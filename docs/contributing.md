# Contributing

## Development Setup

```bash
git clone https://github.com/EnxDev/morpheus.git
cd morpheus

# Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r morpheus/requirements.txt
pip install fastmcp

# Environment
cp morpheus/.env.example morpheus/.env

# Run the server. The provider is auto-detected from whichever API key
# is set in .env (OPENAI_API_KEY, ANTHROPIC_API_KEY) or falls back to a
# local Ollama install when no key is found.
cd morpheus
uvicorn main:app --reload --port 8000

# For local validation without API keys, use Ollama:
#   Set MORPHEUS_LLM_PROVIDER=ollama in .env
#   ollama pull <preferred-model> && ollama serve

# Frontend (optional)
cd ..
npm install
npm run dev
```

## Running Tests

```bash
cd morpheus

# Full test suite (219 tests across 15 layers)
python tests/run_all_tests.py

# E2E mock tests only (no LLM needed)
python tests/test_cases.py

# TypeScript check
cd ..
npm run typecheck
```

## Project Structure

- `morpheus/` — Main Python package
  - `llm/` — LLM provider abstraction (Ollama, OpenAI, Anthropic providers)
  - `parser/` — NL to structured intent (LLM)
  - `validator/` — Schema + LLM validation
  - `clarifier/` — Interactive field resolution (LLM)
  - `policies/` — Confidence thresholds, IBAC authorization tuples
  - `decision_engine/` — Deterministic action selection
  - `execution/` — Plan builder + executor
  - `proxy/` — MCP Proxy (Control 2): downstream transports + upstream MCP server endpoint
  - `audit/` — Audit logger with pluggable sinks
  - `domain/` — Domain-agnostic config system
  - `sdk/` — Python client + FastAPI middleware
  - `controls.py` — Independent control toggles
  - `main.py` — FastAPI server
  - `mcp_server.py` — MCP tools (stdio transport for desktop/IDE clients)
  - `tests/` — Test suite
- `src/` — React testing UI
- `docs/` — Documentation

## Code Style

- Python 3.11+ features (`str | None`, dataclasses, `from __future__ import annotations`)
- No unnecessary abstractions
- Deterministic behavior over LLM-dependent behavior
- Every decision must be auditable
- LLM proposes, thresholds decide — the LLM never makes the final call

## Pull Requests

1. Create a feature branch
2. Write tests for new functionality
3. Run `python tests/run_all_tests.py` and ensure all tests pass
4. Run `npm run typecheck` if frontend was changed
5. Keep changes focused and minimal
6. Update documentation if APIs change
