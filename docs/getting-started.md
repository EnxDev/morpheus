# Getting Started

## Prerequisites

- Python 3.11+
- An API key for a supported remote provider (`OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) **or** [Ollama](https://ollama.com) for local validation
- Node.js 20+ (for the testing UI, optional)

## Installation

```bash
git clone https://github.com/EnxDev/morpheus.git
cd morpheus

# Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r morpheus/requirements.txt
pip install fastmcp   # for MCP server support

# Environment config
cp morpheus/.env.example morpheus/.env
# Edit morpheus/.env — set OPENAI_API_KEY, ANTHROPIC_API_KEY, or use Ollama (no key)
# Provider is auto-detected from which key is present. No key = Ollama (local)
```

## Running the Server

```bash
# Start the backend
cd morpheus
uvicorn main:app --reload --port 8000

# If using a local Ollama provider:
#   ollama pull <preferred-model>
#   ollama serve
```

The API is now available at `http://localhost:8000`.

## First Query

```bash
curl -X POST http://localhost:8000/api/parse \
  -H "Content-Type: application/json" \
  -d '{"query": "Show me revenue by region for Q1 2025"}'
```

Response:

```json
{
  "intent": {
    "measure": [{"value": "revenue", "confidence": 0.95}],
    "dimension": [{"value": "by region", "confidence": 0.88}],
    "time_range": [{"value": "Q1 2025", "confidence": 0.96}],
    "filters": [{"value": null, "confidence": 0.1}],
    "granularity": [{"value": null, "confidence": 0.1}],
    "comparison": [{"value": null, "confidence": 0.1}]
  },
  "low_confidence": ["filters", "granularity", "comparison"],
  "suspicious": false,
  "sanitizer_flags": [],
  "valid": true,
  "errors": []
}
```

## Using the Python SDK

```python
from morpheus.sdk import MorpheusClient

client = MorpheusClient()

# Parse a query
result = client.parse("Show me revenue by region for Q1 2025")
print(result.intent)
print(result.low_confidence)

# Clarify a field
updated = client.clarify(result.intent, "filters", "online channel only")
print(updated.intent)

# Decide what action to take
decision = client.decide(updated.intent)
print(decision.action, decision.score)

# Check controls
controls = client.get_controls()
print(controls)

# Toggle controls
client.set_controls(action_validation=False, reason="testing")

# Audit
events = client.get_audit(last_n=10)
summary = client.get_audit_summary()
```

## Testing UI (optional)

```bash
# From project root
npm install
npm run dev
# Opens at http://localhost:5173
```

The UI runs in mock mode by default. Set `VITE_MOCK_DATA=false` in the root `.env` to connect to the real backend.

## Environment Variables

### LLM provider selection

| Variable | Default | Description |
|----------|---------|-------------|
| `MORPHEUS_LLM_PROVIDER` | auto-detect | Auto: `OPENAI_API_KEY` → openai, `ANTHROPIC_API_KEY` → anthropic, fallback → ollama |
| `LLM_PROVIDER` | (none) | Alias for `MORPHEUS_LLM_PROVIDER` |
| `OPENAI_API_KEY` | (none) | Required when provider is `openai` |
| `OPENAI_MODEL` | provider-default | Specific model selection for the OpenAI provider |
| `ANTHROPIC_API_KEY` | (none) | Required when provider is `anthropic` |
| `ANTHROPIC_MODEL` | provider-default | Specific model selection for the Anthropic provider |
| `ANTHROPIC_MAX_TOKENS` | `1024` | Max tokens for the Anthropic provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (local only) |
| `OLLAMA_MODEL` | provider-default | Specific model selection for the Ollama provider |

### HTTP proxy configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MORPHEUS_REAL_SERVER` | `http://localhost:5010` | Downstream MCP server URL |
| `MORPHEUS_PROXY_PORT` | `5020` | Port for the HTTP proxy |
| `MORPHEUS_PROXY_KEY` | (empty — open) | Proxy auth key; when set, both REST and `/mcp/` require it |
| `MORPHEUS_DOWNSTREAM_TRANSPORT` | `plain_jsonrpc` | `plain_jsonrpc` or `streamable_http` |
| `MORPHEUS_MCP_PATH` | `/mcp/` | Mount path for the upstream MCP streamable-HTTP endpoint |
| `MORPHEUS_MCP_STATELESS` | (empty — stateful) | Truthy → stateless mode (each POST is independent) |
| `MORPHEUS_NO_ADMIN_MCP_TOOLS` | (empty — exposed) | Truthy → suppress the three management MCP tools |

### Other

| Variable | Default | Description |
|----------|---------|-------------|
| `MORPHEUS_AUDIT_FILE` | (none) | Path for JSONL audit file (file sink with rotation) |
| `VITE_MOCK_DATA` | `true` | Set to `false` to connect UI to real backend |

See [Configuration](configuration.md#http-proxy-configuration) for the
matching CLI flags and example invocations.

## Running Tests

```bash
cd morpheus
python tests/run_all_tests.py
```

The test suite covers 15 layers (219 tests): schema, domain, confidence, sanitizer, coherence, session guard, validator, clarifier, decision engine, execution, audit, controls, proxy (server + downstream transports + upstream MCP endpoint), MCP server, IBAC, and FastAPI endpoints.

## Next Steps

- [Architecture](architecture.md) — understand the two controls
- [Configuration](configuration.md) — customize domains, policies, and HTTP proxy flags
- [API Reference](api-reference.md) — all REST endpoints
- [MCP Proxy](mcp-proxy.md) — set up Control 2 (action validation), with both the downstream transport and the upstream MCP server endpoint
- [Streamable-HTTP downstream transport](streamable-http-transport.md) — design rationale for talking streamable-HTTP to backend MCP servers
- [Streamable-HTTP upstream MCP endpoint](streamable-http-upstream.md) — design rationale for the `/mcp/` server endpoint
- [Multilingual support analysis](multilingual-analysis.md) — language-coupling audit and roadmap
- [SDK](sdk.md) — Python client and FastAPI middleware
