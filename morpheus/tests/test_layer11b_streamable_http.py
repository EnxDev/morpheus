"""Layer 11b — MCP Proxy: Streamable-HTTP Transport

Covers the DownstreamTransport abstraction, transport selection, the
streamable-HTTP implementation, session lifecycle, and the session-loss
error-code guard. Follows Layer 11's harness conventions: sync ``fn``
bodies, hand-rolled fixtures, no pytest.

See ``docs/streamable-http-transport.md`` and ``docs/sdk-notes-phase2.md``
for the design rationale these tests protect.
"""

import os
import time

from tests.harness import run, section
from tests.mock_mcp_server import start_mock_server


# ── Group A — Transport selection (no network) ─────────────────────────────

def _clear_transport_env():
    """Remove the env var so each test starts from a clean slate."""
    os.environ.pop("MORPHEUS_DOWNSTREAM_TRANSPORT", None)


def _test_A1_default_is_plain_jsonrpc():
    """No --transport flag and no env var → PlainJsonRpcTransport."""
    from proxy.http_proxy import _build_transport
    from proxy.transport import PlainJsonRpcTransport, TRANSPORT_PLAIN_JSONRPC

    _clear_transport_env()
    t = _build_transport("http://127.0.0.1:65535", TRANSPORT_PLAIN_JSONRPC)
    try:
        assert isinstance(t, PlainJsonRpcTransport), type(t).__name__
        assert t.name == "plain_jsonrpc"
    finally:
        t.close()


def _test_A2_flag_plain_jsonrpc():
    from proxy.http_proxy import _build_transport
    from proxy.transport import PlainJsonRpcTransport

    t = _build_transport("http://127.0.0.1:65535", "plain_jsonrpc")
    try:
        assert isinstance(t, PlainJsonRpcTransport)
    finally:
        t.close()


def _test_A3_flag_streamable_http():
    from proxy.http_proxy import _build_transport
    from proxy.transport import StreamableHttpTransport

    t = _build_transport("http://127.0.0.1:65535", "streamable_http")
    try:
        assert isinstance(t, StreamableHttpTransport)
        assert t.name == "streamable_http"
    finally:
        t.close()


def _test_A4_env_streamable_http():
    """MORPHEUS_DOWNSTREAM_TRANSPORT without a flag routes to streamable_http.

    The argparse default pulls from the env; this exercises that wiring by
    calling ``main()``-equivalent logic through _build_transport using the
    env-derived value.
    """
    import argparse
    from proxy.transport import (
        StreamableHttpTransport,
        TRANSPORT_PLAIN_JSONRPC,
        VALID_TRANSPORTS,
    )
    from proxy.http_proxy import _build_transport

    os.environ["MORPHEUS_DOWNSTREAM_TRANSPORT"] = "streamable_http"
    try:
        # Rebuild the same argparse spec http_proxy.main() uses, with no
        # --transport on the argv so the env default wins.
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            default=os.environ.get("MORPHEUS_DOWNSTREAM_TRANSPORT", TRANSPORT_PLAIN_JSONRPC),
            choices=sorted(VALID_TRANSPORTS),
        )
        args = parser.parse_args([])
        assert args.transport == "streamable_http"
        t = _build_transport("http://127.0.0.1:65535", args.transport)
        try:
            assert isinstance(t, StreamableHttpTransport)
        finally:
            t.close()
    finally:
        _clear_transport_env()


def _test_A5_flag_overrides_env():
    import argparse
    from proxy.transport import (
        PlainJsonRpcTransport,
        TRANSPORT_PLAIN_JSONRPC,
        VALID_TRANSPORTS,
    )
    from proxy.http_proxy import _build_transport

    os.environ["MORPHEUS_DOWNSTREAM_TRANSPORT"] = "streamable_http"
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "--transport",
            default=os.environ.get("MORPHEUS_DOWNSTREAM_TRANSPORT", TRANSPORT_PLAIN_JSONRPC),
            choices=sorted(VALID_TRANSPORTS),
        )
        args = parser.parse_args(["--transport", "plain_jsonrpc"])
        assert args.transport == "plain_jsonrpc"
        t = _build_transport("http://127.0.0.1:65535", args.transport)
        try:
            assert isinstance(t, PlainJsonRpcTransport)
        finally:
            t.close()
    finally:
        _clear_transport_env()


