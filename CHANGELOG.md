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

### Added — upstream MCP streamable-HTTP server endpoint

- New `/mcp/` endpoint mounted on the existing FastAPI HTTP-proxy app, speaking the MCP spec's streamable-HTTP transport (`initialize` handshake, `Mcp-Session-Id` headers, JSON-or-SSE responses, `tools/list_changed` notifications). MCP-compliant HTTP clients can now connect to Morpheus directly; tool calls flow through the same Control 2 pipeline as the existing REST surface.
- New module `morpheus/proxy/upstream.py` owning FastMCP construction, tool registration, the auth middleware, and the lifespan helper.
- Three new CLI flags on `proxy/http_proxy.py`: `--mcp-path` (default `/mcp/`), `--mcp-stateless` (default off), `--no-admin-mcp-tools` (default off — admin tools exposed). Each has a corresponding env var: `MORPHEUS_MCP_PATH`, `MORPHEUS_MCP_STATELESS`, `MORPHEUS_NO_ADMIN_MCP_TOOLS`.
- Three management tools (`set_validated_intent`, `get_proxy_status`, `get_proxy_audit`) exposed on the upstream MCP surface alongside the proxied catalogue, mirroring the stdio bridge's management surface. Sit behind the same `MORPHEUS_PROXY_KEY` check as the REST endpoints. Suppressible via `--no-admin-mcp-tools`.
- New public API on `MorpheusProxy`: `add_tools_changed_listener(callback)` lets external subscribers (the upstream module being the first user) react to downstream `tools/list_changed` events. Listener exceptions are caught and emitted as a `tools_changed_listener_failed` audit event.
- Test layer 11c (`tests/test_layer11c_upstream_streamable.py`) covering: lifespan + basic wiring (Group A), auth middleware (Group B), tool dispatch through Control 2 (Group C), dynamic tool sync (Group D), stateful vs stateless (Group E), management-tools toggle (Group F), concurrent session safety (Group G). Plus a regression guard that fails loudly if the FastMCP lifespan threading is ever removed.

### Changed — upstream-related

- `MorpheusProxy.__init__` now accepts an optional `add_tools_changed_listener` registration via the public method described above; the existing internal `_on_tools_changed` continues to work unchanged.
- An `UpstreamMcp` instance is constructed during `init_proxy` and mounted at the configured `--mcp-path` with an ASGI auth middleware enforcing the same `MORPHEUS_PROXY_KEY` rules as the REST endpoints. The mount uses FastMCP's internal `path="/"` plus the FastAPI mount prefix to avoid the path-doubling that arises when both layers carry the same `/mcp/` prefix; documented inline in `proxy/upstream.py` and in the streamable-http-upstream design doc's implementation addendum.

### Added — packaging

- `morpheus/__init__.py` shim turns the directory into a regular package and provides the project docstring + `__version__`. Enables documented `from morpheus.proxy import …`, `from morpheus.policies.ibac import …`, `from morpheus.sdk import …` imports without changing how tests run from inside the directory.

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
