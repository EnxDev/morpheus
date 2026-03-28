"""Morpheus MCP Bridge — exposes proxied tools as a real MCP server.

This is the runtime component of Control 2. It sits between the LLM client
(Claude Desktop, Cursor, VS Code) and the real MCP tool server.

The LLM sees the same tools as the real server, but every call is intercepted
by the proxy's policy checker before being forwarded.

Usage:
    cd morpheus && python proxy/mcp_bridge.py --real-server http://localhost:5010

Or configure in Claude Desktop:
    {
      "mcpServers": {
        "morpheus-proxy": {
          "command": "python",
          "args": ["/path/to/morpheus/proxy/mcp_bridge.py", "--real-server", "http://localhost:5010"]
        }
      }
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastmcp import FastMCP

from audit.logger import AuditLogger
from controls import ControlManager
from proxy.proxy_server import MorpheusProxy
from proxy.policy_checker import PolicyChecker


# ── Response size guard ───────────────────────────────────────────────────────
# Protects LLM context window from oversized tool responses.
# ~25k tokens ≈ 100KB of text. A get_* LOW risk tool returning a full DB dump
# would bypass all policy checks but poison the context window.
MAX_RESPONSE_CHARS = 100_000  # ~25k tokens
RESPONSE_WARNING_RATIO = 0.8  # warn at 80%


# ── Session state ────────────────────────────────────────────────────────────

# The validated intent from Control 1. Set via set_validated_intent tool
# or programmatically before the LLM starts calling tools.
_validated_intent: dict | None = None


def _build_bridge(real_server_url: str) -> tuple[FastMCP, MorpheusProxy, ControlManager]:
    """Build the MCP bridge: discover tools, create proxy, register as MCP tools."""

    logger = AuditLogger()
    control_manager = ControlManager(logger=logger)
    policy_checker = PolicyChecker()

    # Connect to real server and discover tools
    proxy = MorpheusProxy(
        real_server_url=real_server_url,
        policy_checker=policy_checker,
        logger=logger,
    )

    tools = proxy.get_proxied_tools()
    tool_names = [t["name"] for t in tools]

    mcp = FastMCP(
        "Morpheus Proxy",
        instructions=(
            "This server proxies tools from a real MCP server through Morpheus Control 2.\n"
            "Every tool call is validated against policies before being forwarded.\n"
            f"Available tools: {', '.join(tool_names)}\n\n"
            "High-risk tools (delete_*, remove_*, etc.) are blocked by default.\n"
            "Medium-risk tools (send_*, create_*, etc.) require coherence check.\n"
            "Low-risk tools (get_*, read_*, etc.) are auto-approved."
        ),
    )

    # ── Register each discovered tool as an MCP tool ─────────────────────

    for tool_def in tools:
        _register_proxied_tool(mcp, proxy, control_manager, tool_def)

    # ── Management tools ─────────────────────────────────────────────────

    @mcp.tool()
    def set_validated_intent(intent_json: str) -> dict:
        """Set the validated user intent for coherence checking.

        Call this BEFORE calling any proxied tools. The intent is used by
        Control 2 Level 2 (coherence check) to verify that tool call
        parameters are consistent with what the user actually requested.

        Pass the intent as a JSON string, e.g.:
        {"measure": "revenue", "time_range": "Q1 2025", "dimension": "by region"}
        """
        global _validated_intent
        try:
            _validated_intent = json.loads(intent_json)
            logger.log("intent_set_for_proxy", {"intent": _validated_intent})
            return {"status": "ok", "intent": _validated_intent}
        except json.JSONDecodeError as e:
            return {"error": f"Invalid JSON: {e}"}

    @mcp.tool()
    def get_proxy_status() -> dict:
        """Get the current proxy status: discovered tools, controls, and active intent."""
        controls = control_manager.get_controls()
        return {
            "real_server": proxy.real_server_url,
            "discovered_tools": tool_names,
            "tool_count": proxy.tool_count,
            "controls": controls.to_dict(),
            "validated_intent_set": _validated_intent is not None,
        }

    @mcp.tool()
    def get_proxy_audit(last_n: int = 20) -> dict:
        """Get recent proxy audit log entries."""
        return {
            "events": proxy.logger.last(last_n),
            "summary": proxy.logger.summary(),
        }

    return mcp, proxy, control_manager


def _register_proxied_tool(
    mcp: FastMCP,
    proxy: MorpheusProxy,
    control_manager: ControlManager,
    tool_def: dict,
) -> None:
    """Register a single discovered tool as an MCP tool on the bridge.

    The tool function intercepts the call, runs it through the proxy
    (policy check + forward), and returns the result.
    """
    name = tool_def["name"]
    description = tool_def.get("description", "")
    # Prefix description so the LLM knows it's proxied
    proxied_description = f"[Proxied via Morpheus] {description}"

    # We need a closure to capture the tool name.
    # fastmcp doesn't support **kwargs, so we accept a single JSON string
    # parameter and parse it. The LLM sees the tool description with the
    # real inputSchema documented, so it knows what to send.
    def make_handler(tool_name: str):
        def handler(arguments_json: str = "{}") -> str:
            """Call this tool with a JSON string of arguments."""
            try:
                args = json.loads(arguments_json) if arguments_json else {}
            except json.JSONDecodeError:
                return f"ERROR: Invalid JSON arguments: {arguments_json[:100]}"

            controls = control_manager.get_controls()
            result = proxy.call_tool(
                tool_name=tool_name,
                arguments=args,
                original_intent=_validated_intent,
                controls_active=controls.to_dict(),
            )

            status = result["status"]
            decision = result.get("decision", {})

            if status == "blocked":
                reason = decision.get("reason", "Blocked by Morpheus policy")
                return f"BLOCKED: {reason}"

            if status == "bypassed":
                inner = result.get("result", {})
                content = _extract_content(inner)
                content = _enforce_response_limit(content, tool_name, proxy.logger)
                return f"[BYPASSED] {content}"

            if status == "error":
                inner = result.get("result", {})
                content = _extract_content(inner)
                return f"ERROR: {content}"

            # Approved — return the real tool result
            inner = result.get("result", {})
            content = _extract_content(inner)
            content = _enforce_response_limit(content, tool_name, proxy.logger)
            return content

        handler.__name__ = tool_name
        handler.__doc__ = f"{proxied_description}\n\nExpected arguments (JSON): {json.dumps(tool_def.get('inputSchema', {}), indent=2)}"
        return handler

    mcp.tool()(make_handler(name))


def _extract_content(result: Any) -> str:
    """Extract text content from an MCP tool result."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        # MCP format: {"content": [{"type": "text", "text": "..."}]}
        content_list = result.get("content", [])
        if isinstance(content_list, list):
            texts = [c.get("text", "") for c in content_list if isinstance(c, dict)]
            if texts:
                return "\n".join(texts)
        # Structured content
        if "structuredContent" in result:
            return json.dumps(result["structuredContent"])
        # Fallback: serialize the whole thing
        return json.dumps(result)
    return str(result)


