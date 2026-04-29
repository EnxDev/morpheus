# Configuration

## Domain Configuration

Morpheus is domain-agnostic. Each domain defines its own fields, thresholds, capabilities, and execution plans.

### Registering a Domain

```python
from morpheus.domain.config import DomainConfig, FieldDefinition, CapabilityDefinition
from morpheus.domain.registry import DomainRegistry

config = DomainConfig(
    name="my_domain",
    domain_description="My custom domain",
    fields=[
        FieldDefinition(
            name="action",
            label="Action",
            description="What the user wants to do",
            threshold=0.8,
            weight=0.5,
            priority=1,
            fallback_question="What action would you like to perform?",
            examples=["create report", "send email", "export data"],
        ),
        # ... more fields
    ],
    capabilities=[
        CapabilityDefinition(
            action="create_report",
            field_weights={"action": 1.0, "scope": 0.5},
            min_score=0.6,
            match_fields={"action": "create_report", "scope": ["quarterly", "annual"]},
        ),
    ],
    # match_fields: optional dict[str, str | list[str]]
    # Constrains which field values a capability matches.
    # If a field value is a string, the intent field must match exactly.
    # If a field value is a list, the intent field must match one of the values.
    # Fields not listed in match_fields are not constrained.

    execution_plans={
        "create_report": [
            {"step": "build_query", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "execute", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
        ],
    },
)

DomainRegistry.register(config, default=True)
```

### Via API

```bash
curl -X POST http://localhost:8000/api/domains/register \
  -H "Content-Type: application/json" \
  -d '{"config": {...}}'
```

## Control Toggles

Three independent controls can be toggled at runtime:

| Control | Default | What it does when disabled |
|---------|---------|---------------------------|
| `input_validation` | `true` | Skips validation + confidence check, logs as "bypassed" |
| `action_validation` | `true` | Skips proxy policy check (L1), logs as "bypassed" |
| `coherence_check` | `true` | Skips LLM coherence check (L2), logs as "bypassed" |

```bash
# Get current state
curl http://localhost:8000/api/controls

# Disable input validation
curl -X POST http://localhost:8000/api/controls \
  -H "Content-Type: application/json" \
  -d '{"input_validation": false, "reason": "testing raw pipeline"}'

# Disable coherence check only (keep deterministic L1 active)
curl -X POST http://localhost:8000/api/controls \
  -H "Content-Type: application/json" \
  -d '{"coherence_check": false, "reason": "reduce latency"}'
```

Every control state change is logged to the audit trail with who, when, previous state, and new state.

## Audit Configuration

Set `MORPHEUS_AUDIT_FILE` to enable file-based audit logging:

```bash
export MORPHEUS_AUDIT_FILE=/var/log/morpheus/audit.jsonl
uvicorn main:app
```

The file sink:
- Creates the file if it doesn't exist
- Appends atomically (one JSON line per event)
- Rotates at 10MB (keeps 5 archive files)
- Survives server restarts (append mode)

## HTTP Proxy Configuration

The HTTP proxy at `morpheus/proxy/http_proxy.py` exposes the proprietary
REST surface (`/proxy/*`) and the MCP streamable-HTTP server endpoint
(`/mcp/`) on the same FastAPI app. It speaks two downstream wire formats
to the real MCP server it sits in front of.

### CLI flags

| Flag | Description | Default |
|---|---|---|
| `--real-server URL` | Downstream MCP server URL | `http://localhost:5010` |
| `--port N` | Port for the HTTP proxy | `5020` |
| `--transport {plain_jsonrpc,streamable_http}` | Downstream wire format | `plain_jsonrpc` |
| `--mcp-path PATH` | Path to mount the upstream MCP server endpoint | `/mcp/` |
| `--mcp-stateless` | Run the upstream MCP server in stateless mode | off (stateful) |
| `--no-admin-mcp-tools` | Suppress the three management tools on the MCP surface | off (exposed) |

### Environment variables

Each CLI flag has an env-var fallback. The CLI value wins if both are set.

