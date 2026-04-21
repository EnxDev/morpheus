"""DownstreamTransport — abstraction over the wire format used to talk to a
real MCP server.

The Morpheus proxy's downstream leg can speak two transports:

- ``plain_jsonrpc``: the original Morpheus-custom JSON-RPC-over-HTTP dialect
  (see :class:`PlainJsonRpcTransport`, added in a later commit).
- ``streamable_http``: the MCP spec's streamable-HTTP transport, implemented
  via the official ``mcp`` SDK (see :class:`StreamableHttpTransport`,
  added in a later commit).

The proxy (``ToolDiscovery``, ``MorpheusProxy``) depends only on this
abstract interface. Concrete implementations live in this same module so
that the SDK import stays localised.

Design rationale and full context:
``docs/streamable-http-transport.md`` and ``docs/sdk-notes-phase2.md``.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from abc import ABC, abstractmethod
from typing import Any, Callable

import requests


# Transport identifiers accepted on CLI / env / config. Kept here (not in
# http_proxy.py) so the abstraction module owns its own vocabulary.
TRANSPORT_PLAIN_JSONRPC = "plain_jsonrpc"
TRANSPORT_STREAMABLE_HTTP = "streamable_http"

VALID_TRANSPORTS = frozenset({TRANSPORT_PLAIN_JSONRPC, TRANSPORT_STREAMABLE_HTTP})


class DownstreamTransport(ABC):
    """Abstract base for all downstream transports.

    Exposes exactly the two operations the proxy uses today — ``list_tools``
    and ``call_tool`` — plus a ``close`` lifecycle hook for transports that
    hold long-lived resources (sessions, background threads).

    Implementations MUST be safe to call from multiple threads concurrently
    on FastAPI / uvicorn's threadpool. How they achieve that is their own
    business — the plain JSON-RPC path is stateless per request; the
    streamable-HTTP path marshals onto a dedicated event loop.
    """

    #: Short identifier for audit-log ``transport`` field. Concrete
    #: subclasses must override with one of :data:`VALID_TRANSPORTS`.
    name: str = ""

    @abstractmethod
    def list_tools(self) -> list[dict[str, Any]]:
        """Fetch the downstream server's tool catalogue.

        Returns a list of raw tool dicts in MCP shape (``name``,
        ``description``, ``inputSchema``, optional ``outputSchema``).
        The caller (``ToolDiscovery``) wraps these in ``ToolDefinition``
        objects — this layer does not impose Morpheus types on the wire
        data.
        """

    @abstractmethod
    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Invoke ``tool_name`` with ``arguments`` on the downstream server.

        Returns the MCP ``result`` object — typically a dict of shape
        ``{"content": [...], "isError": bool, ...}``. Callers do NOT
        re-interpret tool-level errors; they pass through.

        Transport-level failures (network drop, session loss past the
        one-shot re-init budget, malformed response) raise an exception.
        The proxy catches and wraps those at a higher level.
        """

    def close(self) -> None:
        """Release any long-lived resources held by the transport.

        Default is a no-op — transports with nothing to clean up (plain
        JSON-RPC) inherit it. Transports that hold a session or background
        thread override this.

        ``close`` MUST be idempotent.
        """
        return None


# ── PlainJsonRpcTransport ────────────────────────────────────────────────────

# Default HTTP timeout for plain JSON-RPC requests. Matches the value the
# legacy code used in ``discovery.py`` (constructor default) and
# ``proxy_server._forward_call`` (inline literal).
_DEFAULT_TIMEOUT_SECONDS = 30


class PlainJsonRpcTransport(DownstreamTransport):
    """The original Morpheus-custom JSON-RPC-over-HTTP dialect.

    Sends a bare JSON-RPC 2.0 envelope as the POST body to a single
    downstream URL, and parses ``result.tools`` / ``result`` directly from
    the response JSON. No session negotiation, no SSE, no Accept header
    dance. This is what ``hr_mcp_server.py`` and ``tests/mock_mcp_server.py``
    speak.

    This class is a pure extraction of the logic previously inlined in
    :mod:`proxy.discovery` and :mod:`proxy.proxy_server`. Behaviour is
    byte-identical — same payload shape, same fixed ``"id": 1``, same
    30-second timeout, same error-raising contract.
    """

    name = TRANSPORT_PLAIN_JSONRPC

    def __init__(self, server_url: str, timeout: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout = timeout

    @property
    def server_url(self) -> str:
        return self._server_url

    def list_tools(self) -> list[dict[str, Any]]:
        """Send a ``tools/list`` request and return the raw tool dicts.

        Matches the legacy ``ToolDiscovery.discover`` wire payload:
        ``{"jsonrpc": "2.0", "method": "tools/list", "id": 1}``.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "id": 1,
        }

        response = requests.post(self._server_url, json=payload, timeout=self._timeout)
        response.raise_for_status()

        data = response.json()

        # MCP response: {"jsonrpc": "2.0", "result": {"tools": [...]}, "id": 1}
        result = data.get("result", data)
        tools_raw = result.get("tools", []) if isinstance(result, dict) else []
        return list(tools_raw)

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Send a ``tools/call`` request and return the ``result`` field.

        Matches the legacy ``MorpheusProxy._forward_call`` payload shape.
        """
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 1,
        }
        response = requests.post(self._server_url, json=payload, timeout=self._timeout)
        response.raise_for_status()
        data = response.json()
        return data.get("result", data)


