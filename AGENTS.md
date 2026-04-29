# AGENTS.md

## System Identity

Morpheus is a deterministic intent control layer that sits between user input and AI execution.

**Problem being solved:**
LLM agents accept raw user input and pass it directly to tools,
silently inventing missing parameters and executing actions without validation.

**What Morpheus adds:**
A domain-agnostic control layer that validates at two independent points:

- **Control 1** — what the user is asking, before it reaches the model
- **Control 2** — what the model is about to do, before it reaches the tools

Both controls can be enabled or disabled independently. Everything is always logged.

```
# Without Morpheus
User -> LLM -> calls tools freely -> executes

# With Morpheus
User -> [Control 1: is the intent clear and valid?]
     -> LLM
     -> [Control 2: is this action authorized and coherent?]
     -> executes (or is blocked)
```

---

## Core Principles

- **LLM proposes, system decides** — the model never chooses actions autonomously
- **Uncertainty must be explicit** — ambiguous fields are surfaced, not silently resolved
- **Confirmation before execution** — the system always shows the resolved intent before acting
- **All decisions must be explainable** — every action is traceable to a validated intent
- **Execution must be bounded** — timeouts, retries, and audit on every step
- **Domain-agnostic** — any domain can be registered; a generic Business Intelligence config ships as the default example

---

## Architecture

### Control 1 — Input Validation

Validates the user's intent before it reaches the model.

```
User Input (natural language)
  -> Sanitizer          (prompt injection defense)
  -> Parser             (LLM -> multi-hypothesis intent with confidence per field)
  -> Confidence Policy  (threshold check per field, domain-configurable)
  -> Validator          (schema enforcement + structural coherence)
  -> Clarifier          (bounded loop, max iterations configurable)
  -> Confirmation       (show resolved intent to user — mandatory)
  -> validated intent
```

### Control 2 — Action Validation (MCP Proxy)

Validates what the model is about to do before the tool executes.

```
LLM -> tools/call morpheus/[tool_name]
            |
       MorpheusProxy
         Level 1: deterministic checks (risk, rate limit, role, required fields)
         Level 2: LLM-assisted coherence check (optional)
            |
       approved  -> forwards to real_mcp_server/[tool_name]
       blocked   -> returns isError: true + reason to model
       bypassed  -> forwards + logs as deliberate bypass
```

The proxy is transparent to the model — it sees the same tool names and schemas.

### Control Toggles

Three independent toggles managed via `ControlManager` (`morpheus/controls.py`):

| Toggle               | Controls                         | Default |
| -------------------- | -------------------------------- | ------- |
| `input_validation`   | Control 1 (parsing + validation) | `true`  |
| `action_validation`  | Control 2 Level 1 (deterministic)| `true`  |
| `coherence_check`    | Control 2 Level 2 (LLM-assisted) | `true`  |

Every toggle change is logged in the audit trail with reason.

---

## Project Structure

