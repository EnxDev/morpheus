"""Layer 5 — Clarifier"""

from tests.harness import run, section
from intent.schema import INTENT_FIELDS
from clarifier.clarifier import update_intent, render_confirmation, validate_answer
from domain.registry import DomainRegistry
from tests.test_layer03_confidence_policy import _make_intent


def register(run_fn=run):
    section("Layer 5 — Clarifier")

    config = DomainRegistry.default()

    def test_5_1():
        intent = _make_intent({f: 0.1 for f in INTENT_FIELDS})
        updated, val = update_intent(intent, "measure", "revenue", config)
        hyps = updated.get_hypotheses("measure")
        assert hyps[0].confidence >= 0.85
        assert hyps[0].value == "revenue"

    def test_5_2():
        intent = _make_intent({f: 0.1 for f in INTENT_FIELDS})
        updated, val = update_intent(intent, "measure", "revenue", config)
        orig_hyps = intent.get_hypotheses("measure")
        assert orig_hyps[0].value != "revenue"

    def test_5_3():
        # Empty answer is rejected — intent unchanged
        intent = _make_intent({f: 0.1 for f in INTENT_FIELDS})
        updated, val = update_intent(intent, "measure", "", config)
        assert val.valid is False
        # Intent should not be modified
        assert updated.get_hypotheses("measure")[0].confidence == 0.1

    def test_5_4():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        text = render_confirmation(intent)
        assert "Measure" in text or "measure" in text.lower()

    def test_5_5():
        # Garbage input "ss" should be rejected
        fd = config.get_field("measure")
        val = validate_answer("ss", fd)
        assert val.valid is False

    def test_5_6():
        # Denial "no" — valid, confidence 0.0 from validate_answer
        fd = config.get_field("measure")
        val = validate_answer("no", fd)
        assert val.valid is True
        assert val.confidence == 0.0

    def test_5_9():
        # Denial "no" through update_intent → should use default or skip above threshold
        intent = _make_intent({f: 0.1 for f in INTENT_FIELDS})
        updated, val = update_intent(intent, "granularity", "no", config)
        # granularity has default_value="monthly" → should use it
        hyps = updated.get_hypotheses("granularity")
        assert hyps[0].value == "monthly"
        assert hyps[0].confidence >= 0.90

    def test_5_10():
        # Denial "skip" on field without default → skipped above threshold
        intent = _make_intent({f: 0.1 for f in INTENT_FIELDS})
        updated, val = update_intent(intent, "filters", "skip", config)
        hyps = updated.get_hypotheses("filters")
        assert hyps[0].value is None
        # Confidence should be above threshold so it's not re-asked
        fd = config.get_field("filters")
        assert hyps[0].confidence > fd.threshold

    def test_5_7():
        # Exact match with example should get high confidence
        fd = config.get_field("measure")
        val = validate_answer("revenue", fd)
        assert val.valid is True
        assert val.confidence == 0.95

    def test_5_8():
        # Partial match should get medium confidence
        fd = config.get_field("time_range")
        val = validate_answer("Q1 2025", fd)
        assert val.valid is True
        assert val.confidence >= 0.85

    run_fn("5.1", "update_intent sets confidence for valid answer", test_5_1)
    run_fn("5.2", "update_intent does not mutate original", test_5_2)
    run_fn("5.3", "update_intent with empty answer → null", test_5_3)
    run_fn("5.4", "render_confirmation includes field labels", test_5_4)
    run_fn("5.5", "validate_answer rejects garbage input", test_5_5)
    run_fn("5.6", "validate_answer: 'no' is valid but unresolved", test_5_6)
    run_fn("5.7", "validate_answer: exact example match → 0.95", test_5_7)
    run_fn("5.8", "validate_answer: partial match → high confidence", test_5_8)
    run_fn("5.9", "denial 'no' uses default_value if available", test_5_9)
    run_fn("5.10", "denial 'skip' on no-default field → skipped above threshold", test_5_10)