# ── StreamableHttpTransport ──────────────────────────────────────────────────

# SDK imports are local-to-the-class to keep the plain-JSON-RPC path free of
# the mcp dependency at import time. If someone runs the proxy with
# --transport plain_jsonrpc, a broken or missing mcp install must not break
# them. The imports happen inside StreamableHttpTransport's methods instead.

# The "Session terminated" error code is emitted by the SDK's
# streamable_http client as a literal in _send_session_terminated_error
# (mcp/client/streamable_http.py:519). It is not exported as a named
# constant in the SDK, so we pin it here with a citation. If the SDK ever
# promotes it to a named constant we should switch to the import.
_MCP_SESSION_TERMINATED_CODE = 32600


# How long a single list_tools / call_tool submission is allowed to block
# the caller thread before we give up. The underlying session read timeout
# is separate — this bounds the sync-to-async handoff itself.
_STREAMABLE_CALL_TIMEOUT_SECONDS = 60.0

# How long close() waits for the background loop thread to finish its
# teardown. The teardown is a best-effort session DELETE; not worth
# blocking shutdown forever on a hung downstream.
_STREAMABLE_CLOSE_TIMEOUT_SECONDS = 10.0


class SessionLostError(Exception):
    """Raised internally to signal that a session-loss retry should fire.

    The proxy's external callers never see this — it is caught inside
    :class:`StreamableHttpTransport` and transformed into a re-init attempt.
    """


