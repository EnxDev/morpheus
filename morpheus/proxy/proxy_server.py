"""MorpheusProxy — MCP server that dynamically mirrors real tools.

The LLM calls morpheus/[tool_name], Morpheus checks policy,
then either forwards to real_server/[tool_name] or blocks + logs.
Transparent to the calling LLM — same tool names and schemas.
"""

from __future__ import annotations

from typing import Any

import requests

from audit.logger import AuditLogger
from proxy.discovery import ToolDiscovery, ToolDefinition
from proxy.policy_checker import PolicyChecker, ActionDecision


class MorpheusProxy:
    """MCP proxy that discovers tools from a real server and intercepts all calls.

    Usage:
        proxy = MorpheusProxy("http://localhost:5010")
        tools = proxy.get_proxied_tools()       # tools discovered from real server
        result = proxy.call_tool("send_email", {"to": "x@y.com", "body": "hi"}, intent)
    """

    def __init__(
        self,
        real_server_url: str,
        policy_checker: PolicyChecker | None = None,
        logger: AuditLogger | None = None,
    ) -> None:
        self._real_server_url = real_server_url.rstrip("/")
        self._logger = logger or AuditLogger()
        self._discovery = ToolDiscovery(self._real_server_url)
        self._policy_checker = policy_checker or PolicyChecker()

        # Discover tools from the real server
        self._tools: dict[str, ToolDefinition] = {}
        self._discover_tools()

        # Register for dynamic updates
        self._discovery.on_change(self._on_tools_changed)

    def _discover_tools(self) -> None:
        """Connect to real server and dynamically register discovered tools."""
        discovered = self._discovery.discover()
        self._tools.clear()
        for tool in discovered:
            self._tools[tool.name] = tool

        # Update policy checker with known tool names
        self._policy_checker.set_known_tools(set(self._tools.keys()))

        self._logger.log("tools_discovered", {
            "server_url": self._real_server_url,
            "tool_count": len(discovered),
            "tools": [t.name for t in discovered],
        })

    def _on_tools_changed(self) -> None:
        """Called when tools/list_changed notification is received."""
        self._logger.log("tools_list_changed", {
            "server_url": self._real_server_url,
        })
        self._discover_tools()

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
        """Forward a tools/call to the real MCP server via JSON-RPC."""
        payload = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
            "id": 1,
        }
        response = requests.post(self._real_server_url, json=payload, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("result", data)

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
