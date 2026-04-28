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


def register(run_fn=run):
    section("Layer 11c — MCP Proxy: Upstream streamable-HTTP MCP endpoint")

    run_fn("C0", "UpstreamMcp constructs against a real MorpheusProxy", _test_C0_upstream_constructs)
