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


# ── Live-server fixture (FastAPI + UpstreamMcp + downstream mock) ──────────

class _LiveProxyFixture:
    """Spins up a downstream mock + a real Morpheus HTTP proxy with
    the upstream MCP endpoint mounted, all on loopback ports.

    The fixture mirrors layer 11b's _StreamableFixture: a uvicorn
    server in a daemon thread, with a __socket-bind __ port discovery
    so parallel tests cannot collide. Lifespan threading is the same
    code path http_proxy.init_proxy() uses in production — so the
    regression guard (A.3) re-implements just the mount without the
    lifespan and asserts the documented failure mode.
    """

    def __init__(
        self,
        downstream_url: str,
        *,
        proxy_key: str = "",
        expose_admin_tools: bool = True,
        stateless: bool = False,
        mount_path: str = "/mcp/",
        wire_lifespan: bool = True,
    ) -> None:
        import contextlib
        import socket
        import threading
        import uvicorn
        from fastapi import FastAPI

        from proxy.proxy_server import MorpheusProxy
        from proxy.upstream import ProxyKeyAuthMiddleware, UpstreamMcp

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]

        self._proxy = MorpheusProxy(downstream_url)
        self._upstream = UpstreamMcp(
            self._proxy,
            expose_admin_tools=expose_admin_tools,
            stateless=stateless,
            mount_path=mount_path,
        )
        self._mount_path = mount_path

        api = FastAPI()
        upstream = self._upstream
        if wire_lifespan:
            @contextlib.asynccontextmanager
            async def _lifespan(app):
                async with upstream.lifespan_context(app):
                    yield
            api.router.lifespan_context = _lifespan
        api.mount(mount_path, ProxyKeyAuthMiddleware(upstream.asgi_app, proxy_key))
        self._api = api

        config = uvicorn.Config(
            api, host="127.0.0.1", port=self._port,
            log_level="error", lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True,
            name="morpheus-test-upstream",
        )
        self._thread.start()
        self._wait_ready()

    @property
    def port(self) -> int:
        return self._port

    @property
    def proxy(self):
        return self._proxy

    @property
    def upstream(self):
        return self._upstream

    def mcp_url(self) -> str:
        return f"http://127.0.0.1:{self._port}{self._mount_path}"

    def _wait_ready(self, timeout: float = 10.0) -> None:
        import socket
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=0.25):
                    return
            except OSError:
                _t.sleep(0.05)
        raise RuntimeError(f"Upstream proxy did not become ready on :{self._port}")

    def shutdown(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def _with_live_proxy(**fixture_kwargs):
    """Decorator: fresh _LiveProxyFixture per test, downstream mock too."""
    def decorator(fn):
        def wrapper():
            global _layer11c_port_counter
            port = _layer11c_port_counter
            _layer11c_port_counter += 1
            backend, _thread = start_mock_server(port)
            time.sleep(0.3)
            try:
                fixture = _LiveProxyFixture(
                    f"http://127.0.0.1:{port}",
                    **fixture_kwargs,
                )
                try:
                    fn(fixture)
                finally:
                    fixture.shutdown()
            finally:
                backend.shutdown()
        return wrapper
    return decorator


def _client_list_tools(url: str, headers: dict | None = None) -> set[str]:
    """Hit the live MCP endpoint with fastmcp.Client.list_tools.

    Wraps the async client in a short-lived loop so sync tests can call it.
    Headers go through StreamableHttpTransport (Client itself doesn't
    accept a headers kwarg in fastmcp 3.1.1).
    """
    import asyncio
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async def go():
        if headers:
            transport = StreamableHttpTransport(url, headers=headers)
            async with Client(transport) as c:
                tools = await c.list_tools()
        else:
            async with Client(url) as c:
                tools = await c.list_tools()
        return {t.name for t in tools}

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
    finally:
        loop.close()


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


# ── Group A — Lifespan & basic wiring ──────────────────────────────────────

@_with_live_proxy()
def _test_A1_initialize_succeeds(fixture):
    """initialize round-trip against /mcp/ returns a usable session."""
    import asyncio
    from fastmcp import Client

    async def go():
        async with Client(fixture.mcp_url()) as c:
            await c.ping()  # ping == initialize + a noop request
            return True

    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
    finally:
        loop.close()


@_with_live_proxy(expose_admin_tools=False)
def _test_A2_tools_list_matches_proxy(fixture):
    """tools/list over MCP returns exactly the proxy's discovered tools."""
    expected = {t["name"] for t in fixture.proxy.get_proxied_tools()}
    seen = _client_list_tools(fixture.mcp_url())
    assert seen == expected, (seen, expected)


@_with_live_proxy(wire_lifespan=False)
def _test_A3_lifespan_regression_guard(fixture):
    """Without lifespan threading, /mcp/ requests fail predictably.

    Regression guard for design doc §8: the documented failure mode
    is "Task group is not initialized". If a future refactor papers
    over the requirement, this test fails because the call would
    succeed and the assertion below would not trip.
    """
    import asyncio
    from fastmcp import Client

    async def go():
        async with Client(fixture.mcp_url()) as c:
            await c.ping()
            return None

    loop = asyncio.new_event_loop()
    error_message: str | None = None
    try:
        try:
            loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
        except Exception as exc:
            error_message = str(exc)
    finally:
        loop.close()

    assert error_message is not None, (
        "Without lifespan threading, /mcp/ requests must fail. "
        "If this assertion trips, the lifespan footgun no longer "
        "applies — re-read design doc §8 and consider removing the "
        "manual wiring."
    )


# ── Group B — Auth middleware ──────────────────────────────────────────────

@_with_live_proxy(proxy_key="secret-key")
def _test_B1_auth_required_no_header_401(fixture):
    """proxy_key set + no header → request rejected before reaching MCP."""
    import urllib.request
    import urllib.error

    req = urllib.request.Request(
        fixture.mcp_url(),
        method="POST",
        data=b"{}",
        headers={"Content-Type": "application/json"},
    )
    raised = False
    try:
        urllib.request.urlopen(req, timeout=5.0)
    except urllib.error.HTTPError as e:
        raised = True
        assert e.code == 401, e.code
        body = e.read()
        assert b"unauthorized" in body
    assert raised


@_with_live_proxy(proxy_key="secret-key", expose_admin_tools=False)
def _test_B2_auth_x_proxy_key_passes(fixture):
    """proxy_key set + correct X-Proxy-Key → reaches the sub-app."""
    seen = _client_list_tools(
        fixture.mcp_url(),
        headers={"X-Proxy-Key": "secret-key"},
    )
    assert seen == {"send_email", "get_weather", "read_file", "delete_repo"}


@_with_live_proxy(proxy_key="secret-key", expose_admin_tools=False)
def _test_B3_auth_bearer_passes(fixture):
    """proxy_key set + correct Authorization: Bearer → reaches the sub-app."""
    seen = _client_list_tools(
        fixture.mcp_url(),
        headers={"Authorization": "Bearer secret-key"},
    )
    assert seen == {"send_email", "get_weather", "read_file", "delete_repo"}


@_with_live_proxy(proxy_key="", expose_admin_tools=False)
def _test_B4_dev_mode_open(fixture):
    """proxy_key empty → all requests pass (dev-mode parity with REST)."""
    seen = _client_list_tools(fixture.mcp_url())
    assert seen == {"send_email", "get_weather", "read_file", "delete_repo"}


def _test_B5_rest_auth_unchanged():
    """Sanity check: _check_auth is still the gate on REST endpoints.

    We don't spin up a server — the helper itself is what we verify.
    Importing http_proxy bootstraps the module-level FastAPI app and the
    _check_auth function; we assert the function still exists and still
    enforces the key when set.
    """
    from fastapi import HTTPException
    from proxy import http_proxy

    class _MockReq:
        def __init__(self, key=None, bearer=None):
            self.headers = {}
            if key is not None:
                self.headers["X-Proxy-Key"] = key
            if bearer is not None:
                self.headers["Authorization"] = f"Bearer {bearer}"

        # FastAPI's Request exposes .headers as a dict-like; .get is enough.
        def __getattr__(self, name):
            raise AttributeError(name)

    # Snapshot and restore — we don't want to leak module state.
    saved = http_proxy.PROXY_API_KEY
    try:
        http_proxy.PROXY_API_KEY = "rest-key"
        # Wrong key → raises
        raised = False
        try:
            http_proxy._check_auth(_MockReq(key="wrong"))
        except HTTPException as e:
            raised = True
            assert e.status_code == 401
        assert raised, "_check_auth must reject wrong keys"
        # Right key via X-Proxy-Key → passes
        http_proxy._check_auth(_MockReq(key="rest-key"))
        # Right key via Bearer → passes
        http_proxy._check_auth(_MockReq(bearer="rest-key"))
    finally:
        http_proxy.PROXY_API_KEY = saved


def register(run_fn=run):
    section("Layer 11c — MCP Proxy: Upstream streamable-HTTP MCP endpoint")

    run_fn("C0", "UpstreamMcp constructs against a real MorpheusProxy", _test_C0_upstream_constructs)
    run_fn("C.tools", "every proxied tool is registered with FastMCP", _test_C_register_proxied_tools)
    run_fn("C.admin_on", "expose_admin_tools=True adds three management tools", _test_C_register_admin_tools)
    run_fn("C.admin_off", "expose_admin_tools=False suppresses management tools", _test_C_no_admin_tools)
    run_fn("A.1", "initialize against /mcp/ succeeds", _test_A1_initialize_succeeds)
    run_fn("A.2", "tools/list over MCP matches MorpheusProxy.get_proxied_tools()", _test_A2_tools_list_matches_proxy)
    run_fn("A.3", "lifespan-regression guard: missing wiring fails predictably", _test_A3_lifespan_regression_guard)
    run_fn("B.1", "proxy_key set + no header → 401", _test_B1_auth_required_no_header_401)
    run_fn("B.2", "proxy_key set + X-Proxy-Key → passes", _test_B2_auth_x_proxy_key_passes)
    run_fn("B.3", "proxy_key set + Authorization: Bearer → passes", _test_B3_auth_bearer_passes)
    run_fn("B.4", "proxy_key empty → dev mode, all requests pass", _test_B4_dev_mode_open)
    run_fn("B.5", "REST _check_auth remains the gate on /proxy/* endpoints", _test_B5_rest_auth_unchanged)
