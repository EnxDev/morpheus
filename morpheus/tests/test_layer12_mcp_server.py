"""Layer 12 — MCP Server: Intent Guard Tools"""

from tests.harness import run, section, OLLAMA_AVAILABLE


def register(run_fn=run):
    section("Layer 12 — MCP Server: Intent Guard Tools")

    def test_12_1():
        from mcp_server import get_audit_log
        result = get_audit_log(5)
        assert "events" in result
        assert "summary" in result

    skip_llm = None if OLLAMA_AVAILABLE else "Ollama not running"

    def test_12_2():
        from mcp_server import parse_query
        result = parse_query("revenue Q1 2025 by region")
        assert "intent" in result
        assert "low_confidence" in result
        assert "session_id" in result

    def test_12_3():
        from mcp_server import clarify_field, parse_query
        parsed = parse_query("how are we doing?")
        session_id = parsed["session_id"]
        result = clarify_field(session_id, "measure", "revenue")
        assert "intent" in result

    run_fn("12.1", "get_audit_log() returns events + summary", test_12_1)
    run_fn("12.2", "parse_query returns intent + low_confidence", test_12_2, skip_reason=skip_llm)
    run_fn("12.3", "clarify_field updates intent", test_12_3, skip_reason=skip_llm)