class StreamableHttpTransport(DownstreamTransport):
    """MCP streamable-HTTP transport via the official ``mcp`` SDK.

    Lifecycle model (see docs/sdk-notes-phase2.md, section 2):

    - A dedicated background thread owns an ``asyncio`` event loop.
    - On first use, a coroutine enters ``streamable_http_client(...)`` and
      then ``ClientSession(...)``, awaits ``initialize()``, stores the
      session reference, and parks on an ``asyncio.Event`` until either
      shutdown is requested or a re-init is forced.
    - Every ``list_tools`` / ``call_tool`` submits a coroutine to the
      background loop via ``run_coroutine_threadsafe`` and blocks on the
      result. This keeps the interface sync for the proxy while the
      session stays open across calls.
    - On ``McpError`` with ``error.code == 32600`` ("Session terminated")
      or the SDK's ``CONNECTION_CLOSED`` code, the transport attempts
      ONE silent re-init (new session, new ``initialize``) and retries
      the original operation. A second failure surfaces normally.
    - ``close()`` signals the parked coroutine to tear down the exit
      stack — the SDK's ``streamable_http_client`` context manager
      handles the session-terminate DELETE on exit.

    Thread-safety: all state transitions happen on the background loop.
    The caller side uses a single ``_call_lock`` to serialise submissions
    during re-init, because re-init swaps ``self._session`` and we don't
    want a concurrent caller observing a half-torn-down state.
    """

    name = TRANSPORT_STREAMABLE_HTTP

    def __init__(self, server_url: str) -> None:
        self._server_url = server_url
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._thread_ready = threading.Event()
        self._closed = False

        # Owned and touched only on the background loop.
        self._stack: contextlib.AsyncExitStack | None = None
        self._session: Any = None  # mcp.ClientSession
        self._shutdown_event: asyncio.Event | None = None

        # Serialises re-init against concurrent callers.
        self._call_lock = threading.Lock()

        self._start_loop_thread()

    @property
    def server_url(self) -> str:
        return self._server_url

    # ── Background loop ──────────────────────────────────────────────

    def _start_loop_thread(self) -> None:
        def _run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            self._thread_ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        self._thread = threading.Thread(
            target=_run,
            name="morpheus-streamable-http",
            daemon=True,
        )
        self._thread.start()
        # Wait for the loop to be ready before anyone tries to submit.
        self._thread_ready.wait(timeout=5.0)

    def _submit(self, coro_factory: Callable[[], Any], timeout: float) -> Any:
        """Run ``coro_factory()`` on the background loop and block for the result.

        Must be called with ``_call_lock`` held if the caller touches
        session state that could race with re-init.
        """
        if self._closed or self._loop is None:
            raise RuntimeError("StreamableHttpTransport is closed")
        future = asyncio.run_coroutine_threadsafe(coro_factory(), self._loop)
        return future.result(timeout=timeout)

    # ── Session lifecycle (runs on background loop) ──────────────────

    async def _open_session(self) -> None:
        """Enter streamable_http_client + ClientSession, initialize.

        Called on the background loop. Populates ``self._session`` and
        ``self._stack``. The stack stays open until ``_close_session``.
        """
        from contextlib import AsyncExitStack

        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        stack = AsyncExitStack()
        read, write, _get_sid = await stack.enter_async_context(
            streamable_http_client(self._server_url)
        )
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._stack = stack
        self._session = session

    async def _close_session(self) -> None:
        """Close the current exit stack, terminating the session.

        The SDK's ``streamable_http_client`` issues a best-effort DELETE
        on exit when ``terminate_on_close=True`` (its default).
        """
        stack = self._stack
        self._stack = None
        self._session = None
        if stack is not None:
            with contextlib.suppress(Exception):
                await stack.aclose()

    async def _ensure_session(self) -> None:
        if self._session is None:
            await self._open_session()

    # ── Session-loss detection ───────────────────────────────────────

    @staticmethod
    def _is_session_lost(exc: BaseException) -> bool:
        """True if ``exc`` indicates the downstream session is gone.

        Recognises both the streamable-HTTP "Session terminated" error
        (code 32600, emitted by the SDK on a 404 with session header)
        and the generic connection-closed error that fires when the
        underlying stream dies.
        """
        try:
            from mcp.shared.exceptions import McpError
            from mcp.types import CONNECTION_CLOSED
        except Exception:  # pragma: no cover — SDK missing shouldn't reach here
            return False
        if not isinstance(exc, McpError):
            return False
        code = getattr(exc.error, "code", None)
        return code == _MCP_SESSION_TERMINATED_CODE or code == CONNECTION_CLOSED

    # ── Public API ───────────────────────────────────────────────────

    def list_tools(self) -> list[dict[str, Any]]:
        raw = self._run_with_retry(self._list_tools_once)
        return raw

    def call_tool(self, tool_name: str, arguments: dict) -> Any:
        return self._run_with_retry(
            lambda: self._call_tool_once(tool_name, arguments),
        )

    def _run_with_retry(self, op: Callable[[], Any]) -> Any:
        """Submit ``op`` to the background loop with one-shot session re-init.

        ``op`` is a zero-arg callable returning a coroutine. It is invoked
        twice at most: on a session-loss error we tear down and re-open
        the session, then re-invoke. Any other error surfaces immediately.
        """
        with self._call_lock:
            try:
                return self._submit(op, _STREAMABLE_CALL_TIMEOUT_SECONDS)
            except Exception as exc:
                if not self._is_session_lost(exc):
                    raise
                # One-shot re-init.
                self._submit(self._close_session, _STREAMABLE_CLOSE_TIMEOUT_SECONDS)
                self._submit(self._open_session, _STREAMABLE_CALL_TIMEOUT_SECONDS)
                self._on_reinit()
                return self._submit(op, _STREAMABLE_CALL_TIMEOUT_SECONDS)

    def _on_reinit(self) -> None:
        """Hook for audit logging on re-init. Set externally by the proxy.

        Kept as a plain method rather than a constructor callback so that
        the transport module stays unaware of the AuditLogger type. The
        proxy assigns ``transport._on_reinit = lambda: logger.log(...)``
        at wiring time.
        """

    async def _list_tools_once(self) -> list[dict[str, Any]]:
        await self._ensure_session()
        result = await self._session.list_tools()
        tools_out: list[dict[str, Any]] = []
        for t in result.tools:
            entry: dict[str, Any] = {
                "name": t.name,
                "description": t.description or "",
                "inputSchema": t.inputSchema or {},
            }
            output_schema = getattr(t, "outputSchema", None)
            if output_schema is not None:
                entry["outputSchema"] = output_schema
            tools_out.append(entry)
        return tools_out

    async def _call_tool_once(self, tool_name: str, arguments: dict) -> Any:
        await self._ensure_session()
        result = await self._session.call_tool(tool_name, arguments)
        # ``CallToolResult`` dumps to the MCP wire shape
        # ``{"content": [...], "isError": bool, ...}``. The proxy's
        # downstream contract expects that dict, so serialise here.
        return result.model_dump(by_alias=True, exclude_none=True, mode="json")

    # ── Shutdown ─────────────────────────────────────────────────────

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        # Best-effort terminate (runs on background loop), then stop the loop.
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(
                self._close_session(), loop,
            ).result(timeout=_STREAMABLE_CLOSE_TIMEOUT_SECONDS)
        loop.call_soon_threadsafe(loop.stop)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=_STREAMABLE_CLOSE_TIMEOUT_SECONDS)
