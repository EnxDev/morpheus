# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `DownstreamTransport` abstraction in `morpheus/proxy/transport.py` with `PlainJsonRpcTransport` and `StreamableHttpTransport` implementations.
- `--transport {plain_jsonrpc,streamable_http}` flag and `MORPHEUS_DOWNSTREAM_TRANSPORT` env var on the HTTP proxy; default remains `plain_jsonrpc`.
- One-shot session re-init on session-loss for the streamable-HTTP transport; best-effort session `DELETE` on proxy shutdown.
- `mcp>=1.26,<2` promoted to a direct, pinned dependency.
- Test layer 11b covering transport selection, plain JSON-RPC regression, streamable-HTTP against FastMCP, session lifecycle, and a guard against SDK drift on the session-terminated error code.

### Changed
- `ToolDiscovery` and `MorpheusProxy` now accept either a URL or a pre-built `DownstreamTransport`. URL-accepting constructors remain backwards compatible.
- `tool_call_forwarded` and `tool_call_failed` audit events include a `transport` field. Additive; no existing field changed.
- New audit event `downstream_session_reinitialized` emitted when the streamable-HTTP transport recovers from a lost session.

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
