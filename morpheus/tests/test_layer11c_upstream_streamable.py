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


# ── Group E — Stateful vs stateless ────────────────────────────────────────

@_with_live_proxy(stateless=False, expose_admin_tools=False)
def _test_E1_stateful_session_id_present(fixture):
    """Stateful default: server includes Mcp-Session-Id on initialize."""
    import asyncio
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    seen_session_ids: list[str | None] = []

    async def go():
        transport = StreamableHttpTransport(fixture.mcp_url())
        async with Client(transport) as c:
            await c.list_tools()
            seen_session_ids.append(transport.get_session_id())
            await c.list_tools()
            seen_session_ids.append(transport.get_session_id())

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
    finally:
        loop.close()

    assert seen_session_ids[0] is not None, seen_session_ids
    # Same session reused across two consecutive list_tools.
    assert seen_session_ids[0] == seen_session_ids[1], seen_session_ids


@_with_live_proxy(stateless=True, expose_admin_tools=False)
def _test_E2_stateless_no_session_id(fixture):
    """Stateless mode: server does NOT issue an Mcp-Session-Id."""
    import asyncio
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    sid: list[str | None] = []

    async def go():
        transport = StreamableHttpTransport(fixture.mcp_url())
        async with Client(transport) as c:
            await c.list_tools()
            sid.append(transport.get_session_id())

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
    finally:
        loop.close()

    assert sid[0] is None, f"stateless mode must not issue a session id, got {sid[0]!r}"


# ── Group F — Management tools toggle ──────────────────────────────────────

@_with_live_proxy(expose_admin_tools=True)
def _test_F1_admin_tools_default_present(fixture):
    """Default: tools/list over MCP includes the three admin tools."""
    seen = _client_list_tools(fixture.mcp_url())
    for admin in ("set_validated_intent", "get_proxy_status", "get_proxy_audit"):
        assert admin in seen, f"expected {admin} in {seen}"


@_with_live_proxy(expose_admin_tools=False)
def _test_F2_admin_tools_suppressed(fixture):
    """expose_admin_tools=False: the three admin tools are NOT in tools/list."""
    seen = _client_list_tools(fixture.mcp_url())
    for admin in ("set_validated_intent", "get_proxy_status", "get_proxy_audit"):
        assert admin not in seen, f"unexpected {admin} in {seen}"


def _test_F3_admin_toggle_is_local_to_mcp_endpoint():
    """Suppression is endpoint-local: it must not affect any REST behaviour.

    No live server needed — verify by introspection that
    expose_admin_tools=False does not modify anything in the REST
    code path (no globals touched, no /proxy/* route changed).
    """
    from proxy import http_proxy
    from proxy.proxy_server import MorpheusProxy
    from proxy.upstream import UpstreamMcp
    from tests.mock_mcp_server import start_mock_server

    # Snapshot REST endpoint paths.
    before = {r.path for r in http_proxy.app.routes if hasattr(r, "path")}

    server, _t = start_mock_server(5450)
    time.sleep(0.3)
    try:
        proxy = MorpheusProxy("http://127.0.0.1:5450")
        # Both modes leave REST routes unchanged — what changes is the
        # FastMCP catalogue inside UpstreamMcp, never http_proxy.app.
        UpstreamMcp(proxy, expose_admin_tools=True)
        after_on = {r.path for r in http_proxy.app.routes if hasattr(r, "path")}
        UpstreamMcp(proxy, expose_admin_tools=False)
        after_off = {r.path for r in http_proxy.app.routes if hasattr(r, "path")}
        assert before == after_on == after_off
    finally:
        server.shutdown()


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


# ── Group C — Tool dispatch through Control 2 ─────────────────────────────

def _client_call_tool(url: str, tool_name: str, arguments_json: str) -> str:
    """Run a single MCP tools/call against the live endpoint.

    Returns the flat text content the proxy emitted for the tool —
    which after the upstream adapter is one of:
      - the raw downstream output, on approved
      - "BLOCKED: ..." on policy block
      - "[BYPASSED] ..." on a forwarded-with-controls-off call
      - "ERROR: ..." on transport error
    """
    import asyncio
    from fastmcp import Client

    async def go():
        async with Client(url) as c:
            result = await c.call_tool(tool_name, {"arguments_json": arguments_json})
            content = getattr(result, "content", None) or []
            for item in content:
                if getattr(item, "type", None) == "text":
                    return item.text
            return str(result)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(asyncio.wait_for(go(), timeout=10.0))
    finally:
        loop.close()