def _enforce_response_limit(content: str, tool_name: str, logger: Any) -> str:
    """Truncate oversized tool responses to protect the LLM context window.

    A get_* LOW risk tool returning a full database dump would bypass all
    policy checks but poison the context window with 50k+ tokens.
    """
    length = len(content)

    if length > MAX_RESPONSE_CHARS:
        logger.log("response_truncated", {
            "tool": tool_name,
            "original_chars": length,
            "limit": MAX_RESPONSE_CHARS,
        })
        truncated = content[:MAX_RESPONSE_CHARS]
        return (
            f"{truncated}\n\n"
            f"[TRUNCATED: Response was {length:,} chars, limit is {MAX_RESPONSE_CHARS:,}. "
            f"Try adding filters or reducing scope.]"
        )

    if length > int(MAX_RESPONSE_CHARS * RESPONSE_WARNING_RATIO):
        logger.log("response_size_warning", {
            "tool": tool_name,
            "chars": length,
            "limit": MAX_RESPONSE_CHARS,
            "usage_pct": round(length / MAX_RESPONSE_CHARS * 100),
        })

    return content


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Morpheus MCP Proxy Bridge")
    parser.add_argument(
        "--real-server",
        default=os.environ.get("MORPHEUS_REAL_SERVER", "http://localhost:5010"),
        help="URL of the real MCP server to proxy (default: $MORPHEUS_REAL_SERVER or localhost:5010)",
    )
    args = parser.parse_args()

    mcp, proxy, _ = _build_bridge(args.real_server)

    print(f"Morpheus Proxy Bridge starting...", file=sys.stderr)
    print(f"  Real server: {args.real_server}", file=sys.stderr)
    print(f"  Discovered {proxy.tool_count} tools", file=sys.stderr)

    mcp.run()


if __name__ == "__main__":
    main()
