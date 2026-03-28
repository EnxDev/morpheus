"""Dynamic tool discovery — connects to a real MCP server and calls tools/list.

No tools are hardcoded. Everything comes from the real server.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

import requests


@dataclass
class ToolDefinition:
    """A tool discovered from a real MCP server."""

    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)
    output_schema: dict | None = None


class ToolDiscovery:
    """Connects to a real MCP server and discovers its tools via tools/list."""

    def __init__(self, server_url: str, timeout: int = 30) -> None:
        self._server_url = server_url.rstrip("/")
        self._timeout = timeout
        self._on_change_callbacks: list[Callable[[], None]] = []
        self._watch_thread: threading.Thread | None = None
        self._watching = False

    @property
    def server_url(self) -> str:
        return self._server_url

    def discover(self) -> list[ToolDefinition]:
        """Send tools/list JSON-RPC request to the real server.

        Request:
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}

        Parses response: result.tools -> list of tool objects.
        Each tool includes: name, description, inputSchema, outputSchema (if present).
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
