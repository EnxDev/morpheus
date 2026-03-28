"""Policy engine for the MCP Proxy (Control 2).

Two distinct levels of control:
  Level 1 — Deterministic (always active): pattern matching, explicit rules
  Level 2 — LLM-Assisted Coherence Check (optional): semantic coherence via Ollama

The LLM proposes a score. The threshold decides. The LLM never decides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from typing import Any

from llm import get_default_provider


# ── Risk patterns ─────────────────────────────────────────────────────────────

RISK_PATTERNS: dict[str, list[str]] = {
    "high":   ["delete_*", "remove_*", "drop_*", "destroy_*", "purge_*"],
    "medium": ["send_*", "create_*", "update_*", "write_*", "post_*", "approve_*", "request_*", "export_*"],
    "low":    ["get_*", "list_*", "read_*", "fetch_*", "search_*", "query_*", "view_*"],
}


def classify_risk(tool_name: str) -> str:
    """Classify tool risk using fnmatch against RISK_PATTERNS.

    Returns "high", "medium", "low", or "unknown".
    """
    for level, patterns in RISK_PATTERNS.items():
        for pattern in patterns:
            if fnmatch(tool_name, pattern):
                return level
    return "unknown"


# ── Level 1: Deterministic ───────────────────────────────────────────────────

@dataclass
class PolicyRule:
    """Explicit policy rule for a tool pattern."""

    tool_pattern: str                              # e.g. "send_*"
    risk_level: str = ""                           # "high" | "medium" | "low"
    blocked_for_roles: list[str] | None = None     # block if user has this role
    require_intent_field: str | None = None        # block if this field missing in intent
    requires_confirmation: bool = False            # default True for high risk
    auto_approve: bool = False                     # default True for low risk
    max_calls_per_session: int | None = None


DEFAULT_RULES: dict[str, PolicyRule] = {
    "high": PolicyRule(
        tool_pattern="*",
        risk_level="high",
        requires_confirmation=True,
        auto_approve=False,
    ),
    "medium": PolicyRule(
        tool_pattern="*",
        risk_level="medium",
        requires_confirmation=False,
        auto_approve=False,
    ),
    "low": PolicyRule(
        tool_pattern="*",
        risk_level="low",
        requires_confirmation=False,
        auto_approve=True,
    ),
    "unknown": PolicyRule(
        tool_pattern="*",
        risk_level="unknown",
        requires_confirmation=True,
        auto_approve=False,
    ),
}


@dataclass
class L1Decision:
    """Result of Level 1 deterministic check."""

    status: str  # "approved" | "blocked" | "bypassed" | "passed_to_level_2"
    reason: str
    risk_level: str = "unknown"
    rule_applied: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "risk_level": self.risk_level,
            "rule_applied": self.rule_applied,
        }


# Session rate limiting
_session_call_counts: dict[str, dict[str, int]] = {}


def reset_session(session_id: str) -> None:
    _session_call_counts.pop(session_id, None)


def _increment_call_count(session_id: str, tool_name: str) -> int:
    if session_id not in _session_call_counts:
        _session_call_counts[session_id] = {}
    counts = _session_call_counts[session_id]
    counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts[tool_name]


# ── Level 2: LLM-Assisted Coherence ─────────────────────────────────────────

@dataclass
class CoherenceResult:
    """Result of LLM-assisted coherence check."""

    coherence_score: float  # 0.0 to 1.0
    reason: str = ""
    llm_used: bool = True

    def to_dict(self) -> dict:
        return {
            "coherence_score": self.coherence_score,
            "reason": self.reason,
            "llm_used": self.llm_used,
        }


COHERENCE_PROMPT_TEMPLATE = """Given the user's validated intent:
{intent}

And the action about to be executed:
Tool: {tool_name}
Arguments: {arguments}

