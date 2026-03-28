"""Layer 13 — FastAPI Endpoints"""

import requests as req

from tests.harness import run, section, BACKEND_AVAILABLE, OLLAMA_AVAILABLE


def register(run_fn=run):
    section("Layer 13 — FastAPI Endpoints")

    skip_api = None if BACKEND_AVAILABLE else "Backend not running on :8000"
    skip_api_llm = None if (BACKEND_AVAILABLE and OLLAMA_AVAILABLE) else "Backend or Ollama not running"

    def test_13_1():
        r = req.get("http://localhost:8000/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_13_2():
        r = req.post("http://localhost:8000/api/parse", json={"query": "revenue Q1 2025 by region"})
        assert r.status_code == 200
        data = r.json()
        assert "intent" in data
        assert "low_confidence" in data

    def test_13_3():
        r = req.get("http://localhost:8000/api/controls")
        assert r.status_code == 200
        data = r.json()
        assert "input_validation" in data

    def test_13_4():
        r = req.get("http://localhost:8000/audit")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_13_5():
        r = req.get("http://localhost:8000/audit/summary")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_13_6():
        r = req.get("http://localhost:8000/audit/export?format=json")
        assert r.status_code == 200

    def test_13_7():
        r = req.get("http://localhost:8000/audit/export?format=csv")
        assert r.status_code == 200
        assert "event_type" in r.text

    def test_13_8():
        r = req.get("http://localhost:8000/api/domains")
        assert r.status_code == 200
        data = r.json()
        assert "generic_bi" in data

    def test_13_9():
        """ResponseSizeGuard: input over Pydantic max_length rejected at 422."""
        # ParseRequest.query has max_length=10000 (Pydantic validation)
        oversized_query = "x" * 10001
        r = req.post("http://localhost:8000/api/parse", json={"query": oversized_query})
        assert r.status_code == 422, f"Expected 422, got {r.status_code}"

    def test_13_10():
        """Sanitizer: input below Pydantic limit but above sanitizer limit is truncated, not rejected."""
        # Pydantic max_length=10000, sanitizer MAX_INPUT_LENGTH=2000
        # Input passes Pydantic but gets truncated by sanitizer — should not crash
        long_but_valid = "revenue " * 400  # ~3200 chars, under 10000
        r = req.post("http://localhost:8000/api/parse", json={"query": long_but_valid})
        # Should succeed (sanitizer truncates, LLM parses the truncated version)
        # or 502 if LLM is down — but NOT 500 (internal error)
        assert r.status_code in (200, 502), f"Expected 200 or 502, got {r.status_code}"

    run_fn("13.1", "GET /health returns ok", test_13_1, skip_reason=skip_api)
    run_fn("13.2", "POST /api/parse returns intent", test_13_2, skip_reason=skip_api_llm)
    run_fn("13.3", "GET /api/controls returns state", test_13_3, skip_reason=skip_api)
    run_fn("13.4", "GET /audit returns event list", test_13_4, skip_reason=skip_api)
    run_fn("13.5", "GET /audit/summary returns counts", test_13_5, skip_reason=skip_api)
    run_fn("13.6", "GET /audit/export?format=json works", test_13_6, skip_reason=skip_api)
    run_fn("13.7", "GET /audit/export?format=csv has headers", test_13_7, skip_reason=skip_api)
    run_fn("13.8", "GET /api/domains lists superset", test_13_8, skip_reason=skip_api)
    run_fn("13.9", "POST /api/parse rejects query > 10000 chars", test_13_9, skip_reason=skip_api)
    run_fn("13.10", "Sanitizer truncates long input without crashing", test_13_10, skip_reason=skip_api_llm)
