"""Layer 11 — MCP Proxy: Server + Discovery"""

import time

from tests.harness import run, section
from tests.mock_mcp_server import start_mock_server

_mock_port_counter = 5020


def _with_mock_server(fn):
    """Decorator: start mock server on unique port, run test, stop."""
    def wrapper():
        global _mock_port_counter
        port = _mock_port_counter
        _mock_port_counter += 1
        server, thread = start_mock_server(port)
        time.sleep(0.3)
        try:
            fn(f"http://127.0.0.1:{port}")
        finally:
            server.shutdown()
    return wrapper


@_with_mock_server
def _test_11_1(url):
    from proxy.discovery import ToolDiscovery
    td = ToolDiscovery(url)
    tools = td.discover()
    assert len(tools) == 4


@_with_mock_server
def _test_11_2(url):
    from proxy.discovery import ToolDiscovery
    td = ToolDiscovery(url)
    tools = td.discover()
    for t in tools:
        assert t.name != ""
        assert t.description != ""
        assert t.input_schema != {}


@_with_mock_server
def _test_11_3(url):
    from proxy.discovery import ToolDiscovery
    td = ToolDiscovery(url)
    tools = td.discover()
    weather = [t for t in tools if t.name == "get_weather"][0]
    assert weather.output_schema is not None


@_with_mock_server
def _test_11_4(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    assert proxy.tool_count == 4


@_with_mock_server
def _test_11_5(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    tools = proxy.get_proxied_tools()
    names = {t["name"] for t in tools}
    assert names == {"send_email", "get_weather", "read_file", "delete_repo"}


@_with_mock_server
def _test_11_6(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    r = proxy.call_tool("get_weather", {"location": "Rome"})
    assert r["status"] == "approved"
    assert "result" in r


@_with_mock_server
def _test_11_7(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    r = proxy.call_tool("delete_repo", {"repo_name": "test"})
    assert r["status"] == "blocked"
    assert r["result"]["isError"] is True


@_with_mock_server
def _test_11_8(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    r = proxy.call_tool("delete_repo", {"repo_name": "test"}, controls_active={
        "input_validation": True, "action_validation": False, "coherence_check": True
    })
    assert r["status"] == "bypassed"


@_with_mock_server
def _test_11_9(url):
    from proxy.proxy_server import MorpheusProxy
    proxy = MorpheusProxy(url)
    proxy.call_tool("get_weather", {"location": "Rome"})
    proxy.call_tool("delete_repo", {"repo_name": "test"})
    events = [e.event_type for e in proxy.logger.get_events()]
    assert "tool_call_intercepted" in events
    assert "policy_decision" in events


def _test_11_10():
    """MCP Bridge: _enforce_response_limit truncates oversized responses."""
    from proxy.mcp_bridge import _enforce_response_limit, MAX_RESPONSE_CHARS
    from audit.logger import AuditLogger

    logger = AuditLogger()
    oversized = "x" * (MAX_RESPONSE_CHARS + 5000)
    result = _enforce_response_limit(oversized, "big_tool", logger)
    assert len(result) < len(oversized)
    assert "[TRUNCATED:" in result
    events = [e.event_type for e in logger.get_events()]
    assert "response_truncated" in events


def _test_11_11():
    """MCP Bridge: _enforce_response_limit passes small responses unchanged."""
    from proxy.mcp_bridge import _enforce_response_limit, MAX_RESPONSE_CHARS
    from audit.logger import AuditLogger

    logger = AuditLogger()
    small = "hello world"
    result = _enforce_response_limit(small, "small_tool", logger)
    assert result == small
    assert len(logger.get_events()) == 0


def _test_11_12():
    """MCP Bridge: _enforce_response_limit warns at 80% threshold."""
    from proxy.mcp_bridge import _enforce_response_limit, MAX_RESPONSE_CHARS, RESPONSE_WARNING_RATIO
    from audit.logger import AuditLogger

    logger = AuditLogger()
    near_limit = "x" * int(MAX_RESPONSE_CHARS * 0.85)
    result = _enforce_response_limit(near_limit, "big_read", logger)
    # Content should pass through unchanged (under limit)
    assert result == near_limit
    # But a warning event should be logged
    events = [e.event_type for e in logger.get_events()]
    assert "response_size_warning" in events


def register(run_fn=run):
    section("Layer 11 — MCP Proxy: Server + Discovery")

    run_fn("11.1", "ToolDiscovery fetches 4 tools from mock server", _test_11_1)
    run_fn("11.2", "Discovered tools have name, description, inputSchema", _test_11_2)
    run_fn("11.3", "get_weather has outputSchema", _test_11_3)
    run_fn("11.4", "MorpheusProxy discovers 4 tools on init", _test_11_4)
    run_fn("11.5", "Proxied tool names match real server", _test_11_5)
    run_fn("11.6", "get_weather → forwarded (approved)", _test_11_6)
    run_fn("11.7", "delete_repo → blocked (isError=true)", _test_11_7)
    run_fn("11.8", "delete_repo with bypass → bypassed + forwarded", _test_11_8)
    run_fn("11.9", "Audit log contains intercepted + decision events", _test_11_9)
    run_fn("11.10", "Response size guard: truncates oversized response", _test_11_10)
    run_fn("11.11", "Response size guard: passes small response unchanged", _test_11_11)
    run_fn("11.12", "Response size guard: warns at 80% threshold", _test_11_12)
