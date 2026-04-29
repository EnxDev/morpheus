# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Security

- **IBAC fail-open fix for non-English step names.** Steps whose names did not match
  the English action-prefix list (e.g., `borrar_registros`, `lösche_eintrag`) were
  inferred as the most permissive action `execute` and could be silently authorised
  by any deployment with a permissive `execute:*` allow tuple — bypassing
  `delete:*` denial tuples a security-conscious operator may have written.

  The fix changes the inference default in `morpheus/policies/ibac.py` to a sentinel
  `_UNKNOWN_ACTION = "unknown"` that does not match operator-declared action
  vocabularies, and removes the unconditional `("execute", step_name)` fallback
  in the IBAC candidate list. Wildcard tuples (`*:*`) are intentionally preserved.

  **This is a breaking change for deployments that rely on the implicit-execute
  fallback for non-English step names.** Affected steps must declare an explicit
  `requires:` field. Example migration:

  ```yaml
  # Before (relied on implicit inference)
  step: borrar_registros

  # After (option 1: explicit declaration)
  step: borrar_registros
  requires: "delete:records"

  # After (option 2: rename with English prefix)
  step: delete_records
  ```

  Surfaced by the multilingual analysis at `docs/multilingual-analysis.md` §2.6.

## [0.1.0-alpha] — 2026-03-28

### Added
- Dual-checkpoint pipeline (Control 1 + Control 2)
- IBAC authorization tuples
- Plan Review with step ordering validation
- Input sanitizer with Unicode normalization
- Session Guard with cross-iteration memory
- MCP Proxy with dynamic tool discovery
- LLM provider abstraction (OpenAI, Anthropic, Ollama)
- Python SDK with FastAPI middleware
- HR Assistant demo app
- 148 tests across 15 layers

### Known limitations
- No persistent audit log (in-memory only)
- No authentication / multi-user support
- No dashboard UI
- Local models (Ollama) have lower parsing accuracy
