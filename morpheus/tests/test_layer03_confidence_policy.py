"""Layer 3 — Confidence Policy"""

from tests.harness import run, section
from intent.schema import DynamicIntent, Hypothesis, INTENT_FIELDS
from policies.confidence_policy import check, next_to_clarify, is_ambiguous


def _make_intent(confidence_map: dict) -> DynamicIntent:
    data = {}
    for f in INTENT_FIELDS:
        c = confidence_map.get(f, 0.0)
        v = f"val_{f}" if c > 0.5 else None
        data[f] = [{"value": v, "confidence": c}]
    return DynamicIntent.from_dict(data, INTENT_FIELDS)


def register(run_fn=run):
    section("Layer 3 — Confidence Policy")

    def test_3_1():
        intent = _make_intent({})
        low = check(intent)
        assert len(low) >= 5

    def test_3_2():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        low = check(intent)
        assert len(low) == 0

    def test_3_3():
        intent = _make_intent({"measure": 0.95, "time_range": 0.95, "dimension": 0.0})
        low = check(intent)
        assert "dimension" in low
        assert "measure" not in low

    def test_3_4():
        intent = _make_intent({"measure": 0.85, "comparison": 0.65})
        low = check(intent)
        assert "measure" in low
        assert "comparison" not in low

    def test_3_5():
        intent = _make_intent({"measure": 0.0, "time_range": 0.0})
        low = check(intent)
        field = next_to_clarify(intent)
        assert field == "measure"

    def test_3_6():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        field = next_to_clarify(intent)
        assert field is None

    def test_3_7():
        hyps = [Hypothesis(value="send_report", confidence=0.72), Hypothesis(value="delete_report", confidence=0.68)]
        assert is_ambiguous(hyps, ambiguity_threshold=0.1) is True

    def test_3_8():
        hyps = [Hypothesis(value="revenue", confidence=0.95), Hypothesis(value="orders", confidence=0.30)]
        assert is_ambiguous(hyps, ambiguity_threshold=0.1) is False

    def test_3_9():
        hyps = [Hypothesis(value="revenue", confidence=0.72)]
        assert is_ambiguous(hyps) is False

    def test_3_10():
        data = {f: [{"value": f"val_{f}", "confidence": 0.95}] for f in INTENT_FIELDS}
        data["measure"] = [
            {"value": "send_report", "confidence": 0.92},
            {"value": "delete_report", "confidence": 0.88},
        ]
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        low = check(intent)
        assert "measure" in low

    run_fn("3.1", "check() returns all fields for null intent", test_3_1)
    run_fn("3.2", "check() returns empty for fully resolved", test_3_2)
    run_fn("3.3", "check() identifies partial intent correctly", test_3_3)
    run_fn("3.4", "check() respects per-field thresholds", test_3_4)
    run_fn("3.5", "next_to_clarify() returns highest-priority field", test_3_5)
    run_fn("3.6", "next_to_clarify() returns None when all resolved", test_3_6)
    run_fn("3.7", "is_ambiguous() detects close hypotheses", test_3_7)
    run_fn("3.8", "is_ambiguous() clears large gap", test_3_8)
    run_fn("3.9", "is_ambiguous() single hypothesis is not ambiguous", test_3_9)
    run_fn("3.10", "check() flags ambiguous field even above threshold", test_3_10)
