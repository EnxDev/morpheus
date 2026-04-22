# MCP Proxy (Control 2)

## Overview

The MCP Proxy sits between the LLM and real MCP tool servers. It dynamically discovers tools from the real server and intercepts every call to check policy and coherence.

```
LLM -> morpheus/send_email(params)
  -> Proxy intercepts
  -> policy_checker.check_action(tool_name, params, intent)
  -> approved  -> forwards to real_server/send_email(params)
  -> blocked   -> returns error + reason
  -> bypassed  -> forwards + logs as bypass
```

## Setup

The Morpheus project runs from inside the `morpheus/` package directory
(`cd morpheus && python …`), so the top-level Python package name for
imports is `proxy`, not `morpheus.proxy`.

```python
from proxy import MorpheusProxy  # re-exported from proxy.proxy_server

# Connect to a real MCP server. A URL string defaults to the
# plain_jsonrpc transport — see "Downstream transports" below.
proxy = MorpheusProxy("http://localhost:5010")

# See what tools were discovered
tools = proxy.get_proxied_tools()
for tool in tools:
    print(f"  {tool['name']}: {tool['description']}")

# Call a tool through the proxy
result = proxy.call_tool(
    "send_email",
    {"to": "sales@company.com", "subject": "Q1 Report", "body": "..."},
    original_intent={"to": "sales@company.com", "subject": "Q1 Report"},
)
print(result["status"])  # "approved", "blocked", or "bypassed"
```

## Downstream transports

The proxy speaks two downstream wire formats, selected at construction
time or — when running the HTTP proxy as a process — via a CLI flag or
env var.

| Transport | Identifier | Use when |
|---|---|---|
| Morpheus JSON-RPC over HTTP | `plain_jsonrpc` (default) | The downstream is a simple server that accepts a bare JSON-RPC POST (the HR demo, `tests/mock_mcp_server.py`, other Morpheus-style servers). |
| MCP streamable-HTTP | `streamable_http` | The downstream implements the MCP spec's streamable-HTTP transport (FastMCP in streamable mode, Superset MCP, the official MCP reference servers). Includes `initialize` + `Mcp-Session-Id` + `Accept: text/event-stream`. |

On the `streamable_http` path the transport holds a single session open
for the proxy's lifetime, reuses it across calls, re-initializes once
transparently on session loss, and issues a best-effort `DELETE` on
shutdown. Every tool-call audit event records which transport was used.

### Selecting a transport — HTTP proxy

```bash
# Plain JSON-RPC (default — no flag needed)
python proxy/http_proxy.py --real-server http://localhost:5010

# Streamable HTTP (for FastMCP-style servers)
python proxy/http_proxy.py \
  --real-server http://localhost:5008/mcp \
  --transport streamable_http

# Or via env var
MORPHEUS_DOWNSTREAM_TRANSPORT=streamable_http \
  python proxy/http_proxy.py --real-server http://localhost:5008/mcp
```

### Selecting a transport — programmatic

The `MorpheusProxy` constructor accepts either a URL (implicitly
`plain_jsonrpc`, for backwards compatibility) or a pre-built
`DownstreamTransport` instance:

```python
from proxy import MorpheusProxy
from proxy.transport import StreamableHttpTransport

transport = StreamableHttpTransport("http://localhost:5008/mcp")
proxy = MorpheusProxy(real_server_or_transport=transport)
# ... use the proxy normally ...
transport.close()  # best-effort session terminate
```

See [streamable-http-transport.md](streamable-http-transport.md) for the
design rationale, the session lifecycle model, and the SDK-compatibility
notes.

## Dynamic Discovery

The proxy calls `tools/list` on the real MCP server when initialized
(via whichever transport is in use). No tools are hardcoded. You can
refresh at any time:

```python
proxy.refresh_tools()
```

## Risk Classification

Tools are classified using a hybrid approach (name patterns → description keywords → unknown):

| Risk | Name Patterns | Description Keywords | Default Behavior |
|------|--------------|---------------------|-----------------|
| High | `delete_*`, `remove_*`, `drop_*`, `destroy_*`, `purge_*` | "permanently", "irreversible", "destructive", "cannot be undone" | Blocked (requires confirmation) |
| Medium | `send_*`, `create_*`, `update_*`, `write_*`, `post_*`, `approve_*`, `request_*`, `export_*` | "create", "modify", "publish", "send", "deploy" | Coherence check required |
| Low | `get_*`, `list_*`, `read_*`, `fetch_*`, `search_*`, `query_*`, `view_*` | "read-only", "retrieve", "idempotent" | Auto-approved |
| Unknown | No match on name or description | — | Coherence check + confirmation |

Name patterns have highest priority. Tool descriptions and input schemas are
obtained from MCP discovery and passed to the policy checker automatically.

## Coherence Check

Compares tool call parameters against the validated user intent.

Three defense layers protect the coherence check from prompt injection:

| Layer | Type | Effect |
|-------|------|--------|
| **D1 — Argument sanitization** | Deterministic | Scans parameter values for injection patterns. Blocks before LLM. |
| **D2 — Schema pre-validation** | Deterministic | Validates arguments against tool's `inputSchema`. Blocks before LLM. |
| **D3 — Hardened prompt** | Probabilistic | Structural delimiters + anti-injection framing. Defense-in-depth only. |

D1 and D2 are the real security guarantees. D3 depends on the LLM model and should not be relied upon alone.

```python
# Intent says audience = "team_sales"
# Tool call sends to "everyone@company.com" -> BLOCKED (incoherent)

# Intent says scope = "Q1 2025"
# Tool call uses date_range = "2020-2024" -> BLOCKED (incoherent)

# Tool params contain "ignore all previous instructions" -> BLOCKED by D1 (LLM never called)
# Tool params fail inputSchema validation -> BLOCKED by D2 (LLM never called)
```

## Custom Policies

```python
from proxy.policy_checker import PolicyChecker, PolicyRule

checker = PolicyChecker()
checker.add_rule(PolicyRule(
    tool_pattern="send_*",
    risk_level="medium",
    max_calls_per_session=10,
    blocked_for_roles=["viewer"],
    require_intent_field="measure",
))
```

Available `PolicyRule` fields:
- `tool_pattern` — fnmatch pattern (e.g., `"send_*"`)
- `risk_level` — `"high"`, `"medium"`, `"low"`
- `blocked_for_roles` — list of roles that cannot use this tool
- `require_intent_field` — block if this field is missing from the intent
- `requires_confirmation` — force confirmation for this tool (default for high risk)
- `auto_approve` — skip all checks (default for low risk)
- `max_calls_per_session` — rate limit per session

## IBAC Integration

When IBAC tuples are configured for a capability, the proxy verifies each tool call against the authorization set. A `get_weather` LOW risk tool with a `read:data:*` tuple passes, but a `send_email` without a `write:email` tuple is blocked even if it passes risk classification.

Sensitive resources (e.g., `payroll:ceo`) require exact tuple match — wildcards are blocked:

```python
from policies.ibac import DeterministicEvaluator

evaluator = DeterministicEvaluator(
    sensitive_resources={"payroll:ceo", "data:all_employees"}
)
```

## Disabling Control 2

```python
result = proxy.call_tool(
    "delete_repo",
    {"repo_name": "old-repo"},
    controls_active={"action_validation": False, "input_validation": True, "coherence_check": True},
)
# result["status"] == "bypassed" (forwarded but logged)
```