| Env var | Type | Default | Equivalent flag |
|---|---|---|---|
| `MORPHEUS_REAL_SERVER` | URL string | `http://localhost:5010` | `--real-server` |
| `MORPHEUS_PROXY_PORT` | integer | `5020` | `--port` |
| `MORPHEUS_PROXY_KEY` | string | empty (dev mode) | — (auth header value) |
| `MORPHEUS_DOWNSTREAM_TRANSPORT` | `plain_jsonrpc` \| `streamable_http` | `plain_jsonrpc` | `--transport` |
| `MORPHEUS_MCP_PATH` | path | `/mcp/` | `--mcp-path` |
| `MORPHEUS_MCP_STATELESS` | truthy (`1`/`true`/`yes`/`on`) | empty (stateful) | `--mcp-stateless` |
| `MORPHEUS_NO_ADMIN_MCP_TOOLS` | truthy (`1`/`true`/`yes`/`on`) | empty (exposed) | `--no-admin-mcp-tools` |

When `MORPHEUS_PROXY_KEY` is empty, both REST and the upstream `/mcp/`
endpoint are open (dev mode). When set, both require either
`X-Proxy-Key: <key>` or `Authorization: Bearer <key>` on every request;
mismatched keys produce HTTP 401 before the request reaches the proxy
or the MCP sub-app. Auth parity between the two surfaces is enforced by
construction — there is no combination where REST and MCP disagree on
whether the proxy is authenticated.

### Examples

```bash
# Dev mode (no key), default downstream, default upstream MCP path
python proxy/http_proxy.py --real-server http://localhost:5010

# Production-style: keyed auth, streamable-HTTP downstream, custom MCP mount path
MORPHEUS_PROXY_KEY=<secret> \
  python proxy/http_proxy.py \
  --real-server http://localhost:5008/mcp \
  --transport streamable_http \
  --mcp-path /agents/mcp/

# Suppress the three admin MCP tools (proxy-only client surface)
python proxy/http_proxy.py --real-server http://localhost:5010 --no-admin-mcp-tools
```

See [MCP Proxy](mcp-proxy.md) for the proxy's architecture and
[streamable-http-upstream.md](streamable-http-upstream.md) for the
upstream endpoint design.

## MCP Proxy Risk Patterns

Default risk classification patterns:

| Risk Level | Patterns |
|-----------|----------|
| High | `delete_*`, `remove_*`, `drop_*`, `destroy_*`, `purge_*` |
| Medium | `send_*`, `create_*`, `update_*`, `write_*`, `post_*`, `approve_*`, `request_*`, `export_*` |
| Low | `get_*`, `list_*`, `read_*`, `fetch_*`, `search_*`, `query_*`, `view_*` |

Custom policies can override defaults. See [MCP Proxy](mcp-proxy.md) for details.

## IBAC — Authorization Tuples

Each capability can declare `authorized_tuples` — templates that generate authorization grants from the validated intent:

```python
CapabilityDefinition(
    action="query_payroll",
    field_weights={"action_type": 1.0, "hr_category": 1.0},
    min_score=0.6,
    authorized_tuples=[
        {"action": "read", "resource": "payroll:{data_subject}", "required_fields": ["data_subject"]},
        {"action": "read", "resource": "employee:{data_subject}", "required_fields": ["data_subject"]},
    ],
)
```

At runtime, `{data_subject}` is resolved from the validated intent. If the field has low confidence, the tuple is NOT generated and the step is blocked.

### Sensitive Resources

Resources that should never be covered by wildcards:

```python
from morpheus.policies.ibac import DeterministicEvaluator

evaluator = DeterministicEvaluator(
    sensitive_resources={"payroll:ceo", "payroll:all_employees", "data:sensitive"}
)
```

With `read:payroll:*` as a tuple:
- `payroll:self` → allowed (not sensitive)
- `payroll:ceo` → **blocked** (sensitive, wildcard not accepted)
- `payroll:ceo` with exact tuple `read:payroll:ceo` → allowed

### Replacing the Evaluator

The `TupleEvaluator` is a Protocol. For enterprise:

```python
# Default (MIT, no dependencies)
evaluator = DeterministicEvaluator()

# Enterprise (same interface, different backend)
evaluator = CedarAdapter(endpoint="...")   # future
evaluator = OPAAdapter(endpoint="...")     # future
```

## Plan Review Constraints

The `PlanReviewer` validates execution plans before they run:

```python
from morpheus.execution.review import PlanReviewer

reviewer = PlanReviewer(constraints={
    "max_total_timeout_ms": 60000,      # 1 minute max
    "max_side_effect_steps": 3,         # max irreversible steps
    "max_retries_per_step": 5,          # prevent retry storms
    "max_plan_steps": 10,               # max steps in a plan
    "require_pure_before_side_effect": True,  # verify before acting
})
```
