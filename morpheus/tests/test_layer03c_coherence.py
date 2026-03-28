"""Layer 3c — Parser Coherence Check"""

from tests.harness import run, section
from intent.schema import DynamicIntent, INTENT_FIELDS
from parser.coherence import check_coherence


def register(run_fn=run):
    section("Layer 3c — Parser Coherence Check")

    def test_3c_1():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data["measure"] = [{"value": "revenue", "confidence": 0.95}]
        data["dimension"] = [{"value": "by region", "confidence": 0.90}]
        data["time_range"] = [{"value": "Q1 2025", "confidence": 0.92}]
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        r = check_coherence("show me revenue by region for Q1 2025", intent)
        assert r.is_coherent is True
        assert r.score >= 0.9

    def test_3c_2():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data["measure"] = [{"value": "delete_database", "confidence": 0.95}]
        data["dimension"] = [{"value": "all_users", "confidence": 0.90}]
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        r = check_coherence("show me revenue by region", intent)
        assert r.is_coherent is False
        assert "measure" in r.incoherent_fields

    def test_3c_3():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        r = check_coherence("how are we doing?", intent)
        assert r.is_coherent is True

    def test_3c_4():
        data = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data["measure"] = [{"value": "revenue", "confidence": 0.95}]
        data["dimension"] = [{"value": "by hacker_table", "confidence": 0.90}]
        intent = DynamicIntent.from_dict(data, INTENT_FIELDS)
        r = check_coherence("show me revenue by region", intent)
        assert "dimension" in r.incoherent_fields
        assert "measure" not in r.incoherent_fields

    run_fn("3c.1", "Coherent intent passes check", test_3c_1)
    run_fn("3c.2", "Incoherent intent detected (injected values)", test_3c_2)
    run_fn("3c.3", "All-null intent is coherent", test_3c_3)
    run_fn("3c.4", "Partial incoherence flags only bad fields", test_3c_4)
