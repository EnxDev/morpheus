"""Layer 3d — Session Guard (cross-iteration)"""

from tests.harness import run, section
from intent.schema import DynamicIntent, INTENT_FIELDS
from parser.session_guard import SessionGuard


def register(run_fn=run):
    section("Layer 3d — Session Guard (cross-iteration)")

    def test_3d_1():
        guard = SessionGuard()
        data1 = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data1["measure"] = [{"value": "revenue", "confidence": 0.95}]
        intent1 = DynamicIntent.from_dict(data1, INTENT_FIELDS)
        guard.record_iteration(intent1, "time_range", "Q1 2025")

        data2 = dict(data1)
        data2["time_range"] = [{"value": "Q1 2025", "confidence": 0.95}]
        intent2 = DynamicIntent.from_dict(data2, INTENT_FIELDS)
        guard.record_iteration(intent2, "time_range", "Q1 2025")

        anomalies = guard.check_anomalies()
        field_drift = [a for a in anomalies if a.anomaly_type == "field_drift"]
        assert len(field_drift) == 0

    def test_3d_2():
        guard = SessionGuard()
        data1 = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data1["measure"] = [{"value": "revenue", "confidence": 0.95}]
        intent1 = DynamicIntent.from_dict(data1, INTENT_FIELDS)
        guard.record_iteration(intent1, "time_range", "Q1 2025")

        data2 = {f: [{"value": None, "confidence": 0.0}] for f in INTENT_FIELDS}
        data2["measure"] = [{"value": "delete_all", "confidence": 0.95}]
        data2["time_range"] = [{"value": "Q1 2025", "confidence": 0.95}]
        intent2 = DynamicIntent.from_dict(data2, INTENT_FIELDS)
        guard.record_iteration(intent2, "time_range", "Q1 2025")

        anomalies = guard.check_anomalies()
        drift = [a for a in anomalies if a.anomaly_type == "field_drift"]
        assert len(drift) >= 1
        assert drift[0].field == "measure"

    run_fn("3d.1", "Normal clarification: no anomalies", test_3d_1)
    run_fn("3d.2", "Field drift detected across iterations", test_3d_2)
