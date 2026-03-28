# Getting Started

## Prerequisites

- Python 3.11+
- An OpenAI API key (default provider) **or** [Ollama](https://ollama.com) for local validation
- Node.js 20+ (for the testing UI, optional)

## Installation

```bash
git clone https://github.com/EnxDev/morpheus.git
cd intent-guard

# Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r morpheus/requirements.txt
pip install fastmcp   # for MCP server support

# Environment config
cp morpheus/.env.example morpheus/.env
# Edit morpheus/.env — add your OPENAI_API_KEY or ANTHROPIC_API_KEY
# Provider is auto-detected from which key is present. No key = Ollama (local)
```

## Running the Server

```bash
# Start the backend
cd morpheus
uvicorn main:app --reload --port 8000

# If using Ollama instead of OpenAI:
#   ollama pull mistral
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

| Variable | Default | Description |
|----------|---------|-------------|
| `MORPHEUS_LLM_PROVIDER` | auto-detect | Auto: `OPENAI_API_KEY` → openai, `ANTHROPIC_API_KEY` → anthropic, fallback → ollama |
| `OPENAI_API_KEY` | (none) | Required when provider is `openai` |
| `OPENAI_MODEL` | `gpt-4o` | Model for OpenAI provider |
| `ANTHROPIC_API_KEY` | (none) | Required when provider is `anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-20250514` | Model for Anthropic provider |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL (local only) |
| `OLLAMA_MODEL` | `mistral` | Model for Ollama provider (local only) |
| `ANTHROPIC_MAX_TOKENS` | `1024` | Max tokens for Anthropic provider |
| `LLM_PROVIDER` | (none) | Alias for `MORPHEUS_LLM_PROVIDER` |
| `MORPHEUS_AUDIT_FILE` | (none) | Path for JSONL audit file |
| `VITE_MOCK_DATA` | `true` | Set to `false` to connect UI to real backend |

## Running Tests

```bash
cd morpheus
python tests/run_all_tests.py
```

The test suite covers 15 layers (148 tests): schema, domain, confidence, sanitizer, coherence, session guard, validator, clarifier, decision engine, execution, audit, controls, proxy, MCP server, IBAC, and FastAPI endpoints.

## Next Steps

- [Architecture](architecture.md) — understand the two controls
- [Configuration](configuration.md) — customize domains and policies
- [API Reference](api-reference.md) — all REST endpoints
- [MCP Proxy](mcp-proxy.md) — set up Control 2 (action validation)
- [SDK](sdk.md) — Python client and FastAPI middleware
