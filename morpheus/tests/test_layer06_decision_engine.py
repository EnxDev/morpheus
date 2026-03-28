"""Layer 6 — Decision Engine"""

from tests.harness import run, section
from intent.schema import INTENT_FIELDS
from decision_engine.engine import select_action
from tests.test_layer03_confidence_policy import _make_intent


def register(run_fn=run):
    section("Layer 6 — Decision Engine")

    def test_6_1():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        result = select_action(intent)
        assert result is not None
        assert "action" in result

    def test_6_2():
        intent = _make_intent({})
        result = select_action(intent)
        assert result is None

    def test_6_3():
        intent = _make_intent({f: 0.95 for f in INTENT_FIELDS})
        r1 = select_action(intent)
        r2 = select_action(intent)
        assert r1["action"] == r2["action"]
        assert r1["score"] == r2["score"]

    run_fn("6.1", "select_action returns action for resolved intent", test_6_1)
    run_fn("6.2", "select_action returns None for empty intent", test_6_2)
    run_fn("6.3", "Score is deterministic (same input → same output)", test_6_3)
