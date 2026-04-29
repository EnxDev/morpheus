"""Intent-Based Access Control (IBAC) — authorization tuple model.

Implements the IBAC pattern: validated intent generates authorization tuples
that constrain every subsequent operation. No operation executes without
a matching tuple.

Architecture:
    Intent validated (Control 1)
      → IntentPolicyMapper generates AuthorizationTuples
      → Each execution step verified by TupleEvaluator
      → Only steps matching a tuple are allowed

The TupleEvaluator is a Protocol — default implementation is deterministic
Python with no dependencies. Can be replaced with Cedar, OPA, or OpenFGA
for enterprise deployments without changing the interface.

Key rule: if a field used to resolve a tuple has low confidence,
the tuple is NOT generated → the step is BLOCKED, not silently degraded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


# ── Sentinel for unknown action ──────────────────────────────────────────────
#
# Returned by ``DeterministicEvaluator._infer_action_resource`` when a step
# name does not match any English-prefix pattern. NOT a real IBAC action —
# it is intentionally outside the ``{read, write, execute, delete, *}``
# vocabulary so an operator-declared tuple with a concrete action never
# matches it. Only an explicit ``*`` action wildcard tuple (operator opt-in
# to "allow anything") authorises a step with this action.
#
# See the "IBAC fail-open fix for non-English step names" entry in
# CHANGELOG.md for rationale and migration guidance.
_UNKNOWN_ACTION = "unknown"


# ── Data structures ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthorizationTuple:
    """A single authorization grant.

    Format follows the FGA pattern: principal:action#resource
    with optional constraints.

    Examples:
        AuthorizationTuple("E003", "read", "payroll:E003")
        AuthorizationTuple("E003", "read", "employee:E003", constraints={"fields": ["name"]})
        AuthorizationTuple("E003", "execute", "query_chart", constraints={"max_rows": 1000})
    """

    principal: str          # who (user ID, role, or "system")
    action: str             # what (read, write, execute, delete)
    resource: str           # on what (resource:scope pattern)
    constraints: dict[str, Any] = field(default_factory=dict)

    def matches(
        self,
        action: str,
        resource: str,
        sensitive_resources: set[str] | None = None,
    ) -> bool:
        """Check if this tuple authorizes a given action on a resource.

        Supports wildcard matching:
            resource="payroll:*" matches "payroll:E003" and "payroll"
            resource="data:*" matches "data:revenue", "data", "data:anything"

        BUT: if the requested resource is in sensitive_resources,
        wildcards are NOT accepted — only exact match works.

        Examples:
            tuple "read:payroll:*" + resource "payroll:self"      → MATCH
            tuple "read:payroll:*" + resource "payroll:sensitive"
                + sensitive={"payroll:sensitive"}                  → NO MATCH
            tuple "read:payroll:sensitive" + resource "payroll:sensitive" → MATCH (exact)
        """
        if self.action != action and self.action != "*":
            return False
        if self.resource == resource:
            return True
        # Wildcard: "data:*" matches "data:foo" AND "data" (the base)
        if self.resource.endswith(":*"):
            # Block wildcard on sensitive resources
            if sensitive_resources and resource in sensitive_resources:
                return False
            base = self.resource[:-2]    # "data"
            prefix = self.resource[:-1]  # "data:"
            if resource == base or resource.startswith(prefix):
                return True
        return False

    def to_dict(self) -> dict:
        d = {
            "principal": self.principal,
            "action": self.action,
            "resource": self.resource,
        }
        if self.constraints:
            d["constraints"] = self.constraints
        return d


@dataclass
class TupleResolutionError:
    """A field required to resolve a tuple could not be resolved."""

    field_name: str
    reason: str  # e.g. "confidence 0.10 below threshold 0.80"


@dataclass
class EvaluationResult:
    """Result of evaluating a step against authorization tuples."""

    allowed: bool
    matched_tuple: AuthorizationTuple | None = None
    reason: str = ""
    step_name: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "matched_tuple": self.matched_tuple.to_dict() if self.matched_tuple else None,
            "reason": self.reason,
            "step_name": self.step_name,
        }


@dataclass
class PolicyMappingResult:
    """Result of mapping an intent to authorization tuples."""

    tuples: list[AuthorizationTuple]
    errors: list[TupleResolutionError]
    action: str

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def to_dict(self) -> dict:
        return {
            "tuples": [t.to_dict() for t in self.tuples],
            "errors": [{"field": e.field_name, "reason": e.reason} for e in self.errors],
            "action": self.action,
            "tuple_count": len(self.tuples),
        }


# ── Tuple template (defined per capability in DomainConfig) ─────────────────

@dataclass
class TupleTemplate:
    """Template for generating authorization tuples from intent fields.

    Defined in DomainConfig per capability. Variables in {braces} are
    resolved from the validated intent at runtime.

    Example:
        TupleTemplate(action="read", resource="payroll:{data_subject}")
        + intent {data_subject: "E003"}
        → AuthorizationTuple(principal, "read", "payroll:E003")
    """

    action: str                          # "read", "write", "execute", "delete"
    resource: str                        # "payroll:{data_subject}", "chart:*"
    constraints: dict[str, Any] = field(default_factory=dict)
    required_fields: list[str] = field(default_factory=list)  # fields that must be resolved

    def resolve(self, principal: str, intent_values: dict[str, str | None]) -> AuthorizationTuple | None:
        """Resolve this template using intent field values.

        Returns None if any required field is missing/null.
        """
        resource = self.resource
        for field_name in self.required_fields:
            value = intent_values.get(field_name)
            if value is None:
                return None
            resource = resource.replace(f"{{{field_name}}}", value)

        resolved_constraints = {}
        for k, v in self.constraints.items():
            if isinstance(v, str) and "{" in v:
                for field_name, field_value in intent_values.items():
                    if field_value is not None:
                        v = v.replace(f"{{{field_name}}}", field_value)
            resolved_constraints[k] = v

        return AuthorizationTuple(
            principal=principal,
            action=self.action,
            resource=resource,
            constraints=resolved_constraints,
        )

    def to_dict(self) -> dict:
        d = {"action": self.action, "resource": self.resource}
        if self.constraints:
            d["constraints"] = self.constraints
        if self.required_fields:
            d["required_fields"] = self.required_fields
        return d


# ── TupleEvaluator Protocol ─────────────────────────────────────────────────

@runtime_checkable
class TupleEvaluator(Protocol):
    """Evaluates whether an execution step is authorized by the tuple set.

    This is the core interface — implement this to swap in Cedar, OPA,
    or OpenFGA without changing any other code.

    Default: DeterministicEvaluator (Python, no dependencies)
    Enterprise: CedarAdapter, OPAAdapter (optional)
    """

    def evaluate(
        self,
        tuples: list[AuthorizationTuple],
        step: dict,
    ) -> EvaluationResult:
        """Check if a step is authorized by any tuple in the set.

        Args:
            tuples: the authorization tuples generated from the validated intent
            step: execution step dict with at least "step" (name) and "type"

        Returns:
            EvaluationResult with allowed=True if a matching tuple was found
        """
        ...


# ── Default deterministic evaluator ─────────────────────────────────────────

class DeterministicEvaluator:
    """Default IBAC evaluator — pure Python, no external dependencies.

    Matching rules:
    1. Pure steps (no side effects) are always allowed
    2. Side-effect steps must match at least one authorization tuple
    3. Reversible steps must match a tuple unless they are preparatory

    Sensitive resources require exact tuple match (wildcards blocked).

    This can be replaced with CedarAdapter or OPAAdapter for enterprise.
    """

    def __init__(self, sensitive_resources: set[str] | None = None) -> None:
        self._sensitive = sensitive_resources or set()

    def evaluate(
        self,
        tuples: list[AuthorizationTuple],
        step: dict,
    ) -> EvaluationResult:
        """Evaluate ``step`` against ``tuples``.

        Pure steps (``type == "pure"``) are always allowed. Side-effect
        and reversible steps must match at least one tuple in the set.

        For steps without an explicit ``requires:`` field, candidates are
        constructed from inference. The execute-fallback candidate is only
        appended when the inferred action is a recognised English verb;
        steps with no recognised prefix get the :data:`_UNKNOWN_ACTION`
        sentinel and the execute fallback is suppressed. This closes the
        fail-open path documented in CHANGELOG.md.
        """
        step_name = step.get("step", "unknown")
        step_type = step.get("type", "unknown")

        # Pure steps are always allowed (no resource access)
        if step_type == "pure":
            return EvaluationResult(
                allowed=True,
                reason=f"Pure step '{step_name}' — no authorization required",
                step_name=step_name,
            )

        # Side-effect and reversible steps need tuple authorization.
        # Use explicit "requires" field if present, otherwise infer.
        #
        # Candidate list construction — tried in order against every tuple:
        #   1. (inferred_action, inferred_resource) — prefix stripped, the
        #      most specific match.
        #   2. (inferred_action, step_name)         — full step name as
        #      resource, in case the operator wrote a tuple keyed on the
        #      raw name.
        #   3. ("execute", step_name)               — generic-execute fallback,
        #      ONLY appended when the inferred action is recognised. When the
        #      step name does not match any English prefix, the inference
        #      returns _UNKNOWN_ACTION and the third candidate is suppressed.
        #      This closes the historical fail-open where a permissive
        #      ``execute:*`` allow tuple silently authorised non-English step
        #      names like ``borrar_registros``. See CHANGELOG.md.
        requires = step.get("requires")
        if requires and ":" in requires:
            # Explicit declaration: "read:data", "write:export"
            parts = requires.split(":", 1)
            candidates = [(parts[0], parts[1])]
        else:
            step_action, step_resource = self._infer_action_resource(step_name)
            candidates = [(step_action, step_resource), (step_action, step_name)]
            if step_action != _UNKNOWN_ACTION:
                candidates.append(("execute", step_name))

        for action, resource in candidates:
            for t in tuples:
                if t.matches(action, resource, self._sensitive):
                    return EvaluationResult(
                        allowed=True,
                        matched_tuple=t,
                        reason=f"Step '{step_name}' authorized by tuple {t.action}#{t.resource}",
                        step_name=step_name,
                    )

        return EvaluationResult(
            allowed=False,
            reason=f"Step '{step_name}' ({step_type}) has no matching authorization tuple. "
                   f"Tried: {candidates}",
            step_name=step_name,
        )

    def _infer_action_resource(self, step_name: str) -> tuple[str, str]:
        """Infer action and resource from step name conventions.

        The prefix table is curated for English verb conventions
        (``fetch_``, ``send_``, ``delete_``, etc.). Step names that do
        not match any prefix — non-English names, custom vocabularies,
        unconventional spellings — return :data:`_UNKNOWN_ACTION` for
        the action component. This is intentional: callers MUST treat
        the unknown sentinel as "no inference possible" rather than
        falling back to a permissive default. See CHANGELOG.md for the
        security rationale (the historical default of ``"execute"``
        was a fail-open path).

        Examples:
            "fetch_payroll_data"  → ("read", "payroll_data")
            "send_email"          → ("write", "email")
            "delete_records"      → ("delete", "records")
            "borrar_registros"    → ("unknown", "borrar_registros")
        """
        name = step_name.lower()

        # Action inference from prefix
        if name.startswith(("fetch_", "get_", "read_", "query_", "check_", "verify_")):
            action = "read"
        elif name.startswith(("delete_", "remove_", "drop_", "purge_")):
            action = "delete"
        elif name.startswith(("send_", "submit_", "create_", "write_", "update_", "save_", "notify_")):
            action = "write"
        elif name.startswith(("format_", "render_", "compute_", "build_", "identify_", "resolve_")):
            return "read", step_name  # preparatory, treated as read
        else:
            # No prefix matched — return the unknown sentinel rather than
            # the permissive "execute" default. See module docstring for
            # _UNKNOWN_ACTION and CHANGELOG.md for migration guidance.
            action = _UNKNOWN_ACTION

        # Resource inference: strip the action prefix
        for prefix in ("fetch_", "get_", "read_", "query_", "delete_", "remove_",
                        "send_", "submit_", "create_", "write_", "update_", "save_",
                        "check_", "verify_", "notify_", "format_", "render_",
                        "compute_", "build_", "log_"):
            if name.startswith(prefix):
                resource = name[len(prefix):]
                return action, resource

        return action, step_name


# ── Intent Policy Mapper ────────────────────────────────────────────────────

class IntentPolicyMapper:
    """Maps a validated intent to authorization tuples using domain config.

    Key rule: if a field required to resolve a tuple has low confidence
    (below threshold), the tuple is NOT generated and an error is recorded.
    This means the step requiring that tuple will be BLOCKED.
    """

    def map(
        self,
        intent_values: dict[str, str | None],
        intent_confidences: dict[str, float],
        templates: list[TupleTemplate],
        thresholds: dict[str, float],
        principal: str = "system",
        action_name: str = "",
    ) -> PolicyMappingResult:
        """Generate authorization tuples from intent + templates.

        Args:
            intent_values: field_name → top value (or None)
            intent_confidences: field_name → confidence score
            templates: TupleTemplates from the capability definition
            thresholds: field_name → minimum confidence threshold
            principal: who is making the request
            action_name: the selected action name
        """
        tuples: list[AuthorizationTuple] = []
        errors: list[TupleResolutionError] = []

        for template in templates:
            # Check all required fields have sufficient confidence
            blocked = False
            for req_field in template.required_fields:
                conf = intent_confidences.get(req_field, 0.0)
                threshold = thresholds.get(req_field, 0.7)
                if conf < threshold:
                    errors.append(TupleResolutionError(
                        field_name=req_field,
                        reason=f"confidence {conf:.2f} below threshold {threshold:.2f}",
                    ))
                    blocked = True

                value = intent_values.get(req_field)
                if value is None:
                    errors.append(TupleResolutionError(
                        field_name=req_field,
                        reason=f"field value is null",
                    ))
                    blocked = True

            if blocked:
                continue

            resolved = template.resolve(principal, intent_values)
            if resolved is not None:
                tuples.append(resolved)

        return PolicyMappingResult(
            tuples=tuples,
            errors=errors,
            action=action_name,
        )