def _test_A6_bad_flag_rejected():
    """argparse's ``choices=`` rejects unknown flag values at parse time."""
    import argparse
    from proxy.transport import TRANSPORT_PLAIN_JSONRPC, VALID_TRANSPORTS

    _clear_transport_env()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--transport",
        default=TRANSPORT_PLAIN_JSONRPC,
        choices=sorted(VALID_TRANSPORTS),
    )
    raised = False
    try:
        # argparse calls sys.exit(2) on invalid choice; capture via SystemExit.
        parser.parse_args(["--transport", "bogus"])
    except SystemExit as exc:
        raised = True
        assert exc.code == 2, f"expected exit code 2, got {exc.code}"
    assert raised, "argparse should have rejected 'bogus'"


def _test_A7_bad_env_rejected():
    """Unknown value via env triggers _build_transport's ValueError.

    argparse.choices= guards the CLI path; the env path goes through
    _build_transport directly and must re-validate.
    """
    from proxy.http_proxy import _build_transport

    raised = False
    try:
        _build_transport("http://127.0.0.1:65535", "bogus")
    except ValueError as exc:
        raised = True
        msg = str(exc)
        assert "bogus" in msg
        assert "plain_jsonrpc" in msg
        assert "streamable_http" in msg
    assert raised, "_build_transport should reject 'bogus'"


# ── Shared streamable-HTTP mock server fixture ─────────────────────────────

# Single module-level FastMCP instance + uvicorn thread, reused across tests.
# Starting FastMCP per-test would add ~500ms × N; the design note in the
# Phase 1 test plan explicitly called this out as a reason to share.
#
# Chose FastMCP (already in requirements.txt, same version that produces real
# downstreams) over a hand-rolled minimum spec implementation — FastMCP
# startup in a background thread is <400ms locally, well within the 500ms
# budget, and using the real implementation catches spec-interpretation
# mismatches that a hand-rolled mock would hide.

_streamable_fixture_lock = __import__("threading").Lock()
_streamable_fixture = None  # populated on first use