```
morpheus/                          # Backend (Python)
  __init__.py                      # Package shim — exposes morpheus.X import paths
  main.py                          # FastAPI backend
  mcp_server.py                    # MCP server (stdio transport for desktop/IDE clients)
  controls.py                      # Control toggles manager
  audit/logger.py                  # Audit logging with pluggable sinks + secret redaction
  clarifier/clarifier.py           # Clarification logic + question generation
  decision_engine/engine.py        # Capability-based action selection + scoring
  domain/
    config.py                      # DomainConfig, FieldDefinition, CapabilityDefinition
    registry.py                    # DomainRegistry (register/get/list domains)
    default_bi.py                  # Default BI domain config
  execution/
    engine.py                      # Plan executor (timeout + retry)
    plan.py                        # Plan builder
    review.py                      # Plan review (structural + constraint + IBAC)
  intent/schema.py                 # DynamicIntent, Hypothesis (domain-agnostic)
  llm/
    provider.py                    # Abstract LLM provider + auto-detection
    anthropic.py                   # Anthropic provider (env: ANTHROPIC_API_KEY)
    openai.py                      # OpenAI provider (env: OPENAI_API_KEY)
    ollama.py                      # Ollama provider (local, no key)
  parser/
    parser.py                      # Query parser (LLM-assisted)
    sanitizer.py                   # Prompt injection defense
    coherence.py                   # Input/output coherence check
    session_guard.py               # Clarification anomaly detection
  policies/
    confidence_policy.py           # Low-confidence + ambiguity detection
    ibac.py                        # Intent-Based Access Control (authorization tuples)
  proxy/
    proxy_server.py                # MorpheusProxy (MCP proxy implementation)
    policy_checker.py              # Control 2: PolicyChecker (L1 + L2)
    discovery.py                   # Dynamic tool discovery from real MCP servers
    transport.py                   # Downstream transports: plain_jsonrpc + streamable_http
    upstream.py                    # Upstream MCP streamable-HTTP server endpoint (/mcp/)
    mcp_bridge.py                  # Standalone MCP proxy bridge (stdio transport)
    http_proxy.py                  # HTTP proxy service (REST + /mcp/ on one FastAPI app)
  sdk/
    client.py                      # Python HTTP client (MorpheusClient)
    types.py                       # Pydantic response models
    adapters/fastapi_middleware.py  # FastAPI middleware integration
  validator/validator.py           # Intent validation (deterministic + structural)
  tests/
    test_cases.py                  # Test cases
    mock_mcp_server.py             # Mock MCP server for proxy testing
    test_layer11_proxy_server.py   # Proxy server + discovery + listener API
    test_layer11b_streamable_http.py # Downstream streamable-HTTP transport
    test_layer11c_upstream_streamable.py # Upstream MCP /mcp/ endpoint

src/                               # Frontend (React 19 + TypeScript + Vite)
  App.tsx                          # Routes: / (Pipeline Tester), /config (Domain Configurator)
  components/
    QueryInput/                    # Query input + submit
    PipelineTracker/               # Animated pipeline step tracker
    IntentDisplay/                 # Per-field confidence bars
    ClarificationPanel/            # Bounded clarification loop
    ConfirmationStep/              # Mandatory intent confirmation
    AuditLog/                      # Event log, exportable as JSON
    DomainConfigurator/            # Domain config editor (fields, capabilities, prompts)
  hooks/
    usePipeline.ts                 # Pipeline state machine + API calls
    useDomains.ts                  # Domain management

docs/                              # Documentation
  api-reference.md
  architecture.md
  configuration.md
  mcp-proxy.md
  streamable-http-transport.md     # Downstream transport design
  streamable-http-upstream.md      # Upstream /mcp/ endpoint design
  multilingual-analysis.md         # Language-coupling audit
  roadmap.md
  sdk.md
  sdk-notes-phase2.md              # MCP SDK reconnaissance (frozen artifact)
  examples/
    basic_pipeline.py
    custom_domain.py
    fastapi_integration.py
    mcp_proxy_setup.py
```

---

## Intent Schema

Every field is a list of hypotheses, each with a confidence score.
The parser never returns a single truth — it returns candidates.

```python
@dataclass
class Hypothesis:
    value: str | None
    confidence: float  # 0.0 - 1.0

class DynamicIntent:
    """Domain-agnostic intent. Fields are defined by the domain config."""
    _fields: tuple[str, ...]
    _data: dict[str, list[Hypothesis]]
```

Fields, thresholds, weights, and priorities are all defined per domain via `DomainConfig`.

---

## Domain System

Domains are registered via code or HTTP API. Each domain defines:

- **Fields** — what the parser extracts (name, threshold, weight, priority, fallback question, examples)
- **Capabilities** — what actions are available (field weights, min score, match_fields)
- **Execution plans** — step sequences per action (type, timeout, retry)
- **Parser prompt** — domain-specific LLM prompt template
- **Clarification policy** — max iterations, priority order, fallback behavior

```python
from morpheus.domain.config import DomainConfig, FieldDefinition, CapabilityDefinition
from morpheus.domain.registry import DomainRegistry

config = DomainConfig(name="my_domain", ...)
DomainRegistry.register(config, default=True)
```

Or via API: `POST /api/domains/register`

### Semantic Action Matching (`match_fields`)

Each capability can declare `match_fields` — a map of field names to expected values. The decision engine uses these to select the right action:

