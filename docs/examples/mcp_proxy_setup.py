"""Set up the MCP Proxy between an LLM and real tool servers.

Requires: a real MCP server running (or the mock server from tests).

Run from project root:
    python docs/examples/mcp_proxy_setup.py

Or start the mock server first:
    cd morpheus && python tests/mock_mcp_server.py
"""

import sys
from pathlib import Path

# Add morpheus to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "morpheus"))

from proxy import MorpheusProxy
from proxy.policy_checker import PolicyRule

# 1. Create a proxy pointing to a real MCP server
proxy = MorpheusProxy("http://localhost:5010")

# 2. See what tools were discovered
print("Discovered tools:")
for tool in proxy.get_proxied_tools():
    print(f"  {tool['name']}: {tool['description']}")

# 3. Add a custom policy
proxy.policy_checker.add_rule(PolicyRule(
    tool_pattern="send_*",
    risk_level="medium",
    max_calls_per_session=5,
))

# 4. Call a low-risk tool (auto-approved)
result = proxy.call_tool("get_weather", {"location": "Rome"})
print(f"\nLow-risk call: {result['status']}")

# 5. Call a high-risk tool (blocked)
result = proxy.call_tool(
    "delete_repo",
    {"repo_name": "important-project"},
)
print(f"High-risk call: {result['status']} - {result['decision']['reason']}")

# 6. Call a medium-risk tool with intent for coherence check
result = proxy.call_tool(
    "send_email",
    {"to": "sales@company.com", "subject": "Q1 Report", "body": "See attached."},
    original_intent={"measure": "revenue", "time_range": "Q1 2025"},
)
print(f"Medium-risk call: {result['status']}")

# 7. Bypass mode (action_validation disabled)
result = proxy.call_tool(
    "delete_repo",
    {"repo_name": "old-repo"},
    controls_active={"input_validation": True, "action_validation": False, "coherence_check": True},
)
print(f"Bypass mode: {result['status']}")

# 8. Check audit log
print(f"\nAudit trail ({len(proxy.logger.get_log())} events):")
for event in proxy.logger.get_log():
    et = event["event_type"]
    tool = event.get("payload", {}).get("tool", "")
    status = event.get("payload", {}).get("status", "")
    print(f"  [{et}] {tool} {status}")
