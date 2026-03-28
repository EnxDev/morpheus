from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from intent.schema import DynamicIntent, Hypothesis
from domain.registry import DomainRegistry
from domain.config import DomainConfig

# Backwards-compatible constants (computed from default config on access)
_LAZY_THRESHOLDS = None


def _get_default_thresholds():
    global _LAZY_THRESHOLDS
    if _LAZY_THRESHOLDS is None:
        _LAZY_THRESHOLDS = DomainRegistry.default().thresholds
    return _LAZY_THRESHOLDS


def is_ambiguous(hypotheses: list[Hypothesis], ambiguity_threshold: float = 0.1) -> bool:
    """Check if the top two hypotheses are too close in confidence.

    When two hypotheses have similar confidence, the parser is unsure
    which one is correct. Even if the top one is above the field threshold,
    the intent is still ambiguous and should trigger clarification.

    Example:
        [{"value": "send_report", "confidence": 0.72},
         {"value": "delete_report", "confidence": 0.68}]
        → gap = 0.04 < threshold 0.1 → AMBIGUOUS

    Returns True if the field is ambiguous (top two too close).
    """
    if len(hypotheses) < 2:
        return False
    sorted_hyps = sorted(hypotheses, key=lambda h: h.confidence, reverse=True)
    gap = sorted_hyps[0].confidence - sorted_hyps[1].confidence
    return gap < ambiguity_threshold


def check(intent: DynamicIntent, config: DomainConfig | None = None) -> list[str]:
    """Return field names that need clarification.

    A field needs clarification if:
    1. It has no hypotheses, OR
    2. Its top hypothesis confidence is below the field threshold, OR
    3. Its top two hypotheses are ambiguous (gap < ambiguity_threshold)
    """
    if config is None:
        config = DomainRegistry.default()
    low = []
    for fd in config.fields:
        hyps = intent.get_hypotheses(fd.name)
        if not hyps:
            low.append(fd.name)
            continue
        top = max(hyps, key=lambda h: h.confidence)
        if top.confidence < fd.threshold:
            low.append(fd.name)
            continue
        # Above threshold but ambiguous — two close hypotheses
        if is_ambiguous(hyps, fd.ambiguity_threshold):
            low.append(fd.name)
    return low


def get_threshold(field: str, config: DomainConfig | None = None) -> float:
    if config is None:
        config = DomainRegistry.default()
    return config.get_field(field).threshold


def get_defaults(config: DomainConfig | None = None) -> dict:
    if config is None:
        config = DomainRegistry.default()
    return {fd.name: fd.default_value for fd in config.fields if fd.default_value is not None}


def next_to_clarify(intent: DynamicIntent, config: DomainConfig | None = None) -> str | None:
    if config is None:
        config = DomainRegistry.default()
    low = check(intent, config)
    for field in config.field_priority:
        if field in low:
            return field
    return None


# Backwards compatibility
THRESHOLDS = property(lambda self: _get_default_thresholds())
FIELD_PRIORITY = ["measure", "time_range", "filters", "dimension", "granularity"]


if __name__ == "__main__":
    # Test normal case
    mock = DynamicIntent.from_dict({
        "measure":     [{"value": "revenue", "confidence": 0.92}],
        "dimension":   [{"value": "by region", "confidence": 0.55}],
        "time_range":  [{"value": "Q1 2025", "confidence": 0.95}],
        "filters":     [{"value": None, "confidence": 0.3}],
        "granularity": [{"value": "monthly", "confidence": 0.85}],
        "comparison":  [{"value": None, "confidence": 0.2}],
    })
    result = check(mock)
    print(f"Low confidence fields: {result}")

    # Test ambiguous case
    ambiguous = DynamicIntent.from_dict({
        "measure":     [
            {"value": "send_report", "confidence": 0.72},
            {"value": "delete_report", "confidence": 0.68},
        ],
        "dimension":   [{"value": "by region", "confidence": 0.90}],
        "time_range":  [{"value": "Q1 2025", "confidence": 0.95}],
        "filters":     [{"value": None, "confidence": 0.3}],
        "granularity": [{"value": "monthly", "confidence": 0.85}],
        "comparison":  [{"value": None, "confidence": 0.2}],
    })
    result = check(ambiguous)
    print(f"Ambiguous fields: {result}")
    print(f"  measure is ambiguous: {'measure' in result}")