```python
CapabilityDefinition(
    action="query_payroll",
    field_weights={"action_type": 1.0, "hr_category": 1.0, ...},
    match_fields={"action_type": "view", "hr_category": ["payroll", "salary"]},
)
```

- All resolved fields must match for the capability to be a candidate
- If no capability matches the intent → `action: null` (out of scope)
- No hardcoded logic — matching is driven entirely by domain configuration

The default domain is **Generic BI** (`morpheus/domain/default_bi.py`) with 6 fields (measure, time_range, dimension, filters, granularity, comparison) and 4 capabilities (query_chart, export_csv, save_dashboard, compare_periods).

---

## Control 2 — Policy Rules

The `PolicyChecker` (`morpheus/proxy/policy_checker.py`) enforces action-level policies in two levels.

### Level 1 — Deterministic

Risk classification via fnmatch patterns:

| Risk     | Patterns                                                              |
| -------- | --------------------------------------------------------------------- |
| `high`   | `delete_*`, `remove_*`, `drop_*`, `destroy_*`, `purge_*`             |
| `medium` | `send_*`, `create_*`, `update_*`, `write_*`, `post_*`, `approve_*`, `request_*`, `export_*` |
| `low`    | `get_*`, `list_*`, `read_*`, `fetch_*`, `search_*`, `query_*`, `view_*` |

Custom rules via `PolicyRule`:

```python
PolicyRule(
    tool_pattern="send_*",
    risk_level="medium",
    max_calls_per_session=10,
    blocked_for_roles=["viewer"],
    require_intent_field="measure",
)
```

### Level 2 — LLM Coherence Check

If Level 1 passes to Level 2 (medium/unknown risk with coherence_check enabled):

1. LLM evaluates semantic coherence between the validated intent and the tool arguments
2. Returns `coherence_score` (0.0 - 1.0)
3. Threshold decides (default 0.70) — the LLM never decides

---

## LLM Usage

The LLM is used in **three** controlled places. Everything else is deterministic Python.

| Component        | Purpose                                 | Fallback if unavailable         |
| ---------------- | --------------------------------------- | ------------------------------- |
| Parser           | Raw query -> structured JSON intent     | Empty intent (blocked)          |
| Clarifier        | Generate natural clarification question | Template-based question         |
| Coherence Check  | Score intent-action coherence (Control 2 L2) | Score 0.0 (safe default)  |

**LLM is explicitly NOT used for:** choosing actions, scoring capabilities, execution planning, validation logic, policy decisions.

### Provider Support

Configured via env vars. Auto-detects from available API keys.

| Provider  | Auth env var          | Model selection env var | Notes                  |
| --------- | --------------------- | ----------------------- | ---------------------- |
| Anthropic | `ANTHROPIC_API_KEY`   | `ANTHROPIC_MODEL`       | Remote, frontier-tier  |
| OpenAI    | `OPENAI_API_KEY`      | `OPENAI_MODEL`          | Remote, frontier-tier  |
| Ollama    | `OLLAMA_BASE_URL`     | `OLLAMA_MODEL`          | Local, no key required |

Specific model strings are not pinned in this document — each provider's
`<provider>_MODEL` env var defaults to the current stable model from
that provider, which evolves over time.

---

## API Endpoints

### Core Pipeline
| Method | Endpoint                  | Purpose                          |
| ------ | ------------------------- | -------------------------------- |
| POST   | `/api/parse`              | Parse query into intent          |
| POST   | `/api/clarify`            | Update intent with user answer   |
| POST   | `/api/decide`             | Select action + execute          |

### Domain Management
| Method | Endpoint                  | Purpose                          |
| ------ | ------------------------- | -------------------------------- |
| GET    | `/api/domains`            | List registered domains          |
| POST   | `/api/domains/register`   | Register new domain config       |
| DELETE | `/api/domains/{name}`     | Delete a registered domain       |

### Controls
| Method | Endpoint                  | Purpose                          |
| ------ | ------------------------- | -------------------------------- |
| GET    | `/api/controls`           | Get current control state        |
| POST   | `/api/controls`           | Update control toggles           |

