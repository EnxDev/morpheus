"""Layer 4 — Validator"""

from tests.harness import run, section
from intent.schema import DynamicIntent, INTENT_FIELDS
from validator.validator import validate
from tests.test_layer03_confidence_policy import _make_intent


def register(run_fn=run):
    section("Layer 4 — Validator")

    def test_4_1():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        result = validate(intent)
        assert result.is_valid is True

    def test_4_2():
        data = {f: [{"value": "v", "confidence": 0.9}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        intent.set_hypotheses("measure", [])
        result = validate(intent)
        assert result.is_valid is False

    def test_4_3():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        result = validate(intent)
        assert len(result.errors) == 0

    run_fn("4.1", "Valid intent passes deterministic checks", test_4_1)
    run_fn("4.2", "Empty hypothesis list → invalid", test_4_2)
    run_fn("4.3", "Valid intent has no errors", test_4_3)
