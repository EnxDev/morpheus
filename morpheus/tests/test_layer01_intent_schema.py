"""Layer 1 — Intent Schema"""

from tests.harness import run, section
from intent.schema import DynamicIntent, Hypothesis, INTENT_FIELDS


def register(run_fn=run):
    section("Layer 1 — Intent Schema")

    def test_1_1():
        try:
            Hypothesis(value="x", confidence=-0.1)
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_1_2():
        try:
            Hypothesis(value="x", confidence=1.1)
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_1_3():
        Hypothesis(value="x", confidence=0.0)
        Hypothesis(value="x", confidence=1.0)

    def test_1_4():
        data = {f: [{"value": "test", "confidence": 0.9}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        assert intent.top("measure") == "test"

    def test_1_5():
        data = {f: [{"value": f"val_{f}", "confidence": 0.8}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        d = intent.to_dict()
        intent2 = DynamicIntent.from_dict(d, INTENT_FIELDS)
        assert intent2.top("measure") == "val_measure"

    def test_1_6():
        data = {"measure": [{"value": "low", "confidence": 0.3}, {"value": "high", "confidence": 0.9}]}
        for f in INTENT_FIELDS:
            if f != "measure":
                data[f] = [{"value": None, "confidence": 0.0}]
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        top = intent.top("measure")
        assert top in ("low", "high")

    def test_1_7():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        assert intent.top("measure") is None

    def test_1_8():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        assert intent.is_empty("measure") is True

    def test_1_9():
        custom_fields = ("custom_a", "custom_b")
        data = {f: [Hypothesis(value=f"val_{f}", confidence=0.9)] for f in custom_fields}
        intent = DynamicIntent(custom_fields, data)
        assert intent.top("custom_a") == "val_custom_a"

    run_fn("1.1", "Hypothesis rejects confidence < 0.0", test_1_1)
    run_fn("1.2", "Hypothesis rejects confidence > 1.0", test_1_2)
    run_fn("1.3", "Hypothesis accepts boundaries 0.0 and 1.0", test_1_3)
    run_fn("1.4", "DynamicIntent.from_dict() creates intent", test_1_4)
    run_fn("1.5", "DynamicIntent round-trip (from_dict → to_dict → from_dict)", test_1_5)
    run_fn("1.6", "DynamicIntent.top() returns highest confidence", test_1_6)
    run_fn("1.7", "DynamicIntent.top() returns None for null-only", test_1_7)
    run_fn("1.8", "DynamicIntent.is_empty() for null field", test_1_8)
    run_fn("1.9", "DynamicIntent with custom field names", test_1_9)
