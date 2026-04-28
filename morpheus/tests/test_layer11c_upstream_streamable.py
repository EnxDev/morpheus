"""Layer 11c — MCP Proxy: Upstream streamable-HTTP MCP endpoint.

Covers the upstream MCP server endpoint mounted at ``/mcp/`` on the
HTTP proxy. Symmetric counterpart to layer 11b (which covers the
downstream side). Same harness conventions: sync ``fn`` bodies,
hand-rolled fixtures, no pytest, no pytest-asyncio.

See ``docs/streamable-http-upstream.md`` §10 for the test plan this
file implements; sections fill in across Phase 2 commits.
"""

import time

from tests.harness import run, section
from tests.mock_mcp_server import start_mock_server


# Reuse the layer-11 mock-server pattern. Port range placed above
# layer 11b's 5200+N to stay collision-free.
_layer11c_port_counter = 5400


def _with_mock_server(fn):
    def wrapper():
        global _layer11c_port_counter
        port = _layer11c_port_counter
        _layer11c_port_counter += 1
        server, _thread = start_mock_server(port)
        time.sleep(0.3)
        try:
            fn(f"http://127.0.0.1:{port}")
        finally:
            server.shutdown()
    return wrapper


# ── Group A.0 — Module wiring smoke test ────────────────────────────────

@_with_mock_server
def _test_C0_upstream_constructs(url):
    """UpstreamMcp instantiates against a real MorpheusProxy without crashing.

    Establishes the test file. Real Group A.1/A.2/A.3 (initialize +
    tools/list + lifespan regression guard) land in Commit 3 / Commit 4
    once the FastMCP wiring is filled in.
    """
    from proxy.proxy_server import MorpheusProxy
    from proxy.upstream import UpstreamMcp

    proxy = MorpheusProxy(url)
    upstream = UpstreamMcp(proxy)
    assert upstream.fastmcp is not None
    assert upstream.mount_path == "/mcp/"
    assert upstream.stateless is False
    assert upstream.expose_admin_tools is True


def _list_fastmcp_tool_names(upstream) -> set[str]:
    """Synchronously enumerate the FastMCP tool catalogue.

    FastMCP exposes ``list_tools`` as an async method. This helper
    runs it on a short-lived event loop so sync test bodies can use it.
    """
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        tools = loop.run_until_complete(upstream.fastmcp.list_tools())
    finally:
        loop.close()
    return {t.name for t in tools}


# ── Group A — Tool registration (in-process, no HTTP yet) ──────────────────
# A.1/A.2 over real HTTP arrive in Commit 4 once the lifespan + mount
# integration is in place. Here we verify the in-process FastMCP
# catalogue matches what the proxy reports.

@_with_mock_server
def _test_C_register_proxied_tools(url):
    """Every tool from MorpheusProxy.get_proxied_tools is registered."""
    from proxy.proxy_server import MorpheusProxy
    from proxy.upstream import UpstreamMcp

    proxy = MorpheusProxy(url)
    upstream = UpstreamMcp(proxy, expose_admin_tools=False)
    expected = {t["name"] for t in proxy.get_proxied_tools()}
    assert expected == {"send_email", "get_weather", "read_file", "delete_repo"}
    assert _list_fastmcp_tool_names(upstream) == expected


@_with_mock_server
def _test_C_register_admin_tools(url):
    """expose_admin_tools=True adds the three management tools."""
    from proxy.proxy_server import MorpheusProxy
    from proxy.upstream import UpstreamMcp

    proxy = MorpheusProxy(url)
    upstream = UpstreamMcp(proxy, expose_admin_tools=True)
    names = _list_fastmcp_tool_names(upstream)
    assert {"set_validated_intent", "get_proxy_status", "get_proxy_audit"} <= names


@_with_mock_server
def _test_C_no_admin_tools(url):
    """expose_admin_tools=False suppresses the three management tools."""
    from proxy.proxy_server import MorpheusProxy
    from proxy.upstream import UpstreamMcp

    proxy = MorpheusProxy(url)
    upstream = UpstreamMcp(proxy, expose_admin_tools=False)
    names = _list_fastmcp_tool_names(upstream)
    for admin in ("set_validated_intent", "get_proxy_status", "get_proxy_audit"):
        assert admin not in names


def register(run_fn=run):
    section("Layer 11c — MCP Proxy: Upstream streamable-HTTP MCP endpoint")

    run_fn("C0", "UpstreamMcp constructs against a real MorpheusProxy", _test_C0_upstream_constructs)
    run_fn("C.tools", "every proxied tool is registered with FastMCP", _test_C_register_proxied_tools)
    run_fn("C.admin_on", "expose_admin_tools=True adds three management tools", _test_C_register_admin_tools)
    run_fn("C.admin_off", "expose_admin_tools=False suppresses management tools", _test_C_no_admin_tools)