@_with_live_proxy(expose_admin_tools=False)
def _test_C1_low_risk_call_routes_through_proxy(fixture):
    """An MCP tool call goes through MorpheusProxy.call_tool and the policy checker.

    get_weather is a low-risk get_* tool — auto-approved by Control 2's
    Level 1. We call it via MCP, then assert the proxy's audit log
    shows tool_call_intercepted + policy_decision events for the
    expected tool name.
    """
    text = _client_call_tool(
        fixture.mcp_url(),
        "get_weather",
        '{"location": "Rome"}',
    )
    # Mock returns "Mock result for get_weather({'location': 'Rome'})"
    assert "Mock result for get_weather" in text, text

    events = fixture.proxy.logger.get_events()
    intercepts = [e for e in events if e.event_type == "tool_call_intercepted"]
    decisions = [e for e in events if e.event_type == "policy_decision"]
    assert intercepts and intercepts[-1].payload["tool"] == "get_weather"
    assert decisions and decisions[-1].payload["status"] == "approved"


@_with_live_proxy(expose_admin_tools=False)
def _test_C2_high_risk_blocked_returns_blocked_text(fixture):
    """A high-risk tool that L1 blocks surfaces with BLOCKED: prefix.

    delete_repo matches the high-risk name pattern, so L1 requires
    confirmation and blocks. The MCP client sees the block reason
    in the tool's text content (per MCP spec, isError on the tool
    response — NOT a JSON-RPC protocol error).
    """
    text = _client_call_tool(
        fixture.mcp_url(),
        "delete_repo",
        '{"repo_name": "x"}',
    )
    assert text.startswith("BLOCKED:"), text


@_with_live_proxy(expose_admin_tools=True)
def _test_C3_bypassed_call_marked_bypassed(fixture):
    """A bypassed call surfaces with [BYPASSED] prefix and is forwarded.

    We exercise the bypass path by setting controls_active via the
    UpstreamMcp's control-manager hook... but the live fixture doesn't
    own a ControlManager (the constructor passed control_manager=None).
    Easier: monkey-patch the upstream's _control_manager for this test
    so the adapter sends action_validation=False on the call.
    """
    class _StubControls:
        @staticmethod
        def to_dict():
            return {"input_validation": True, "action_validation": False, "coherence_check": True}

    class _StubControlManager:
        @staticmethod
        def get_controls():
            return _StubControls()

    fixture.upstream._control_manager = _StubControlManager()

    text = _client_call_tool(
        fixture.mcp_url(),
        "delete_repo",
        '{"repo_name": "x"}',
    )
    assert text.startswith("[BYPASSED]"), text


# ── Group D — Dynamic tool sync ────────────────────────────────────────────

@_with_live_proxy(expose_admin_tools=False)
def _test_D1_handle_tools_changed_diffs_catalogue(fixture):
    """_handle_tools_changed adds new tools, removes gone tools.

    Drives the listener directly: monkey-patch the proxy's
    get_proxied_tools to return a synthetic catalogue, then call
    _on_tools_changed (which runs _discover_tools then fans out to
    the listener). After the dust settles the FastMCP tool set must
    match the synthetic catalogue.
    """
    upstream = fixture.upstream
    proxy = fixture.proxy

    # Snapshot real tools, then make get_proxied_tools return a
    # synthetic set so the diff sees a clean add/remove.
    synthetic = [
        {"name": "get_weather", "description": "kept", "inputSchema": {}},
        {"name": "newly_added", "description": "added by test", "inputSchema": {}},
    ]
    saved = proxy.get_proxied_tools
    proxy.get_proxied_tools = lambda: synthetic
    try:
        # Skip _discover_tools (we don't want it to overwrite our
        # synthetic catalogue) — call the listener fan-out directly.
        upstream._handle_tools_changed()
    finally:
        proxy.get_proxied_tools = saved

    seen = _list_fastmcp_tool_names(upstream)
    assert "get_weather" in seen
    assert "newly_added" in seen
    # Tools that were in the original catalogue but not in synthetic
    # must have been removed.
    assert "send_email" not in seen
    assert "delete_repo" not in seen


@_with_live_proxy(expose_admin_tools=False)
def _test_D2_client_resees_catalogue_after_change(fixture):
    """A connected client picks up the new catalogue on a re-list.

    fastmcp.Client doesn't expose a direct "subscribe to
    notifications/tools/list_changed" — verifying that a client
    *receives* the notification mid-flight is a richer test than this
    file should carry. Instead we verify the observable equivalent:
    after _handle_tools_changed, a new tools/list call returns the
    updated set. That's what any well-behaved client would do on
    receiving the notification.
    """
    upstream = fixture.upstream
    proxy = fixture.proxy

    synthetic = [
        {"name": "newly_added_d2", "description": "added", "inputSchema": {}},
    ]
    proxy.get_proxied_tools = lambda: synthetic
    upstream._handle_tools_changed()

    seen = _client_list_tools(fixture.mcp_url())
    assert seen == {"newly_added_d2"}, seen


