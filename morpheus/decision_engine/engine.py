from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent.schema import DynamicIntent
from domain.config import DomainConfig, CapabilityDefinition
from domain.registry import DomainRegistry


def field_resolved(intent: DynamicIntent, field: str, threshold: float) -> bool:
    hyps = intent.get_hypotheses(field)
    if not hyps:
        return False
    top = max(hyps, key=lambda h: h.confidence)
    return top.value is not None and top.confidence >= threshold


def _value_matches(actual: str | None, expected: str | list[str]) -> bool:
    """Check if an intent field value matches one of the expected values."""
    if not actual:
        return False
    actual_lower = actual.lower().strip()
    if isinstance(expected, str):
        return actual_lower == expected.lower().strip()
    return actual_lower in [e.lower().strip() for e in expected]


def score_capability(
    intent: DynamicIntent,
    capability: CapabilityDefinition,
    config: DomainConfig,
) -> float:
    total_possible = sum(capability.field_weights.values())
    if total_possible == 0:
        return 0.0

    earned = 0.0
    for field_name, importance in capability.field_weights.items():
        if importance == 0.0:
            continue
        try:
            threshold = config.get_field(field_name).threshold
        except KeyError:
            continue

        hyps = intent.get_hypotheses(field_name)
        if field_resolved(intent, field_name, threshold):
            earned += importance

            # match_fields: if the capability declares expected values for a field,
            # boost when the intent matches, strongly penalize when it doesn't.
            # A mismatch means this capability is semantically wrong for the intent.
            if field_name in capability.match_fields and hyps:
                top = max(hyps, key=lambda h: h.confidence)
                expected = capability.match_fields[field_name]
                if _value_matches(top.value, expected):
                    earned += importance * 0.25
                elif top.value:
                    # Strong penalty: the field is resolved but the value doesn't
                    # match what this capability expects. Reduce the field's
                    # contribution to near zero.
                    earned -= importance * 0.75
        else:
            # Partial credit: field exists but below threshold
            if hyps:
                top = max(hyps, key=lambda h: h.confidence)
                if top.value is not None:
                    ratio = top.confidence / threshold
                    earned += importance * ratio * 0.5

    return earned / total_possible


def _match_fields_pass(intent: DynamicIntent, capability: CapabilityDefinition) -> bool:
    """Check if all match_fields in the capability match the intent.

    If the capability has no match_fields, it always passes (legacy behavior).
    If it has match_fields:
      - Resolved fields must match the expected values
      - Unresolved/null fields cause the capability to be REJECTED
        (a null critical field means the intent is too vague for this action)
    """
    if not capability.match_fields:
        return True
    for field_name, expected in capability.match_fields.items():
        hyps = intent.get_hypotheses(field_name)
        if not hyps:
            return False  # required match field missing entirely
        top = max(hyps, key=lambda h: h.confidence)
        # If field is null or very low confidence → capability doesn't match
        if not top.value or top.confidence < 0.4:
            return False
        # Field has a value — check if it matches expected
        if not _value_matches(top.value, expected):
            return False
    return True


def select_action(intent: DynamicIntent, config: DomainConfig | None = None) -> dict | None:
    if config is None:
        config = DomainRegistry.default()

    candidates = []
    for cap in config.capabilities:
        # Skip capabilities where match_fields don't align with the intent
        if not _match_fields_pass(intent, cap):
            continue
        s = score_capability(intent, cap, config)
        if s >= cap.min_score:
            candidates.append({
                "action": cap.action,
                "score": s,
                "capability": cap,
            })

    if not candidates:
        return None

    best = max(candidates, key=lambda c: c["score"])
    return {
        "action":    best["action"],
        "score":     best["score"],
        "explained": explain(intent, best["capability"], config),
        "dryRun":    True,
    }


def explain(
    intent: DynamicIntent,
    capability: CapabilityDefinition,
    config: DomainConfig,
) -> dict[str, float]:
    result = {}
    for field_name in capability.field_weights:
        hyps = intent.get_hypotheses(field_name)
        if hyps:
            top = max(hyps, key=lambda h: h.confidence)
            result[field_name] = top.confidence if top.value is not None else 0.0
        else:
            result[field_name] = 0.0
    return result


if __name__ == "__main__":
    from intent.schema import Hypothesis, SupersetIntent

    mock = SupersetIntent(
        measure=[Hypothesis(value="revenue", confidence=0.95)],
        dimension=[Hypothesis(value="by region", confidence=0.88)],
        time_range=[Hypothesis(value="Q1 2025", confidence=0.96)],
        filters=[Hypothesis(value="online only", confidence=0.91)],
        granularity=[Hypothesis(value="monthly", confidence=0.85)],
        comparison=[Hypothesis(value="vs Q1 2024", confidence=0.94)],
    )
    result = select_action(mock)
    if result:
        print(result["action"])
    else:
        print("No action selected")
