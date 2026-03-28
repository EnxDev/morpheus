# Contributing

## Development Setup

```bash
git clone https://github.com/EnxDev/morpheus.git
cd intent-guard

# Python backend
python -m venv .venv
source .venv/bin/activate
pip install -r morpheus/requirements.txt
pip install fastmcp

# Environment
cp morpheus/.env.example morpheus/.env

# Run the server (uses OpenAI by default — set OPENAI_API_KEY in .env)
cd morpheus
uvicorn main:app --reload --port 8000

# For local validation without API keys, use Ollama instead:
#   Set MORPHEUS_LLM_PROVIDER=ollama in .env
#   ollama pull mistral && ollama serve

# Frontend (optional)
cd ..
npm install
npm run dev
```

## Running Tests

```bash
cd morpheus

# Full test suite (148 tests across 15 layers)
python tests/run_all_tests.py

# E2E mock tests only (no LLM needed)
python tests/test_cases.py

# TypeScript check
cd ..
npm run typecheck
```

## Project Structure

- `morpheus/` — Main Python package
  - `llm/` — LLM provider abstraction (Ollama, OpenAI, Anthropic)
  - `parser/` — NL to structured intent (LLM)
  - `validator/` — Schema + LLM validation
  - `clarifier/` — Interactive field resolution (LLM)
  - `policies/` — Confidence thresholds
  - `decision_engine/` — Deterministic action selection
  - `execution/` — Plan builder + executor
  - `proxy/` — MCP Proxy (Control 2)
  - `audit/` — Audit logger with pluggable sinks
  - `domain/` — Domain-agnostic config system
  - `sdk/` — Python client + FastAPI middleware
  - `controls.py` — Independent control toggles
  - `main.py` — FastAPI server
  - `mcp_server.py` — MCP tools for Claude Desktop/VS Code
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
