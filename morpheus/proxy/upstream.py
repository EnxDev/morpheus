"""Upstream MCP streamable-HTTP endpoint for the Morpheus HTTP proxy.

This module owns everything that makes the proxy *look like* an MCP
server to client-facing connections. The companion module
``proxy/transport.py`` owns the inverse direction (the proxy speaking
streamable-HTTP downstream to a real MCP backend).

Architecture in one sentence: a :class:`UpstreamMcp` instance wraps a
:class:`MorpheusProxy`, exposes its tool catalogue via FastMCP, and
hands the FastAPI parent app a mountable ASGI sub-app plus the
lifespan context that sub-app needs.

See ``docs/streamable-http-upstream.md`` for the full design — the
locked decisions in §4 are the contract this module follows.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Callable

from fastmcp import FastMCP
from fastmcp.tools.tool import Tool

if TYPE_CHECKING:
    from controls import ControlManager
    from proxy.proxy_server import MorpheusProxy


_DEFAULT_MOUNT_PATH = "/mcp/"


class ProxyKeyAuthMiddleware:
    """ASGI middleware enforcing the same proxy-key check as the REST endpoints.

    Wraps an inner ASGI app. On each HTTP request:

    - ``proxy_key`` empty → pass through unchanged (parity with the
      REST dev-mode behaviour in :func:`http_proxy._check_auth`).
    - ``X-Proxy-Key: <key>`` matches → pass through.
    - ``Authorization: Bearer <key>`` matches → pass through.
    - Otherwise → respond 401 with a small JSON body, never reach the
      inner app.

    Scoped to the MCP mount; the existing ``_check_auth`` per-request
    helper continues to guard ``/proxy/*`` exactly as before.
    """

    def __init__(self, app, proxy_key: str) -> None:
        self._app = app
        self._proxy_key = proxy_key

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            # WebSocket / lifespan messages: pass straight through —
            # auth applies to HTTP requests only.
            await self._app(scope, receive, send)
            return

        if not self._proxy_key:
            # Dev mode: no key configured, accept everything.
            await self._app(scope, receive, send)
            return

        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1")
            for k, v in scope.get("headers", [])
        }
        provided = headers.get("x-proxy-key")
        if provided is None:
            authz = headers.get("authorization", "")
            if authz.startswith("Bearer "):
                provided = authz[len("Bearer "):]

        if provided == self._proxy_key:
            await self._app(scope, receive, send)
            return

        body = b'{"error":"unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
        })
        await send({"type": "http.response.body", "body": body})


def _extract_text(result: Any) -> str:
    """Extract a flat text representation from an MCP tool result.

    The proxy's call_tool returns the downstream's ``result`` block,
    which in MCP shape looks like ``{"content": [{"type": "text",
    "text": "..."}], "isError": bool}``. We flatten to a single string
    so the MCP-server tool handler can return ``str`` (FastMCP turns
    that back into a TextContent). Mirrors mcp_bridge.py:206-222 but
    duplicated rather than imported because the bridge entangles its
    helper with stdio-specific module globals.

    Future cleanup: extract a shared helper if a third consumer
    appears.
    """
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content_list = result.get("content", [])
        if isinstance(content_list, list):
            texts = [c.get("text", "") for c in content_list if isinstance(c, dict)]
            if texts:
                return "\n".join(texts)
        if "structuredContent" in result:
            return json.dumps(result["structuredContent"])
        return json.dumps(result)
    return str(result)


class UpstreamMcp:
    """The MCP-server-side half of the proxy.

    Constructs a :class:`fastmcp.FastMCP` instance, registers each tool
    discovered by the wrapped :class:`MorpheusProxy`, optionally adds
    three management tools (``set_validated_intent``, ``get_proxy_status``,
    ``get_proxy_audit``), and subscribes to the proxy's
    tools-changed event so the FastMCP catalogue stays in sync.

    Construction does not start a server. The caller obtains the ASGI
    sub-app via :attr:`asgi_app` and the lifespan context via
    :meth:`lifespan_context`, mounts both onto a FastAPI app, and serves
    them with uvicorn — the integration point lives in
    :mod:`proxy.http_proxy`.
    """

    def __init__(
        self,
        proxy: "MorpheusProxy",
        *,
        expose_admin_tools: bool = True,
        stateless: bool = False,
        mount_path: str = _DEFAULT_MOUNT_PATH,
        control_manager: "ControlManager | None" = None,
        intent_provider: Callable[[], dict | None] | None = None,
        intent_setter: Callable[[dict], None] | None = None,
    ) -> None:
        """Build the upstream MCP endpoint around a MorpheusProxy.

        ``control_manager`` is consulted on every proxied tool call to
        forward the operator's current control toggles to
        ``MorpheusProxy.call_tool``. When ``None`` (used in tests),
        the proxy's internal defaults apply.

        ``intent_provider`` returns the current validated intent — a
        zero-arg callable so the upstream module reads the value lazily
        each call rather than capturing a stale snapshot. In production
        this is wired to ``http_proxy._validated_intent`` via a small
        getter; in tests it can be a closure over a local dict.
        """
        self._proxy = proxy
        self._expose_admin_tools = expose_admin_tools
        self._stateless = stateless
        self._mount_path = mount_path
        self._control_manager = control_manager
        self._intent_provider = intent_provider
        self._intent_setter = intent_setter

        # Build the FastMCP instance.
        self._mcp: FastMCP = FastMCP(
            "Morpheus Proxy",
            instructions=(
                "Morpheus HTTP proxy MCP endpoint. Every tools/call is "
                "validated by Control 2 (policy + coherence) before being "
                "forwarded to the downstream MCP server."
            ),
        )

        # Track which proxied tool names are currently registered so
        # the tools-changed handler (Commit 6) can diff against the
        # latest get_proxied_tools() output. Admin tools are tracked
        # separately because they are static for the proxy's lifetime.
        self._registered_proxied_tools: set[str] = set()

        # The FastMCP-built Starlette ASGI sub-app. Lazily constructed
        # by ``asgi_app`` / ``lifespan_context`` so simple introspection
        # tests don't pay the http_app cost.
        self._asgi_app = None

        self._register_proxied_tools()
        if self._expose_admin_tools:
            self._register_admin_tools()

        # Subscribe to live discovery changes — when the downstream
        # announces tools/list_changed, the proxy fires this callback
        # and we re-sync the FastMCP catalogue (real body in Commit 6).
        self._proxy.add_tools_changed_listener(self._handle_tools_changed)

    # ── Tool registration (real bodies land in Commit 3) ─────────────

    def _register_proxied_tools(self) -> None:
        """Register every tool returned by ``proxy.get_proxied_tools``.

        Each tool is exposed with a single ``arguments_json: str``
        parameter, mirroring the pattern in ``mcp_bridge.py``: the
        adapter parses the JSON string, calls ``proxy.call_tool``, and
        translates the proxy's ``{status, result, decision}`` envelope
        back into a flat string the MCP client receives as the tool's
        text content.

        Schema-faithful per-tool argument surfacing is roadmap (see
        design doc §11). v1 keeps the stdio bridge's JSON-string form.
        """
        for tool_def in self._proxy.get_proxied_tools():
            self._register_one_proxied_tool(tool_def)

    def _register_one_proxied_tool(self, tool_def: dict) -> None:
        name = tool_def["name"]
        description = tool_def.get("description", "")
        input_schema = tool_def.get("inputSchema", {})

        handler = self._make_proxied_handler(name)
        handler.__name__ = name
        handler.__doc__ = (
            f"[Proxied via Morpheus] {description}\n\n"
            f"Pass arguments as a JSON string. Expected shape "
            f"(MCP inputSchema):\n{json.dumps(input_schema, indent=2)}"
        )
        self._mcp.add_tool(Tool.from_function(handler))
        self._registered_proxied_tools.add(name)

    def _make_proxied_handler(self, tool_name: str) -> Callable[[str], str]:
        """Build the closure that handles one proxied tool call.

        The closure captures ``tool_name`` and reads
        ``self._intent_provider`` / ``self._control_manager`` lazily
        each call so live changes (e.g. an operator flipping a control,
        or a client setting a new validated intent) take effect on the
        very next call.
        """
        proxy = self._proxy

        def handler(arguments_json: str = "{}") -> str:
            try:
                args = json.loads(arguments_json) if arguments_json else {}
            except json.JSONDecodeError:
                return f"ERROR: Invalid JSON arguments: {arguments_json[:100]}"

            controls = None
            if self._control_manager is not None:
                controls = self._control_manager.get_controls().to_dict()

            intent = None
            if self._intent_provider is not None:
                intent = self._intent_provider()

            result = proxy.call_tool(
                tool_name=tool_name,
                arguments=args,
                original_intent=intent,
                controls_active=controls,
            )

            status = result["status"]
            decision = result.get("decision", {})

            if status == "blocked":
                reason = decision.get("reason", "Blocked by Morpheus policy")
                return f"BLOCKED: {reason}"

            if status == "error":
                inner = result.get("result", {})
                return f"ERROR: {_extract_text(inner)}"

            inner = result.get("result", {})
            text = _extract_text(inner)
            if status == "bypassed":
                return f"[BYPASSED] {text}"
            return text

        return handler

    def _register_admin_tools(self) -> None:
        """Register the three management tools.

        Mirrors ``mcp_bridge.py``'s management surface:
        ``set_validated_intent``, ``get_proxy_status``,
        ``get_proxy_audit``. They sit behind the same proxy-key auth as
        every other MCP tool.

        ``set_validated_intent`` writes through the configured
        ``intent_provider`` only if it carries a setter sibling — for
        v1 it raises a clear error if the upstream was wired without an
        intent setter, mirroring the design doc §11 acknowledgement
        that the global ``_validated_intent`` lives in ``http_proxy.py``.
        """
        proxy = self._proxy
        intent_setter = getattr(self, "_intent_setter", None)

        @self._mcp.tool
        def set_validated_intent(intent_json: str) -> str:
            """Set the validated user intent for coherence checking.

            Pass the intent as a JSON object string. Mirrors the
            ``POST /proxy/intent`` REST endpoint.
            """
            try:
                parsed = json.loads(intent_json)
            except json.JSONDecodeError as exc:
                return f"ERROR: Invalid JSON: {exc}"
            if intent_setter is None:
                return (
                    "ERROR: This UpstreamMcp instance was constructed "
                    "without an intent setter; set_validated_intent has "
                    "no effect."
                )
            intent_setter(parsed)
            proxy.logger.log("intent_set_for_proxy", {"intent": parsed})
            return f"OK: intent set with fields {sorted(parsed.keys())}"

        @self._mcp.tool
        def get_proxy_status() -> str:
            """Return discovered tools, server URL, and basic counters."""
            return json.dumps({
                "real_server": proxy.real_server_url,
                "tool_count": proxy.tool_count,
                "discovered_tools": [
                    t["name"] for t in proxy.get_proxied_tools()
                ],
            })

        @self._mcp.tool
        def get_proxy_audit(last_n: int = 20) -> str:
            """Return the last N proxy audit events as a JSON list."""
            return json.dumps({
                "events": [e.to_dict() for e in proxy.logger.last(last_n)],
            }, default=str)

    def _handle_tools_changed(self) -> None:
        """Re-sync the FastMCP tool catalogue against the proxy.

        Computes the diff between currently-registered proxied tool
        names and the proxy's latest catalogue, then calls
        ``mcp.add_tool`` for new tools and ``mcp.remove_tool`` for
        removed ones. Admin tools are not in the diff — they are
        static for the proxy's lifetime.

        FastMCP fans out a ``tools/list_changed`` notification to
        connected MCP clients automatically on add/remove, so client
        propagation is free.

        Fires on the discovery polling thread; the call sites in
        ``MorpheusProxy._on_tools_changed`` already wrap each listener
        in try/except, so any exception raised here is caught and
        audited rather than crashing the proxy.
        """
        latest = {t["name"]: t for t in self._proxy.get_proxied_tools()}
        latest_names = set(latest)
        current_names = set(self._registered_proxied_tools)

        for removed in current_names - latest_names:
            self._mcp.remove_tool(removed)
            self._registered_proxied_tools.discard(removed)

        for added in latest_names - current_names:
            self._register_one_proxied_tool(latest[added])

    # ── ASGI integration ──────────────────────────────────────────────

    def _build_asgi_app(self):
        """Build (and cache) the FastMCP-backed Starlette ASGI sub-app.

        Subtle: the sub-app's *internal* route is fixed at ``/`` so
        FastAPI can mount it at the user-visible ``mount_path`` without
        the path doubling up (the spec route then resolves to
        ``mount_path`` end-to-end). FastMCP defaults to ``path="/mcp/"``
        which would put the route at ``mount_path + "/mcp/"`` —
        clients would have to hit ``/mcp/mcp/`` and that is exactly the
        case we don't want.
        """
        if self._asgi_app is None:
            self._asgi_app = self._mcp.http_app(
                transport="streamable-http",
                path="/",
                stateless_http=self._stateless,
            )
        return self._asgi_app

    @property
    def asgi_app(self):
        """The mountable Starlette ASGI sub-app for ``FastAPI.mount(...)``."""
        return self._build_asgi_app()

    def lifespan_context(self, app):
        """Return the async context manager the FastAPI parent must enter.

        Without this, FastMCP's StreamableHTTPSessionManager.run() is
        never entered and the first /mcp/ request fails with
        "Task group is not initialized". See design doc §8 for the
        footgun discussion.
        """
        return self._build_asgi_app().router.lifespan_context(app)

    # ── Read-only accessors used by tests and http_proxy.py ──────────

    @property
    def fastmcp(self) -> FastMCP:
        return self._mcp

    @property
    def mount_path(self) -> str:
        return self._mount_path

    @property
    def stateless(self) -> bool:
        return self._stateless

    @property
    def expose_admin_tools(self) -> bool:
        return self._expose_admin_tools
