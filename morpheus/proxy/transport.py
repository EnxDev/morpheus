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

from abc import ABC, abstractmethod
from typing import Any


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
