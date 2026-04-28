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

from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.tools.tool import Tool

if TYPE_CHECKING:
    from proxy.proxy_server import MorpheusProxy


_DEFAULT_MOUNT_PATH = "/mcp/"


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
    ) -> None:
        self._proxy = proxy
        self._expose_admin_tools = expose_admin_tools
        self._stateless = stateless
        self._mount_path = mount_path

        # Build the FastMCP instance. The instructions string is filled
        # in once we know the tool catalogue (Commit 3).
        self._mcp: FastMCP = FastMCP(
            "Morpheus Proxy",
            instructions=(
                "Morpheus HTTP proxy MCP endpoint. Every tools/call is "
                "validated by Control 2 (policy + coherence) before being "
                "forwarded to the downstream MCP server."
            ),
        )

        # Track which tool names we have currently registered so the
        # tools-changed handler (Commit 3 / Commit 6) can compute a
        # diff against the proxy's latest catalogue.
        self._registered_proxied_tools: set[str] = set()

        # Tool registration and tools-changed wiring happen in Commit 3 /
        # Commit 6. The scaffold lets callers construct the object so the
        # http_proxy integration in Commit 4 can begin while the tool
        # adapter is still being filled in.

    # ── Tool registration (real bodies land in Commit 3) ─────────────

    def _register_proxied_tools(self) -> None:
        """Register every tool returned by ``proxy.get_proxied_tools``.

        Each tool is exposed with a single ``arguments_json: str``
        parameter, mirroring the pattern in ``mcp_bridge.py``. The real
        adapter logic lands in Commit 3.
        """
        raise NotImplementedError(
            "_register_proxied_tools is implemented in Commit 3"
        )

    def _register_admin_tools(self) -> None:
        """Register the three management tools.

        Mirrors ``mcp_bridge.py``'s management surface: ``set_validated_intent``,
        ``get_proxy_status``, ``get_proxy_audit``. Real bodies land in
        Commit 3.
        """
        raise NotImplementedError(
            "_register_admin_tools is implemented in Commit 3"
        )

    def _handle_tools_changed(self) -> None:
        """Re-sync the FastMCP tool catalogue against the proxy.

        Computes the diff between ``self._registered_proxied_tools`` and
        the proxy's current ``get_proxied_tools()``, then calls
        ``mcp.add_tool`` and ``mcp.remove_tool`` accordingly. Real body
        lands in Commit 6.
        """
        raise NotImplementedError(
            "_handle_tools_changed is implemented in Commit 6"
        )

    # ── ASGI integration (real bodies land in Commit 4) ──────────────

    @property
    def asgi_app(self):
        """The mountable Starlette ASGI sub-app for FastAPI.mount(...).

        Real implementation in Commit 4.
        """
        raise NotImplementedError("asgi_app is implemented in Commit 4")

    def lifespan_context(self, app):
        """Async context manager threading FastMCP's session-manager
        lifespan through the FastAPI parent's ``lifespan=`` parameter.

        Real implementation in Commit 4.
        """
        raise NotImplementedError("lifespan_context is implemented in Commit 4")

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