class _StreamableFixture:
    """Module-level FastMCP-backed streamable-HTTP server.

    Holds a uvicorn server running a FastMCP app on a loopback port. The
    instance exposes :meth:`url` for clients and :meth:`reset_tool_calls`
    for per-test state isolation.
    """

    def __init__(self):
        import socket
        import threading
        import uvicorn
        from fastmcp import FastMCP

        # Pick a free port by binding :0 and reading it back.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]

        mcp = FastMCP("morpheus-test-streamable")

        # Tool-call counter, for "session reuse" verification in later tests.
        self.call_counts: dict[str, int] = {}

        @mcp.tool
        def ping() -> str:
            """Return 'pong'."""
            self.call_counts["ping"] = self.call_counts.get("ping", 0) + 1
            return "pong"

        @mcp.tool
        def echo(message: str) -> str:
            """Return the given message verbatim."""
            self.call_counts["echo"] = self.call_counts.get("echo", 0) + 1
            return message

        self._mcp = mcp

        app = mcp.http_app(transport="streamable-http", path="/mcp")
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self._port,
            log_level="error", lifespan="on",
        )
        self._server = uvicorn.Server(config)

        self._thread = threading.Thread(
            target=self._server.run, daemon=True,
            name="morpheus-test-fastmcp",
        )
        self._thread.start()

        # Wait until the server is actually accepting connections.
        self._wait_ready()

    @property
    def port(self) -> int:
        return self._port

    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/mcp"

    def reset_call_counts(self) -> None:
        self.call_counts.clear()

    def _wait_ready(self, timeout: float = 10.0) -> None:
        import socket
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=0.25):
                    return
            except OSError:
                _time.sleep(0.05)
        raise RuntimeError(f"FastMCP test server did not become ready on port {self._port}")

    def shutdown(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def _streamable_mock():
    """Lazy singleton — one FastMCP per test run, shared across C/D tests."""
    global _streamable_fixture
    with _streamable_fixture_lock:
        if _streamable_fixture is None:
            _streamable_fixture = _StreamableFixture()
    return _streamable_fixture


# ── Group B — PlainJsonRpcTransport regression ─────────────────────────────

# Start port well above Layer 11's counter (5020+N) so we can never collide.
_plain_port_counter = 5200


def _with_plain_mock(fn):
    def wrapper():
        global _plain_port_counter
        port = _plain_port_counter
        _plain_port_counter += 1
        server, _thread = start_mock_server(port)
        time.sleep(0.3)
        try:
            fn(f"http://127.0.0.1:{port}")
        finally:
            server.shutdown()
    return wrapper


@_with_plain_mock
def _test_B1_plain_jsonrpc_regression(url):
    """End-to-end: MorpheusProxy over the explicit PlainJsonRpcTransport
    against the existing mock produces the same results Layer 11 asserts.

    This duplicates some of Layer 11's coverage on purpose — Layer 11
    exercises the implicit default path (URL passed directly), this one
    exercises the explicit path where the caller constructs the transport.
    Both must behave identically.
    """
    from proxy.proxy_server import MorpheusProxy
    from proxy.transport import PlainJsonRpcTransport

    transport = PlainJsonRpcTransport(url)
    try:
        proxy = MorpheusProxy(real_server_or_transport=transport)

        # Discovery: matches Layer 11 test 11.5
        tools = proxy.get_proxied_tools()
        names = {t["name"] for t in tools}
        assert names == {"send_email", "get_weather", "read_file", "delete_repo"}

        # Forwarded call: matches Layer 11 test 11.6
        r = proxy.call_tool("get_weather", {"location": "Rome"})
        assert r["status"] == "approved"
        assert "result" in r

        # Blocked call: matches Layer 11 test 11.7
        r = proxy.call_tool("delete_repo", {"repo_name": "test"})
        assert r["status"] == "blocked"
        assert r["result"]["isError"] is True

        # Audit events include the transport field (new in Phase 2)
        events = proxy.logger.get_events()
        forwarded = [e for e in events if e.event_type == "tool_call_forwarded"]
        assert forwarded, "expected at least one tool_call_forwarded event"
        assert all(e.payload.get("transport") == "plain_jsonrpc" for e in forwarded), (
            "all forwarded events should carry transport=plain_jsonrpc"
        )
    finally:
        transport.close()


# ── Minimal streamable-HTTP mock for session-loss tests (D.2–D.4) ──────────
#
# FastMCP cannot easily be made to drop a session on command. For D.2/D.3/D.4
# we use a purpose-built HTTP handler that speaks just enough of the MCP
# streamable-http transport to satisfy ``mcp.client.streamable_http``:
#
#  1. POST initialize (no session header) → 200 JSON with InitializeResult
#     and an ``mcp-session-id`` response header.
#  2. POST notifications/initialized → 202 Accepted (no body).
#  3. POST tools/list and tools/call → 200 JSON with the appropriate result.
#  4. DELETE → 200, records the termination for D.4.
#  5. A ``kill_next`` toggle makes the handler answer 404 once, which the
#     SDK turns into a ``McpError(code=32600)`` per streamable_http.py:350-356.
#
# This intentionally does NOT implement: SSE streaming, resumption tokens,
# GET streams, 2025-11-25 features beyond the subset the transport under
# test exercises. If the SDK ever starts requiring more, this mock will
# fail loudly, which is better than silently drifting.

from http.server import BaseHTTPRequestHandler, HTTPServer
import json as _json
import threading as _threading


class _SessionMockHandler(BaseHTTPRequestHandler):
    # Shared state is stashed on the server instance by
    # ``_StreamableSessionMock.start``.

    def do_POST(self):  # noqa: N802 — stdlib naming
        state = self.server.state  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = _json.loads(raw) if raw else {}
        except Exception:
            body = {}

        session_header = self.headers.get("mcp-session-id")
        state.last_seen_session_id = session_header

        # One-shot session-drop: return 404 and clear the toggle.
        if state.kill_next:
            state.kill_next = False
            state.kill_count += 1
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"session terminated"}')
            return

        method = body.get("method", "")
        req_id = body.get("id")

        # Notifications (no id) — return 202 Accepted with no body.
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return

        if method == "initialize":
            # Hand out a fresh session id — or reuse a sticky one if the
            # test has pinned one (makes D.1 easy to observe deterministically).
            state.session_seq += 1
            sid = f"sess-{state.session_seq}"
            state.session_ids_handed_out.append(sid)
            result = {
                "protocolVersion": "2025-06-18",
                "serverInfo": {"name": "morpheus-mock", "version": "0"},
                "capabilities": {"tools": {}},
            }
            payload = _json.dumps({
                "jsonrpc": "2.0", "id": req_id, "result": result,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", sid)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if method == "tools/list":
            state.list_tools_calls += 1
            result = {
                "tools": [{
                    "name": "noop",
                    "description": "Does nothing.",
                    "inputSchema": {"type": "object", "properties": {}},
                }],
            }
            self._send_json_result(req_id, result)
            return

        if method == "tools/call":
            state.call_tool_calls += 1
            params = body.get("params", {})
            name = params.get("name", "")
            result = {
                "content": [{"type": "text", "text": f"ok:{name}"}],
                "isError": False,
            }
            self._send_json_result(req_id, result)
            return

        # Unknown method — return JSON-RPC method-not-found.
        self._send_json_error(req_id, -32601, f"Unknown method: {method}")

    def do_DELETE(self):  # noqa: N802
        state = self.server.state  # type: ignore[attr-defined]
        state.delete_calls += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        return  # stay silent during tests

    def _send_json_result(self, req_id, result):
        payload = _json.dumps({
            "jsonrpc": "2.0", "id": req_id, "result": result,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json_error(self, req_id, code, message):
        payload = _json.dumps({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": code, "message": message},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class _StreamableSessionMock:
    """Background HTTP server exposing the minimal streamable-HTTP surface.

    Attributes monitored by tests:
    - session_ids_handed_out: every id issued by ``initialize``
    - list_tools_calls / call_tool_calls / delete_calls: counters
    - kill_next: when True, the next POST returns 404 (one-shot)
    - kill_count: total number of 404 drops served
    """

    def __init__(self) -> None:
        import socket as _socket
        with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self._port = s.getsockname()[1]
        self._server = HTTPServer(("127.0.0.1", self._port), _SessionMockHandler)

        # State accessed both from the handler thread (HTTP) and the test
        # thread (assertions). Single attribute access is GIL-atomic;
        # counters may race under load but tests always await the call
        # return before reading, which provides a happens-before.
        self.session_seq = 0
        self.session_ids_handed_out: list[str] = []
        self.last_seen_session_id: str | None = None
        self.list_tools_calls = 0
        self.call_tool_calls = 0
        self.delete_calls = 0
        self.kill_next = False
        self.kill_count = 0

        self._server.state = self  # type: ignore[attr-defined]
        self._thread = _threading.Thread(
            target=self._server.serve_forever, daemon=True,
            name="morpheus-test-session-mock",
        )
        self._thread.start()

    @property
    def port(self) -> int:
        return self._port

    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}/"

    def shutdown(self) -> None:
        self._server.shutdown()
        self._thread.join(timeout=5.0)


def _with_session_mock(fn):
    """Fixture: fresh _StreamableSessionMock per test, shut down on exit."""
    def wrapper():
        mock = _StreamableSessionMock()
        try:
            fn(mock)
        finally:
            mock.shutdown()
    return wrapper


# ── Group C — StreamableHttpTransport against a real FastMCP ──────────────

def _test_C1_streamable_list_tools():
    from proxy.transport import StreamableHttpTransport

    mock = _streamable_mock()
    mock.reset_call_counts()
    t = StreamableHttpTransport(mock.url())
    try:
        tools = t.list_tools()
        names = {x["name"] for x in tools}
        assert names == {"ping", "echo"}, f"unexpected tool set: {names}"
        # Every tool dict must at minimum carry name+description+inputSchema.
        for tool in tools:
            assert tool["name"]
            assert "inputSchema" in tool
    finally:
        t.close()


def _test_C2_streamable_call_tool():
    from proxy.transport import StreamableHttpTransport

    mock = _streamable_mock()
    mock.reset_call_counts()
    t = StreamableHttpTransport(mock.url())
    try:
        result = t.call_tool("echo", {"message": "hello"})
        # MCP CallToolResult wire shape: {"content": [...], "isError": bool, ...}
        assert isinstance(result, dict), type(result).__name__
        assert result.get("isError") is False, result
        content = result.get("content", [])
        assert content and content[0].get("text") == "hello", content
        assert mock.call_counts.get("echo") == 1
    finally:
        t.close()


def _test_C3_audit_includes_streamable_transport():
    """End-to-end through MorpheusProxy: the forwarded call's audit event
    carries ``transport="streamable_http"``.
    """
    from proxy.proxy_server import MorpheusProxy
    from proxy.transport import StreamableHttpTransport

    mock = _streamable_mock()
    mock.reset_call_counts()
    transport = StreamableHttpTransport(mock.url())
    try:
        proxy = MorpheusProxy(real_server_or_transport=transport)
        # ``ping`` matches the low-risk auto-approve name pattern
        # (get_/list_/... doesn't, but there's no rule blocking it either).
        # Actually: "ping" doesn't match any name pattern, so it goes to
        # risk="unknown" which requires confirmation → blocked by L1.
        # Use "echo" same story. Bypass Control 2 instead so the call
        # is forwarded and audit-logged as forwarded.
        r = proxy.call_tool(
            "echo",
            {"message": "world"},
            controls_active={
                "input_validation": True,
                "action_validation": False,
                "coherence_check": False,
            },
        )
        assert r["status"] == "bypassed", r
        events = proxy.logger.get_events()
        forwarded = [e for e in events if e.event_type == "tool_call_forwarded"]
        assert forwarded, "expected a tool_call_forwarded event"
        assert all(
            e.payload.get("transport") == "streamable_http" for e in forwarded
        ), [e.payload for e in forwarded]
    finally:
        transport.close()


# ── Group D — Session lifecycle ─────────────────────────────────────────────

@_with_session_mock
def _test_D1_session_is_reused(mock):
    """Two consecutive calls must reuse the same session ID.

    Proof: the mock only issues one session id across both calls, which
    only happens if the SDK kept the session alive between them (i.e. no
    hidden per-call initialize).
    """
    from proxy.transport import StreamableHttpTransport

    t = StreamableHttpTransport(mock.url())
    try:
        t.list_tools()
        t.call_tool("noop", {})
        assert len(mock.session_ids_handed_out) == 1, (
            f"expected one session across both calls, got "
            f"{mock.session_ids_handed_out}"
        )
        # And the mock saw that exact session id on the final request.
        assert mock.last_seen_session_id == mock.session_ids_handed_out[0]
    finally:
        t.close()


@_with_session_mock
def _test_D2_session_loss_triggers_reinit(mock):
    """One-shot session-drop → transport re-inits and the call succeeds.

    Flow: list_tools OK; enable kill_next; call_tool should observe 404 →
    McpError(32600), the transport closes + re-opens the session, then
    retries call_tool successfully. The mock should have issued two
    session ids total (original + re-init) and the proxy's audit log
    should carry one ``downstream_session_reinitialized`` event.
    """
    from proxy.proxy_server import MorpheusProxy
    from proxy.transport import StreamableHttpTransport

    transport = StreamableHttpTransport(mock.url())
    try:
        proxy = MorpheusProxy(real_server_or_transport=transport)

        # Arm the mock to drop the NEXT request.
        mock.kill_next = True

        r = proxy.call_tool(
            "noop",
            {},
            controls_active={
                "input_validation": True,
                "action_validation": False,
                "coherence_check": False,
            },
        )
        assert r["status"] == "bypassed", r
        # One kill consumed, one re-init observed
        assert mock.kill_count == 1, mock.kill_count
        assert len(mock.session_ids_handed_out) == 2, (
            f"expected 2 sessions (original + re-init), got "
            f"{mock.session_ids_handed_out}"
        )

        events = proxy.logger.get_events()
        reinits = [
            e for e in events if e.event_type == "downstream_session_reinitialized"
        ]
        assert len(reinits) == 1, (
            f"expected exactly one reinit audit event, got {len(reinits)}: "
            f"{[e.event_type for e in events]}"
        )
        assert reinits[0].payload.get("transport") == "streamable_http"
    finally:
        transport.close()


@_with_session_mock
def _test_D3_second_loss_surfaces_error(mock):
    """Two consecutive session losses → error bubbles to the caller.

    Flow: arm the mock to drop the next call. The transport's one-shot
    re-init fires, attempts the retry, and the mock drops that too
    (the retry is the "next" request at that point if we re-arm). The
    transport MUST surface the error rather than retry again.

    Implementation detail: kill_next is one-shot, so after the first
    failure we re-arm it right before the retry's initialize would
    succeed. We do that via a mock-side latch that re-arms on the first
    *successful* initialize (i.e. the re-init issued by the transport).
    """
    from proxy.proxy_server import MorpheusProxy
    from proxy.transport import StreamableHttpTransport

    # Trickier: we need the second call (during retry) to also fail.
    # Easiest path: kill both the initial tools/call AND the tools/call
    # that follows the re-init.
    #
    # We implement this by arming kill_next, then in a side thread
    # re-arming it once the first kill is consumed. A tight spin with a
    # short deadline is fine — all mock traffic is loopback.
    import time as _t
    import threading as _th

    def _rearm_watcher():
        # Wait for the first kill to be consumed, then re-arm once more.
        deadline = _t.time() + 5.0
        while _t.time() < deadline:
            if mock.kill_count >= 1:
                mock.kill_next = True
                return
            _t.sleep(0.01)

    transport = StreamableHttpTransport(mock.url())
    try:
        proxy = MorpheusProxy(real_server_or_transport=transport)

        mock.kill_next = True
        watcher = _th.Thread(target=_rearm_watcher, daemon=True)
        watcher.start()

        r = proxy.call_tool(
            "noop",
            {},
            controls_active={
                "input_validation": True,
                "action_validation": False,
                "coherence_check": False,
            },
        )
        watcher.join(timeout=2.0)

        # Proxy surfaces transport errors as status="error" (see
        # MorpheusProxy.call_tool's except-Exception branch).
        assert r["status"] == "error", r
        # At least 2 drops consumed — the second was the retry that
        # the transport MUST NOT have retried again.
        assert mock.kill_count >= 2, (
            f"expected >=2 kills (initial + retry), got {mock.kill_count}"
        )
    finally:
        transport.close()


@_with_session_mock
def _test_D4_shutdown_sends_terminate(mock):
    """transport.close() → mock observes a DELETE (best-effort terminate).

    The SDK's streamable_http_client has terminate_on_close=True by default,
    so closing the AsyncExitStack should fire a DELETE at the session URL.
    """
    from proxy.transport import StreamableHttpTransport

    t = StreamableHttpTransport(mock.url())
    try:
        # Force a session to exist.
        t.list_tools()
        assert mock.delete_calls == 0
    finally:
        t.close()

    assert mock.delete_calls == 1, (
        f"expected exactly one DELETE after close(), got {mock.delete_calls}"
    )


# ── Group E — Session-loss error code guard ────────────────────────────────

@_with_session_mock
def _test_E1_sdk_still_emits_expected_session_loss_code(mock):
    """Protects against SDK drift on the session-terminated error code.

    StreamableHttpTransport pins _MCP_SESSION_TERMINATED_CODE = 32600
    because the SDK hardcodes that literal in
    streamable_http.py:_send_session_terminated_error without exporting
    a named constant. If a future SDK version changes the code, or
    introduces an exported named constant, this test forces us to
    notice.

    Procedure:
      1. Stand up the minimal streamable-HTTP mock and arm it to drop
         the next request after initialize succeeds.
      2. Drive the SDK directly (no Morpheus transport) through an
         initialize + list_tools round-trip, catch the resulting
         McpError, and read its error.code.
      3. Assert the code matches our local constant.
      4. Separately assert that mcp.types still has no exported
         constant named like a session-termination code — if that ever
         changes, this test fails and we switch to the import.
    """
    import asyncio as _asyncio
    import mcp.types as _mcp_types
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared.exceptions import McpError

    from proxy.transport import _MCP_SESSION_TERMINATED_CODE

    captured = {"code": None, "message": None}

    async def _drive():
        async with streamable_http_client(mock.url()) as (read, write, _sid):
            async with ClientSession(read, write) as session:
                await session.initialize()
                # Drain the initialized notification that initialize() fires
                # but does not await — otherwise our kill_next flip could
                # land on the notification rather than the list_tools request.
                # The notification lands as a 202 Accepted and is ignored
                # by the SDK; we just need it out of the way.
                await _asyncio.sleep(0.2)
                mock.kill_next = True
                try:
                    await session.list_tools()
                except McpError as e:
                    captured["code"] = e.error.code
                    captured["message"] = e.error.message

    # Run on a short-lived dedicated loop — this test is self-contained
    # and does not need the StreamableHttpTransport's long-lived thread.
    loop = _asyncio.new_event_loop()
    try:
        loop.run_until_complete(_asyncio.wait_for(_drive(), timeout=15.0))
    finally:
        loop.close()

    assert captured["code"] is not None, (
        "expected an McpError from the SDK after the mock dropped the "
        "session; got nothing"
    )
    assert captured["code"] == _MCP_SESSION_TERMINATED_CODE, (
        f"SDK session-terminated code drifted: expected "
        f"{_MCP_SESSION_TERMINATED_CODE}, got {captured['code']!r} "
        f"(message={captured['message']!r}). Update "
        f"proxy/transport.py:_MCP_SESSION_TERMINATED_CODE and re-read the "
        f"SDK to see whether it now exports a named constant we should "
        f"import instead of pinning a literal."
    )

    # Drift check: if the SDK starts exporting a session-termination
    # constant we should prefer that over our literal. Fail loudly to
    # force the update.
    sdk_constants = [
        n for n in dir(_mcp_types)
        if ("SESSION" in n.upper() and ("TERMIN" in n.upper() or "LOST" in n.upper()))
    ]
    assert not sdk_constants, (
        f"mcp.types now exports {sdk_constants} — replace the literal "
        f"_MCP_SESSION_TERMINATED_CODE with this named constant."
    )


def register(run_fn=run):
    section("Layer 11b — MCP Proxy: Streamable-HTTP Transport")

    # Group A — Transport selection (no network)
    run_fn("A.1", "default (no flag, no env) → PlainJsonRpcTransport", _test_A1_default_is_plain_jsonrpc)
    run_fn("A.2", "--transport plain_jsonrpc → PlainJsonRpcTransport", _test_A2_flag_plain_jsonrpc)
    run_fn("A.3", "--transport streamable_http → StreamableHttpTransport", _test_A3_flag_streamable_http)
    run_fn("A.4", "env MORPHEUS_DOWNSTREAM_TRANSPORT=streamable_http → StreamableHttpTransport", _test_A4_env_streamable_http)
    run_fn("A.5", "flag overrides env when both present", _test_A5_flag_overrides_env)
    run_fn("A.6", "unknown flag value → argparse SystemExit(2)", _test_A6_bad_flag_rejected)
    run_fn("A.7", "unknown env value → _build_transport ValueError", _test_A7_bad_env_rejected)

    # Group B — PlainJsonRpcTransport regression
    run_fn("B.1", "PlainJsonRpcTransport end-to-end against mock matches Layer 11 expectations", _test_B1_plain_jsonrpc_regression)

    # Group C — StreamableHttpTransport against a real FastMCP
    run_fn("C.1", "StreamableHttpTransport.list_tools() → expected tool set", _test_C1_streamable_list_tools)
    run_fn("C.2", "StreamableHttpTransport.call_tool() → expected result", _test_C2_streamable_call_tool)
    run_fn("C.3", "audit log carries transport=streamable_http on forwarded call", _test_C3_audit_includes_streamable_transport)

    # Group D — Session lifecycle
    run_fn("D.1", "consecutive calls reuse a single session", _test_D1_session_is_reused)
    run_fn("D.2", "simulated session loss → one-shot reinit + reinit audit event", _test_D2_session_loss_triggers_reinit)
    run_fn("D.3", "second consecutive session loss → error surfaces, no infinite retry", _test_D3_second_loss_surfaces_error)
    run_fn("D.4", "transport.close() sends a DELETE to the session URL", _test_D4_shutdown_sends_terminate)

    # Group E — Session-loss error code guard (protects against SDK drift)
    run_fn("E.1", "SDK still emits code 32600 on session loss", _test_E1_sdk_still_emits_expected_session_loss_code)
