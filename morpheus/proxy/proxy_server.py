"""MorpheusProxy — MCP server that dynamically mirrors real tools.

The LLM calls morpheus/[tool_name], Morpheus checks policy,
then either forwards to real_server/[tool_name] or blocks + logs.
Transparent to the calling LLM — same tool names and schemas.

Wire format is delegated to a ``DownstreamTransport`` (see
``proxy/transport.py``). Callers can pass a URL — in which case a
plain-JSON-RPC transport is constructed for backwards compatibility —
or inject a pre-built transport (e.g. ``StreamableHttpTransport``).
"""

from __future__ import annotations

from typing import Any, Callable

from audit.logger import AuditLogger
from proxy.discovery import ToolDiscovery, ToolDefinition
from proxy.policy_checker import PolicyChecker, ActionDecision
from proxy.transport import DownstreamTransport, PlainJsonRpcTransport


class MorpheusProxy:
    """MCP proxy that discovers tools from a real server and intercepts all calls.

    Usage:
        proxy = MorpheusProxy("http://localhost:5010")
        tools = proxy.get_proxied_tools()       # tools discovered from real server
        result = proxy.call_tool("send_email", {"to": "x@y.com", "body": "hi"}, intent)
    """

    def __init__(
        self,
        real_server_or_transport: str | DownstreamTransport,
        policy_checker: PolicyChecker | None = None,
        logger: AuditLogger | None = None,
    ) -> None:
        if isinstance(real_server_or_transport, DownstreamTransport):
            self._transport = real_server_or_transport
            self._real_server_url = getattr(real_server_or_transport, "server_url", "")
        else:
            self._real_server_url = real_server_or_transport.rstrip("/")
            self._transport = PlainJsonRpcTransport(self._real_server_url)
        self._logger = logger or AuditLogger()
        # Share the same transport instance with ToolDiscovery so a single
        # downstream session (when streamable-http is used) serves both the
        # initial discovery and every subsequent tool call.
        self._discovery = ToolDiscovery(self._transport)
        self._policy_checker = policy_checker or PolicyChecker()

        # Hook the transport's re-init callback so session re-inits are
        # visible in the audit trail. The transport exposes ``_on_reinit``
        # as a plain method overridable here — see transport.py for why
        # it is not a constructor callback.
        self._transport._on_reinit = self._on_session_reinit

        # External subscribers to "downstream tools changed" events.
        # Initialised before _discover_tools() so a callback registered
        # immediately after construction never misses a fire.
        self._tools_changed_listeners: list[Callable[[], None]] = []

        # Discover tools from the real server
        self._tools: dict[str, ToolDefinition] = {}
        self._discover_tools()

        # Register for dynamic updates
        self._discovery.on_change(self._on_tools_changed)

    def _discover_tools(self) -> None:
        """Connect to real server and dynamically register discovered tools.

        Build the new tool map and metadata in local variables, then swap
        all three references atomically (see THREADING NOTE below). This
        prevents a race where a concurrent check_action sees partially-updated
        state (e.g. _tools cleared but _tool_metadata still stale) when
        called from the background poller.
        """
        discovered = self._discovery.discover()

        # Build new state in local vars
        new_tools = {tool.name: tool for tool in discovered}
        new_names = set(new_tools.keys())
        new_metadata = {
            name: {
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for name, tool in new_tools.items()
        }

        # THREADING NOTE: These assignments rely on CPython's GIL for atomicity.
        # A single reference assignment (e.g. self._tools = new_tools) is atomic
        # under the GIL — a concurrent reader sees either the old or new dict,
        # never a partially-constructed one. If this code is ever ported to a
        # GIL-free runtime (free-threaded CPython 3.13+, PyPy STM, etc.), these
        # swaps need a threading.Lock or equivalent barrier.
        #
        # Swap order matters: metadata first, tools last. A concurrent check_action
        # that reads between swaps gets newer metadata with older tools — strictly
        # more information, never less. No bypass path exists in any interleaving.
        self._policy_checker.set_tool_metadata(new_metadata)
        self._policy_checker.set_known_tools(new_names)
        self._tools = new_tools

        self._logger.log("tools_discovered", {
            "server_url": self._real_server_url,
            "tool_count": len(discovered),
            "tools": [t.name for t in discovered],
        })

    def _on_tools_changed(self) -> None:
        """Called when tools/list_changed notification is received.

        Re-discovers tools, then notifies any external listeners
        registered via :meth:`add_tools_changed_listener`. Listener
        exceptions are caught and logged so a misbehaving subscriber
        cannot block the proxy or its other subscribers.
        """
        self._logger.log("tools_list_changed", {
            "server_url": self._real_server_url,
        })
        self._discover_tools()
        for listener in list(self._tools_changed_listeners):
            try:
                listener()
            except Exception as e:
                self._logger.log("tools_changed_listener_failed", {
                    "error": str(e),
                })

    def add_tools_changed_listener(self, callback: Callable[[], None]) -> None:
        """Register a zero-arg callback fired after each tool re-discovery.

        Used by the upstream MCP endpoint to re-sync its FastMCP tool
        catalogue when the downstream server announces tools/list_changed.
        Callbacks fire synchronously on the discovery polling thread —
        keep them quick and exception-safe; raised exceptions are caught
        and logged but not propagated.
        """
        self._tools_changed_listeners.append(callback)

    def _on_session_reinit(self) -> None:
        """Called by the transport after a one-shot session re-init.

        Only fired by transports that hold long-lived sessions (currently
        just ``StreamableHttpTransport``). Lets operators see session
        churn in the audit trail without changing any existing event shape.
        """
        self._logger.log("downstream_session_reinitialized", {
            "server_url": self._real_server_url,
            "transport": self._transport.name,
        })

    def watch_changes(self) -> None:
        """Start watching for tools/list_changed from the real server."""
        self._discovery.watch_changes()

    def stop_watching(self) -> None:
        """Stop watching for tool changes."""
        self._discovery.stop_watching()

    def refresh_tools(self) -> None:
        """Re-discover tools from the real server."""
        self._discover_tools()

    def get_proxied_tools(self) -> list[dict]:
        """Return all proxied tools in MCP tool format (for the LLM to see).

        Exposes same inputSchema and outputSchema as the originals.
        """
        result = []
        for tool in self._tools.values():
            entry: dict[str, Any] = {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            if tool.output_schema is not None:
                entry["outputSchema"] = tool.output_schema
            result.append(entry)
        return result

    def get_output_schema(self, tool_name: str) -> dict | None:
        """Get the outputSchema for a tool (if declared)."""
        tool = self._tools.get(tool_name)
        if tool is None:
            return None
        return tool.output_schema

    def call_tool(
        self,
        tool_name: str,
        arguments: dict,
        original_intent: dict | None = None,
        controls_active: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Intercept a tools/call request: check policy, then forward or block.

        Full flow:
          LLM -> tools/call morpheus/tool_name(arguments)
            -> proxy intercepts
            -> policy_checker.check(tool_name, arguments, original_intent)
            -> approved -> forwards tools/call to real server, returns result
            -> blocked  -> returns { isError: true, content: [{ text: "Blocked: [reason]" }] }
            -> bypassed -> forwards + logs with decision="bypassed"
        """
        self._logger.log("tool_call_intercepted", {
            "tool": tool_name,
            "arguments": arguments,
        })

        decision = self._policy_checker.check_action(
            tool_name=tool_name,
            arguments=arguments,
            original_intent=original_intent,
            controls_active=controls_active,
        )

        self._logger.log("policy_decision", {
            "tool": tool_name,
            "status": decision.status,
            "reason": decision.reason,
            "policy_applied": decision.policy_applied,
        })

        if decision.status == "blocked":
            # MCP spec compliant: blocked actions use isError:true (tool execution error),
            # NOT a JSON-RPC protocol error. This allows the model to read the reason.
            blocked_result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"Blocked: {decision.reason}",
                    }
                ],
                "isError": True,
            }
            return {
                "status": "blocked",
                "decision": decision.to_dict(),
                "result": blocked_result,
            }

        # Approved or bypassed — forward tools/call to real server
        try:
            result = self._forward_call(tool_name, arguments)

            # Post-execution: validate output schema if declared
            output_schema = self.get_output_schema(tool_name)
            if output_schema is not None:
                output_validation = self._policy_checker.check_output(
                    tool_name, result, output_schema, controls_active,
                )
                if not output_validation.valid:
                    self._logger.log("output_schema_warning", {
                        "tool": tool_name,
                        "reason": output_validation.reason,
                    })

            self._logger.log("tool_call_forwarded", {
                "tool": tool_name,
                "status": decision.status,
                "success": True,
                "transport": self._transport.name,
            })
            return {
                "status": decision.status,
                "decision": decision.to_dict(),
                "result": result,
            }
        except Exception as e:
            self._logger.log("tool_call_failed", {
                "tool": tool_name,
                "error": str(e),
                "transport": self._transport.name,
            })
            return {
                "status": "error",
                "decision": decision.to_dict(),
                "result": {
                    "content": [{"type": "text", "text": f"Error: {e}"}],
                    "isError": True,
                },
            }

    def _forward_call(self, tool_name: str, arguments: dict) -> Any:
        """Forward a tools/call via the configured downstream transport."""
        return self._transport.call_tool(tool_name, arguments)

    @property
    def logger(self) -> AuditLogger:
        return self._logger

    @property
    def policy_checker(self) -> PolicyChecker:
        return self._policy_checker

    @property
    def real_server_url(self) -> str:
        return self._real_server_url

    @property
    def tool_count(self) -> int:
        return len(self._tools)