### Audit
| Method | Endpoint                  | Purpose                          |
| ------ | ------------------------- | -------------------------------- |
| GET    | `/audit`                  | Get last N audit events          |
| GET    | `/audit/summary`          | Event type counts                |
| GET    | `/audit/export`           | Export full log (JSON/CSV)       |
| GET    | `/health`                 | Health check                     |

---

## MCP Server

Exposes the pipeline as MCP tools over the stdio transport for any
MCP-compliant desktop or IDE client (`morpheus/mcp_server.py`):

| Tool              | Purpose                                          |
| ----------------- | ------------------------------------------------ |
| `parse_query`     | Parse query, create session, return intent       |
| `clarify_field`   | Update field with user answer                    |
| `decide_action`   | Validate, select action, check Control 2, execute|
| `get_audit_log`   | Return recent audit events                       |

Session-based: `parse_query` creates a session, subsequent calls use `session_id`.

## MCP Proxy Bridge

Standalone MCP proxy (`morpheus/proxy/mcp_bridge.py`) that sits between an LLM client and a real MCP server:

```bash
python morpheus/proxy/mcp_bridge.py --real-server http://localhost:5010
```

Transparently proxies all discovered tools with policy enforcement. Additional tools:

| Tool                    | Purpose                                |
| ----------------------- | -------------------------------------- |
| `set_validated_intent`  | Set intent for coherence checking      |
| `get_proxy_status`      | Proxy status (tools, controls, intent) |
| `get_proxy_audit`       | Audit log                              |

---

## SDK

Python client for embedding Morpheus in existing applications (`morpheus/sdk/`):

```python
from morpheus.sdk.client import MorpheusClient

client = MorpheusClient("http://localhost:8000")
result = client.parse("show me revenue by region for Q1")
decision = client.decide(result.intent)
```

FastAPI middleware adapter available in `morpheus/sdk/adapters/fastapi_middleware.py`.

---

## Audit Trail

Every interaction is logged with full context via pluggable sinks.

**Sinks:** InMemory (default, 10K cap), Console (JSON stdout), File (JSONL with rotation), Composite.

**Event structure:**
```python
AuditEvent:
  timestamp, user, event_type, payload,
  decision,          # "approved" | "blocked" | "bypassed"
  level_1_result,    # {status, reason, risk_level, rule_applied}
  level_2_result,    # {coherence_score, reason, llm_used}
  controls_active,   # {input_validation, action_validation, coherence_check}
  policy_applied
```

**Automatic secret redaction:** API keys, tokens, connection strings, SSH keys, private IPs, home directory paths.

---

## Testing UI

A React interface in `src/` for interactive pipeline testing.

- Routes: `/` (Pipeline Tester), `/config` (Domain Configurator)
- Stack: React 19 + TypeScript + Vite + CSS Modules
- Works in mock mode (`VITE_MOCK_DATA=true`) or connected to FastAPI backend on port 8000

```bash
npm install && npm run dev    # http://localhost:5173
```

---

## Input Security

The sanitizer (`morpheus/parser/sanitizer.py`) defends against:

- Prompt injection (instruction override, role hijacking, admin mode)
- SQL injection (DROP, DELETE, UNION SELECT, shell metacharacters)
- XSS (script tags, event handlers, iframe/object injection)
- Unicode obfuscation (NFKC normalization, Cyrillic/Greek homoglyph mapping, zero-width char stripping)
- Structural attacks (code fences, oversized input, excessive line count)

3+ flags = blocked (never reaches LLM). 1-2 flags = suspicious (logged, app decides).

Patterns are tuned to avoid false positives on legitimate BI/HR queries (e.g. "billing system: Stripe" does not trigger `system:` detection).

The session guard (`morpheus/parser/session_guard.py`) detects clarification anomalies: circular references, conflicting answers, excessive iterations.

---

## Anti-Patterns

- LLM deciding which action to run
- Executing without user confirmation
- Silently using defaults for critical fields
- Skipping validation on high-confidence parses
- Storing session state in chat history
- LLM making policy decisions (it proposes scores, thresholds decide)

---

## Guiding Principle

We do not trust the model's interpretation.
We surface it, validate it, confirm it with the user,
then execute deterministically.
