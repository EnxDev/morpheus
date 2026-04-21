"""Dynamic tool discovery — connects to a real MCP server and calls tools/list.

No tools are hardcoded. Everything comes from the real server.

Wire format is delegated to a ``DownstreamTransport``. By default — and
always, for code paths that pass a URL string — the plain JSON-RPC
transport is used, preserving the original behaviour. Callers that want
the streamable-HTTP transport construct it explicitly and inject it.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from proxy.transport import DownstreamTransport, PlainJsonRpcTransport


@dataclass
class ToolDefinition:
    """A tool discovered from a real MCP server."""

    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict | None = None


class ToolDiscovery:
    """Connects to a real MCP server and discovers its tools via tools/list.

    Accepts either a URL string (constructs a default
    :class:`PlainJsonRpcTransport` — backwards-compatible with every
    existing caller) or a pre-built transport instance.
    """

    def __init__(
        self,
        server_or_transport: str | DownstreamTransport,
        timeout: int = 30,
    ) -> None:
        if isinstance(server_or_transport, DownstreamTransport):
            self._transport = server_or_transport
            # Expose the URL for audit/status when the transport advertises one.
            self._server_url = getattr(server_or_transport, "server_url", "")
        else:
            self._server_url = server_or_transport.rstrip("/")
            self._transport = PlainJsonRpcTransport(self._server_url, timeout=timeout)
        self._timeout = timeout
        self._on_change_callbacks: list[Callable[[], None]] = []
        self._watch_thread: threading.Thread | None = None
        self._watching = False

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def transport(self) -> DownstreamTransport:
        return self._transport

    def discover(self) -> list[ToolDefinition]:
        """Ask the transport for the downstream tool catalogue.

        The transport returns raw MCP-shape dicts; this method wraps them
        in :class:`ToolDefinition` objects. Wire details (JSON-RPC envelope
        vs streamable-HTTP session) live inside the transport.
        """
        tools_raw = self._transport.list_tools()

        tools = []
        for t in tools_raw:
            tools.append(ToolDefinition(
                name=t.get("name", ""),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                output_schema=t.get("outputSchema"),
            ))

        return tools

    def on_change(self, callback: Callable[[], None]) -> None:
        """Register a callback to be called when tools/list changes."""
        self._on_change_callbacks.append(callback)

    def watch_changes(self) -> None:
        """Listen for notifications/tools/list_changed from the real server.

        Re-runs discover() when received and notifies registered callbacks.
        Runs in a background thread polling for changes.
        """
        if self._watching:
            return

        self._watching = True

        def _poll():
            last_tools: set[str] = set()
            while self._watching:
                try:
                    tools = self.discover()
                    current = {t.name for t in tools}
                    if last_tools and current != last_tools:
                        for cb in self._on_change_callbacks:
                            try:
                                cb()
                            except Exception:
                                pass
                    last_tools = current
                except Exception:
                    pass
                # Poll interval
                threading.Event().wait(timeout=5.0)

        self._watch_thread = threading.Thread(target=_poll, daemon=True)
        self._watch_thread.start()

    def stop_watching(self) -> None:
        """Stop watching for changes."""
        self._watching = False
        self._watch_thread = None