Are the arguments semantically coherent with the intent?
Think step by step, then return ONLY a JSON object:
{{"coherence_score": <float 0.0 to 1.0>, "reason": "<one sentence>"}}"""

DEFAULT_COHERENCE_THRESHOLD = 0.70

def check_coherence_llm(
    tool_name: str,
    arguments: dict,
    original_intent: dict,
    threshold: float = DEFAULT_COHERENCE_THRESHOLD,
) -> CoherenceResult:
    """Call LLM to check semantic coherence.

    The LLM returns a coherence_score. The threshold decides.
    The LLM never decides.
    """
    prompt = COHERENCE_PROMPT_TEMPLATE.format(
        intent=json.dumps(original_intent, indent=2),
        tool_name=tool_name,
        arguments=json.dumps(arguments, indent=2),
    )

    try:
        raw = get_default_provider().generate(prompt)

        # Parse JSON from LLM response
        # Strip markdown code fences if present
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()

        parsed = json.loads(cleaned)
        score = float(parsed.get("coherence_score", 0.0))
        reason = str(parsed.get("reason", ""))

        return CoherenceResult(
            coherence_score=max(0.0, min(1.0, score)),
            reason=reason,
            llm_used=True,
        )
    except Exception as e:
        # LLM unavailable or failed — return low score as safe default
        return CoherenceResult(
            coherence_score=0.0,
            reason=f"Coherence check failed: {e}",
            llm_used=False,
        )


# ── Output Schema Validation (post-execution) ───────────────────────────────

@dataclass
class OutputValidationResult:
    """Result of validating tool output against its declared outputSchema."""

    valid: bool
    reason: str | None = None


def validate_output(result: dict, output_schema: dict | None) -> OutputValidationResult:
    """Validate tool result against its declared outputSchema.

    Does NOT block execution — logs warning in audit trail.
    """
    if output_schema is None:
        return OutputValidationResult(valid=True)

    content_to_validate = result
    if isinstance(result, dict) and "structuredContent" in result:
        content_to_validate = result["structuredContent"]

    try:
        import jsonschema
        jsonschema.validate(instance=content_to_validate, schema=output_schema)
        return OutputValidationResult(valid=True)
    except Exception as e:
        return OutputValidationResult(
            valid=False,
            reason=f"Output schema validation failed: {e}",
        )


# ── Combined ActionDecision ──────────────────────────────────────────────────

@dataclass
class ActionDecision:
    """Combined result of Level 1 + Level 2 policy check."""

    status: str  # "approved" | "blocked" | "bypassed"
    reason: str
    tool_name: str
    risk_level: str = "unknown"
    level_1_result: L1Decision | None = None
    level_2_result: CoherenceResult | None = None
    policy_applied: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    controls_active: dict[str, bool] = field(default_factory=lambda: {
        "input_validation": True,
        "action_validation": True,
        "coherence_check": True,
    })

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "status": self.status,
            "reason": self.reason,
            "tool_name": self.tool_name,
            "risk_level": self.risk_level,
            "policy_applied": self.policy_applied,
            "timestamp": self.timestamp,
            "controls_active": self.controls_active,
            "level_1_result": self.level_1_result.to_dict() if self.level_1_result else None,
            "level_2_result": self.level_2_result.to_dict() if self.level_2_result else None,
        }
        return d


# ── Policy Checker ───────────────────────────────────────────────────────────

class PolicyChecker:
    """Combined Level 1 + Level 2 policy checker.

    check_action flow:
      1. Run Level 1 (deterministic)
      2. If L1 = blocked or bypassed -> return immediately
      3. If L1 = approved -> return approved (Level 2 not needed)
      4. If L1 = passed_to_level_2 and coherence_check enabled:
           run Level 2 coherence check, apply threshold
      5. If L1 = passed_to_level_2 and coherence_check disabled:
           return bypassed (Level 2 was skipped intentionally)
    """

    def __init__(
        self,
        known_tools: set[str] | None = None,
        custom_rules: list[PolicyRule] | None = None,
        coherence_threshold: float = DEFAULT_COHERENCE_THRESHOLD,
    ) -> None:
        self._known_tools = known_tools or set()
        self._custom_rules = custom_rules or []
        self._coherence_threshold = coherence_threshold

    def set_known_tools(self, tool_names: set[str]) -> None:
        self._known_tools = tool_names

    def add_rule(self, rule: PolicyRule) -> None:
        self._custom_rules.append(rule)

    def _find_rule(self, tool_name: str, risk_level: str) -> PolicyRule:
        for rule in self._custom_rules:
            if fnmatch(tool_name, rule.tool_pattern):
                return rule
        return DEFAULT_RULES.get(risk_level, DEFAULT_RULES["unknown"])

    # ── Level 1 ──────────────────────────────────────────────────────────

    def _check_level_1(
        self,
        tool_name: str,
        arguments: dict,
        original_intent: dict | None,
        controls_active: dict[str, bool],
        session_id: str,
        user_role: str | None,
    ) -> L1Decision:
        """Level 1: Fully deterministic. No LLM involved."""

        # Bypassed
        if not controls_active.get("action_validation", True):
            return L1Decision(
                status="bypassed",
                reason="Action validation (Control 2) is disabled",
                rule_applied="bypass",
            )

        # Classify risk
        risk_level = classify_risk(tool_name)

        # Find rule
        rule = self._find_rule(tool_name, risk_level)
        rule_name = f"rule:{rule.tool_pattern}:{risk_level}"

        # Rate limit
        if rule.max_calls_per_session is not None:
            count = _increment_call_count(session_id, tool_name)
            if count > rule.max_calls_per_session:
                return L1Decision(
                    status="blocked",
                    reason=f"Rate limit exceeded for '{tool_name}': {count}/{rule.max_calls_per_session}",
                    risk_level=risk_level,
                    rule_applied=f"{rule_name}:rate_limited",
                )

        # Role check
        if rule.blocked_for_roles and user_role and user_role in rule.blocked_for_roles:
            return L1Decision(
                status="blocked",
                reason=f"Tool '{tool_name}' is blocked for role '{user_role}'",
                risk_level=risk_level,
                rule_applied=f"{rule_name}:role_blocked",
            )

        # Require intent field
        if rule.require_intent_field and original_intent is not None:
            if rule.require_intent_field not in original_intent or original_intent[rule.require_intent_field] is None:
                return L1Decision(
                    status="blocked",
                    reason=f"Tool '{tool_name}' requires intent field '{rule.require_intent_field}'",
                    risk_level=risk_level,
                    rule_applied=f"{rule_name}:missing_field",
                )

        # High risk requires confirmation
        if risk_level == "high" and rule.requires_confirmation:
            return L1Decision(
                status="blocked",
                reason=f"High-risk tool '{tool_name}' requires confirmation",
                risk_level=risk_level,
                rule_applied=f"{rule_name}:requires_confirmation",
            )

        # Low risk auto-approve
        if risk_level == "low" and rule.auto_approve:
            return L1Decision(
                status="approved",
                reason=f"Low-risk tool '{tool_name}' auto-approved",
                risk_level=risk_level,
                rule_applied=f"{rule_name}:auto_approved",
            )

        # Medium/unknown risk — pass to Level 2
        return L1Decision(
            status="passed_to_level_2",
            reason=f"Tool '{tool_name}' (risk={risk_level}) passed to Level 2 coherence check",
            risk_level=risk_level,
            rule_applied=f"{rule_name}:passed_to_l2",
        )

    # ── Combined check ───────────────────────────────────────────────────

    def check_action(
        self,
        tool_name: str,
        arguments: dict,
        original_intent: dict | None = None,
        controls_active: dict[str, bool] | None = None,
        session_id: str = "default",
        user_role: str | None = None,
    ) -> ActionDecision:
        """Run Level 1, then Level 2 if needed."""
        if controls_active is None:
            controls_active = {"input_validation": True, "action_validation": True, "coherence_check": True}

        # Step 1: Run Level 1
        l1 = self._check_level_1(tool_name, arguments, original_intent, controls_active, session_id, user_role)

        # Step 2: L1 blocked or bypassed — return immediately
        if l1.status in ("blocked", "bypassed"):
            return ActionDecision(
                status=l1.status,
                reason=l1.reason,
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=None,
                policy_applied=l1.rule_applied,
                controls_active=controls_active,
            )

        # Step 3: L1 approved — return approved (Level 2 not needed)
        if l1.status == "approved":
            return ActionDecision(
                status="approved",
                reason=l1.reason,
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=None,
                policy_applied=l1.rule_applied,
                controls_active=controls_active,
            )

        # Step 4: L1 = passed_to_level_2
        if not controls_active.get("coherence_check", True):
            # Step 5: coherence_check disabled — bypassed
            return ActionDecision(
                status="bypassed",
                reason="Level 2 coherence check is disabled — action bypassed",
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=None,
                policy_applied=f"{l1.rule_applied}:l2_bypassed",
                controls_active=controls_active,
            )

        # Step 4: Run Level 2 coherence check
        if original_intent is None:
            # No intent to check against — approve by default
            return ActionDecision(
                status="approved",
                reason="No intent provided for coherence check — approved",
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=None,
                policy_applied=f"{l1.rule_applied}:no_intent",
                controls_active=controls_active,
            )

        l2 = check_coherence_llm(tool_name, arguments, original_intent, self._coherence_threshold)

        if l2.coherence_score >= self._coherence_threshold:
            return ActionDecision(
                status="approved",
                reason=f"Coherence check passed (score={l2.coherence_score:.2f}, threshold={self._coherence_threshold})",
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=l2,
                policy_applied=f"{l1.rule_applied}:l2_approved",
                controls_active=controls_active,
            )
        else:
            return ActionDecision(
                status="blocked",
                reason=f"Coherence check failed (score={l2.coherence_score:.2f}, threshold={self._coherence_threshold}): {l2.reason}",
                tool_name=tool_name,
                risk_level=l1.risk_level,
                level_1_result=l1,
                level_2_result=l2,
                policy_applied=f"{l1.rule_applied}:l2_blocked",
                controls_active=controls_active,
            )

    # ── Output validation (post-execution) ───────────────────────────────

    def check_output(
        self,
        tool_name: str,
        result: dict,
        output_schema: dict | None,
        controls_active: dict[str, bool] | None = None,
    ) -> OutputValidationResult:
        """Validate tool output against declared outputSchema. Does not block."""
        return validate_output(result, output_schema)