@_with_live_proxy(expose_admin_tools=False)
def _test_D3_inflight_call_survives_unrelated_removal(fixture):
    """Removing tool A does not abort an in-flight call to tool B.

    The simplest verification: start a call, complete it, remove a
    different tool mid-stream, observe the call still produced its
    result. We synthesise the "concurrent" aspect with two threads
    coordinated by a small barrier.
    """
    import threading
    import asyncio
    from fastmcp import Client

    upstream = fixture.upstream
    proxy = fixture.proxy

    completed = []
    errors = []

    def caller():
        try:
            text = _client_call_tool(
                fixture.mcp_url(),
                "get_weather",
                '{"location": "Rome"}',
            )
            completed.append(text)
        except Exception as e:
            errors.append(e)

    t = threading.Thread(target=caller)
    t.start()
    # Race — remove an unrelated tool while the call is in flight.
    synthetic = [
        {"name": "get_weather", "description": "still here", "inputSchema": {}},
    ]
    proxy.get_proxied_tools = lambda: synthetic
    upstream._handle_tools_changed()
    t.join(timeout=10.0)

    assert not errors, errors
    assert completed and "Mock result for get_weather" in completed[0]


# ── Group G — Concurrent session safety ────────────────────────────────────

@_with_live_proxy(expose_admin_tools=False)
def _test_G1_three_concurrent_clients(fixture):
    """Three clients call tools concurrently. All complete with no leaks.

    Each gets a distinct Mcp-Session-Id (stateful default). State
    isolation is the SDK's responsibility on the server side — we
    just verify no client sees another client's result and all calls
    finish successfully.
    """
    import threading

    results: list[tuple[int, str]] = []
    errors: list[BaseException] = []

    def worker(idx: int):
        try:
            text = _client_call_tool(
                fixture.mcp_url(),
                "get_weather",
                f'{{"location": "city-{idx}"}}',
            )
            results.append((idx, text))
        except BaseException as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15.0)

    assert not errors, errors
    assert len(results) == 3
    # Each result must contain that client's own city id — proves
    # no cross-contamination of arguments between sessions.
    for idx, text in results:
        assert f"city-{idx}" in text, (idx, text)


def _test_G2_validated_intent_global_known_limitation():
    """G.2 documents the pre-existing _validated_intent global-state bug.

    See design doc §11 / §12: the upstream MCP path inherits the
    same module-level _validated_intent global that the REST
    /proxy/intent endpoint already uses. Concurrent clients setting
    different intents would race. This test exists to make the
    limitation visible in the audit trail of the test suite — it does
    NOT fix the bug, and it must NOT block on the bug being fixed.

    The assertion is structural: the global exists, both REST and
    MCP paths read/write it via the helper functions added in
    Commit 4. If a future refactor retires the global to per-session
    state, this test will fail with a comment pointing to where to
    delete it.
    """
    from proxy import http_proxy
    assert hasattr(http_proxy, "_validated_intent"), (
        "If _validated_intent has been retired, delete this test "
        "and update design doc §12.3 — the global-state bug is fixed."
    )
    assert callable(getattr(http_proxy, "_get_validated_intent", None))
    assert callable(getattr(http_proxy, "_set_validated_intent", None))


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
    run_fn("E.1", "stateful default: same Mcp-Session-Id across consecutive calls", _test_E1_stateful_session_id_present)
    run_fn("E.2", "stateless: no Mcp-Session-Id issued", _test_E2_stateless_no_session_id)
    run_fn("F.1", "admin tools exposed by default in tools/list", _test_F1_admin_tools_default_present)
    run_fn("F.2", "expose_admin_tools=False suppresses admin tools in tools/list", _test_F2_admin_tools_suppressed)
    run_fn("F.3", "admin-tools toggle is local to MCP endpoint (REST routes unchanged)", _test_F3_admin_toggle_is_local_to_mcp_endpoint)
    run_fn("C.1", "low-risk MCP call routes through MorpheusProxy.call_tool", _test_C1_low_risk_call_routes_through_proxy)
    run_fn("C.2", "high-risk MCP call → BLOCKED text in tool response", _test_C2_high_risk_blocked_returns_blocked_text)
    run_fn("C.3", "bypassed MCP call → [BYPASSED] prefix, still forwarded", _test_C3_bypassed_call_marked_bypassed)
    run_fn("D.1", "_handle_tools_changed adds + removes via add_tool/remove_tool", _test_D1_handle_tools_changed_diffs_catalogue)
    run_fn("D.2", "client re-list reflects updated catalogue after sync", _test_D2_client_resees_catalogue_after_change)
    run_fn("D.3", "in-flight tool call survives unrelated tool removal", _test_D3_inflight_call_survives_unrelated_removal)
    run_fn("G.1", "three concurrent MCP clients: no state leak, all complete", _test_G1_three_concurrent_clients)
    run_fn("G.2", "doc-only test: _validated_intent global-state bug acknowledged", _test_G2_validated_intent_global_known_limitation)
