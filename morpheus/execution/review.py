"""Execution Plan Review — validates a plan against the intent before execution.

Sits between the Decision Engine and the Execution Engine:

    Intent validated (Control 1)
      → Decision Engine selects action
      → build_plan() generates steps
      → [PlanReviewer: is this plan safe for this intent?]
          → approved  → execute_plan()
          → blocked   → return plan + reason, no execution

Three levels of review (all deterministic except L3):

  L1 — Structural: are step types appropriate for the intent?
        e.g. a read-only query shouldn't have side_effect steps
  L2 — Constraint: do timeouts/retries respect domain limits?
        e.g. total plan timeout shouldn't exceed max allowed
  L3 — Semantic (optional, LLM): is the plan coherent with the intent?
        e.g. intent says "revenue Q1 2025" but plan builds query for "all time"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from execution.plan import STEP_TYPES


# ── Review result ────────────────────────────────────────────────────────────

@dataclass
class PlanReviewResult:
    """Result of a plan review."""

    approved: bool
    issues: list[PlanIssue]
    plan_summary: dict

    @property
    def blocked(self) -> bool:
        return not self.approved

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "blocked": self.blocked,
            "issue_count": len(self.issues),
            "issues": [i.to_dict() for i in self.issues],
            "plan_summary": self.plan_summary,
        }


@dataclass
class PlanIssue:
    """A specific issue found during plan review."""

    level: str  # "L1_structural" | "L2_constraint" | "L3_semantic"
    severity: str  # "error" (blocks) | "warning" (allows but logs)
    step: str | None  # which step, or None for plan-level
    description: str

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "severity": self.severity,
            "step": self.step,
            "description": self.description,
        }


# ── Default constraints ──────────────────────────────────────────────────────

DEFAULT_CONSTRAINTS = {
    "max_total_timeout_ms": 60000,      # 1 minute total
    "max_side_effect_steps": 3,         # max irreversible steps
    "max_retries_per_step": 5,          # prevent retry storms
    "max_plan_steps": 10,               # prevent unbounded plans
    "require_pure_before_side_effect": True,  # at least one pure step before side effects
}


# ── Plan Reviewer ────────────────────────────────────────────────────────────

class PlanReviewer:
    """Reviews an execution plan against the validated intent.

    Usage:
        reviewer = PlanReviewer()
        result = reviewer.review(plan, action_name, intent_dict)
        if result.blocked:
            # don't execute
    """

    def __init__(self, constraints: dict | None = None) -> None:
        self._constraints = {**DEFAULT_CONSTRAINTS, **(constraints or {})}

    def review(
        self,
        plan: list[dict],
        action: str,
        intent: dict | None = None,
    ) -> PlanReviewResult:
        """Review a plan. Returns PlanReviewResult with approval status."""
        issues: list[PlanIssue] = []

        # ── L1: Structural checks ────────────────────────────────────
        issues.extend(self._check_structural(plan))

        # ── L2: Constraint checks ────────────────────────────────────
        issues.extend(self._check_constraints(plan))

        # Build summary
        summary = self._build_summary(plan, action)

        # Blocked if any error-severity issues
        has_errors = any(i.severity == "error" for i in issues)

        return PlanReviewResult(
            approved=not has_errors,
            issues=issues,
            plan_summary=summary,
        )

    # ── L1: Structural ───────────────────────────────────────────────

    def _check_structural(self, plan: list[dict]) -> list[PlanIssue]:
        issues: list[PlanIssue] = []

        if not plan:
            issues.append(PlanIssue(
                level="L1_structural",
                severity="error",
                step=None,
                description="Plan is empty — no steps to execute",
            ))
            return issues

        # Check step count
        max_steps = self._constraints["max_plan_steps"]
        if len(plan) > max_steps:
            issues.append(PlanIssue(
                level="L1_structural",
                severity="error",
                step=None,
                description=f"Plan has {len(plan)} steps, exceeds max {max_steps}",
            ))

        # Check each step has required fields
        for i, step in enumerate(plan):
            if "step" not in step:
                issues.append(PlanIssue(
                    level="L1_structural",
                    severity="error",
                    step=f"step_{i}",
                    description=f"Step {i} missing 'step' field",
                ))
            if "type" not in step:
                issues.append(PlanIssue(
                    level="L1_structural",
                    severity="error",
                    step=step.get("step", f"step_{i}"),
                    description=f"Step {i} missing 'type' field",
                ))
            elif step["type"] not in STEP_TYPES:
                issues.append(PlanIssue(
                    level="L1_structural",
                    severity="warning",
                    step=step.get("step", f"step_{i}"),
                    description=f"Unknown step type '{step['type']}' (expected: {list(STEP_TYPES.keys())})",
                ))

        # Check: step type ordering should follow pure → reversible → side_effect
        # A reversible after a side_effect means inconsistent state on failure.
        # A side_effect before any pure means no read/verify before acting.
        if self._constraints.get("require_pure_before_side_effect", True):
            TYPE_ORDER = {"pure": 0, "reversible": 1, "side_effect": 2}
            highest_seen = -1
            highest_seen_name = ""

            for step in plan:
                step_type = step.get("type", "")
                order = TYPE_ORDER.get(step_type, -1)
                if order < 0:
                    continue  # unknown type, caught above

                if step_type == "side_effect" and highest_seen < 0:
                    # Side-effect before any pure/reversible
                    issues.append(PlanIssue(
                        level="L1_structural",
                        severity="warning",
                        step=step.get("step"),
                        description="Side-effect step before any pure step — plan starts with irreversible action",
                    ))

                if order < highest_seen:
                    # Going backwards: e.g. reversible after side_effect
                    issues.append(PlanIssue(
                        level="L1_structural",
                        severity="warning",
                        step=step.get("step"),
                        description=(
                            f"Step type '{step_type}' appears after '{highest_seen_name}' — "
                            f"expected order: pure → reversible → side_effect. "
                            f"A {step_type} after a {highest_seen_name} risks inconsistent state on failure."
                        ),
                    ))

                if order > highest_seen:
                    highest_seen = order
                    highest_seen_name = step_type

        return issues

    # ── L2: Constraints ──────────────────────────────────────────────

    def _check_constraints(self, plan: list[dict]) -> list[PlanIssue]:
        issues: list[PlanIssue] = []

        # Total timeout
        total_timeout = sum(s.get("timeout_ms", 0) for s in plan)
        max_timeout = self._constraints["max_total_timeout_ms"]
        if total_timeout > max_timeout:
            issues.append(PlanIssue(
                level="L2_constraint",
                severity="error",
                step=None,
                description=f"Total plan timeout {total_timeout}ms exceeds max {max_timeout}ms",
            ))

        # Side effect count
        side_effects = [s for s in plan if s.get("type") == "side_effect"]
        max_se = self._constraints["max_side_effect_steps"]
        if len(side_effects) > max_se:
            issues.append(PlanIssue(
                level="L2_constraint",
                severity="error",
                step=None,
                description=f"Plan has {len(side_effects)} side-effect steps, max is {max_se}",
            ))

        # Per-step retry limit
        max_retries = self._constraints["max_retries_per_step"]
        for step in plan:
            retries = step.get("retry", 0)
            if retries > max_retries:
                issues.append(PlanIssue(
                    level="L2_constraint",
                    severity="error",
                    step=step.get("step"),
                    description=f"Step '{step.get('step')}' has {retries} retries, max is {max_retries}",
                ))

        return issues

    # ── Summary ──────────────────────────────────────────────────────

    def _build_summary(self, plan: list[dict], action: str) -> dict:
        step_types = {}
        for step in plan:
            t = step.get("type", "unknown")
            step_types[t] = step_types.get(t, 0) + 1

        return {
            "action": action,
            "total_steps": len(plan),
            "step_types": step_types,
            "total_timeout_ms": sum(s.get("timeout_ms", 0) for s in plan),
            "total_retries": sum(s.get("retry", 0) for s in plan),
            "has_side_effects": any(s.get("type") == "side_effect" for s in plan),
            "steps": [s.get("step", "?") for s in plan],
        }
