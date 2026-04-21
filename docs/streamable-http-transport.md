# Streamable-HTTP Transport for the Morpheus Proxy

**Status:** design (Phase 1). Not yet implemented.
**Branch:** `feat/streamable-http-downstream`
**Scope:** the downstream leg of the Morpheus HTTP Proxy only. The `/proxy/*`
REST surface, Control 1, IBAC, Plan Review, and the stdio `mcp_bridge.py` are
untouched.

## 1. Motivation

The Morpheus HTTP proxy currently speaks a Morpheus-specific JSON-RPC-over-HTTP
dialect to downstream MCP servers: a single synchronous `POST` of a JSON-RPC
envelope with a fixed `"id": 1`, no session negotiation, no `Accept:
text/event-stream`, no `initialize` handshake. This works against the project's
own demo servers (e.g. the HR `hr_mcp_server.py`) but does **not** work against
MCP servers that implement the official streamable-HTTP transport from the MCP
spec (2025-11-25), which requires:

- An `initialize` handshake that returns a session ID
- An `Mcp-Session-Id` header on all subsequent requests
- `Accept: application/json, text/event-stream` on responses that may be
  streamed as Server-Sent Events
- Correct handling of both JSON and SSE response bodies
- Support for `202 Accepted` on notifications with no body

A concrete real-world target is Superset's FastMCP server, which refuses the
current hand-rolled call path. The goal of this feature is to let the Morpheus
proxy interoperate transparently with such servers while preserving byte-exact
behaviour for existing users pointing at demo-style servers.

## 2. Design principles (in priority order)

1. **Backward compatibility is non-negotiable.** Users pointing
   `--real-server` at a `hr_mcp_server.py`-style server must see zero behaviour
   change on the default code path. The existing Layer 11 tests are the
   acceptance bar.
2. **Explicit over implicit.** Transport selection is a deliberate
   configuration choice, not a probe. Users know what their downstream
   server speaks.
3. **SDK over hand-rolled.** Use the official `mcp` Python SDK rather than
   re-implementing session headers, SSE parsing, and 202-Accepted semantics.
   The MCP spec has enough edge cases that spec drift is the likely failure
   mode of a hand-rolled implementation.
4. **The public `/proxy/*` HTTP surface does not change.** This feature is
   an internal-only change to how the proxy talks to its downstream.
5. **Every decision is auditable.** Which transport was used for a given
   tool call must be visible in the audit log, not inferred after the fact.

## 3. Terminology

The existing hand-rolled transport is called **`plain_jsonrpc`** in code and
configuration, not `plain`. This is honest: it is not a spec-compliant "plain
HTTP MCP" mode (no such mode is defined in the spec), it is a Morpheus-custom
JSON-RPC-over-HTTP dialect that happens to work against simple servers that
accept a bare JSON body on `POST /`.

The new transport is called **`streamable_http`**, matching the MCP spec's
naming.

## 4. Architecture: transport abstraction

A new module, `morpheus/proxy/transport.py`, introduces a `DownstreamTransport`
abstraction with two implementations: `PlainJsonRpcTransport` and
`StreamableHttpTransport`. `ToolDiscovery` and `MorpheusProxy` depend on the
abstraction and no longer know the wire format. This keeps the diff to
`discovery.py` and `proxy_server.py` small and localises the new SDK
dependency to one file.

The abstraction exposes exactly two operations the proxy needs today:
list-tools and call-tool. It does not attempt to model the full MCP client —
anything the proxy doesn't use today stays out of the abstraction.

The implementation details (method signatures, async boundaries, error types)
are a Phase 2 concern. This doc fixes the shape, not the shape's edges.

## 5. Transport selection

### 5.1. The decision

Transport is selected **explicitly** via configuration, with
`plain_jsonrpc` as the default.

| Source                            | Value                                  | Notes                                    |
| --------------------------------- | -------------------------------------- | ---------------------------------------- |
| CLI flag                          | `--transport plain_jsonrpc \| streamable_http` | Highest priority                  |
| Env var                           | `MORPHEUS_DOWNSTREAM_TRANSPORT`        | Used when CLI flag absent                |
| Default                           | `plain_jsonrpc`                        | Preserves existing behaviour             |

An unrecognised value is a hard startup failure — the proxy logs the accepted
values and exits non-zero. The proxy does not silently fall back.

### 5.2. Options considered and rejected

- **URL heuristic** (path ending in `/mcp` → streamable-http). Rejected:
  there is no convention that servers actually follow. FastMCP defaults
  to `/mcp/` but is configurable; the HR demo uses `/`. Heuristics that work
  80% of the time generate bugs in the other 20%.
- **Probe-based auto-detection** (try `initialize`, fall back on failure).
  Rejected for v1 on three grounds:
  1. Ambiguous failure signals. A 404 on `initialize` could mean "wrong
     transport" or "wrong path" or "server is down"; a 500 could mean
     "server bug with streamable-http" that we'd then incorrectly demote
     to plain_jsonrpc and silently lose reliable behaviour.
  2. Every startup pays the probe cost, and the result may be cached
     incorrectly if the downstream server changes behind the proxy.
  3. It hides a transport bug behind a silent fallback. Explicit is safer
     for a security-adjacent component.
  Considered, **deferred**: a future `--transport auto` mode could be added
  in a later feature once there is operational demand. This design does not
  preclude that addition.
- **Per-tool transport selection.** Rejected: there is only one downstream
  server per proxy instance; mixing transports to one server is not a real
  use case.

### 5.3. Why default to `plain_jsonrpc`

Every existing user of this proxy is pointing it at a server that speaks the
current dialect. Changing the default would silently break them on upgrade.
New users targeting streamable-HTTP servers must opt in explicitly — the
opt-in is one flag, which is a trivial cost compared to a silent regression.

## 6. Session lifecycle (streamable-HTTP only)

### 6.1. One session per proxy instance

A `StreamableHttpTransport` instance holds a single MCP session opened lazily
on first use and reused across concurrent proxy calls. Rationale:

- The MCP spec permits session reuse; the SDK is built around it.
- The proxy's workload is "many calls to one downstream server per boot";
  this is exactly the case session reuse is designed for.
- One-session-per-call would pay the `initialize` round-trip on every
  `/proxy/call`, which is both slow and spammy in downstream logs.

Concurrency model: the SDK's session is safe to use from multiple awaiting
callers. The proxy's existing concurrency is driven by FastAPI/uvicorn,
which runs each request on the event loop; a single shared session is the
correct fit.

### 6.2. Session loss detection and one-shot re-init

Session loss signals the proxy recognises:

- HTTP `404` on a request that carries `Mcp-Session-Id` — the server has
  forgotten the session.
- An SDK-level error indicating the session is no longer valid (exact
  exception type is a Phase 2 detail).
- An explicit `Mcp-Session-Id` mismatch from the server.

On detection, the proxy performs **one** re-initialize attempt silently and
retries the original operation. A second failure surfaces to the caller as a
normal error — the proxy does not loop. Rationale: one retry covers the
common case (downstream restart, session TTL expiry) without masking a
genuinely broken downstream behind an infinite loop.

Re-init is not logged as a failure at info level, but it **is** logged as a
distinct audit event (`downstream_session_reinitialized`) so operators can
see churn.

### 6.3. Proxy shutdown

On clean shutdown (SIGTERM, uvicorn lifespan shutdown), the proxy attempts a
best-effort session termination against the downstream. Failure to terminate
is logged but does not block shutdown — the proxy does not wait on a
potentially-dead downstream to clean up its bookkeeping. Rationale: the
downstream's session will expire on its own TTL; we just try to be polite.

## 7. Error semantics

The proxy's existing audit-log statuses are `approved`, `blocked`, `bypassed`,
and `error` (from [morpheus/proxy/proxy_server.py:206-223](../morpheus/proxy/proxy_server.py#L206-L223)
and [http_proxy.py:145-150](../morpheus/proxy/http_proxy.py#L145-L150)). The
streamable-HTTP transport does not add new statuses. Mapping:

- **Policy decisions** (`approved`, `blocked`, `bypassed`) are made by
  `PolicyChecker` before the transport is touched. Transport selection
  does not influence them.
- **Downstream errors** (connection refused, 5xx, session re-init exhausted,
  SSE parse error) map to the existing `error` status, with the existing
  `{"isError": true, "content": [{"type": "text", "text": "Error: ..."}]}`
  shape. The caller sees the same thing they see today.
- **Tool-level errors** returned by the downstream (MCP's `{"isError":
  true, ...}` inside `result`) pass through unchanged — the proxy does not
  re-interpret them. This matches current behaviour.

### 7.1. Audit-log additions

Every tool call's existing `tool_call_forwarded` or `tool_call_failed` event
gains a `transport` field (`"plain_jsonrpc"` or `"streamable_http"`). A new
event type `downstream_session_reinitialized` is emitted when the
one-shot retry fires. No existing event shapes change — only additive fields.

## 8. Concurrency

- **`plain_jsonrpc`**: unchanged. Each `_forward_call` is an independent
  blocking `requests.post`. Concurrency is bounded by FastAPI's threadpool.
- **`streamable_http`**: a single shared session, used concurrently. The
  SDK's client handles the read/write serialisation over the underlying
  transport. The proxy does not add its own lock around the session.

An edge case worth calling out: the current codebase's `_forward_call` is
sync (uses `requests`). The SDK's streamable-HTTP client is async. The
transport abstraction will expose an interface that works for both; the
sync-vs-async bridging is a Phase 2 implementation detail (likely
`anyio.from_thread.run` or equivalent, but not decided here).

## 9. Backward compatibility

The following invariants must hold after this feature lands:

1. Running the proxy with **no new flags or env vars** produces byte-identical
   behaviour to the current main branch against the HR demo MCP server and
   the in-tree `tests/mock_mcp_server.py`.
2. The Layer 11 test suite (`tests/test_layer11_proxy_server.py`) passes
   unchanged.
3. The `/proxy/call`, `/proxy/tools`, `/proxy/status`, `/proxy/intent`,
   `/proxy/audit` request and response shapes are bit-for-bit identical.
4. The `mcp_bridge.py` stdio path is not touched and continues to work.
5. The out-of-scope bugs noted in Phase 0 (`_validated_intent` global, the
   `0.0.0.0` default bind, and the empty `MORPHEUS_PROXY_KEY` dev mode) are
   **not** fixed in this feature. They remain separate issues.

## 10. Dependencies

`mcp>=1.26,<2` is promoted from transitive (currently pulled in by
`fastmcp==3.1.1`) to a **direct, pinned dependency** of Morpheus in
`morpheus/requirements.txt`. Two reasons:

- It is load-bearing for this feature. Transitive dependencies can disappear
  when upstreams change their own dependencies — relying on `fastmcp` to keep
  pulling `mcp` in is fragile.
- The upper bound (`<2`) is a **deliberate guard** against a future MCP SDK
  v2 release introducing breaking changes to the streamable-HTTP client API.
  If v2 ships, the upgrade will be an explicit decision, not a silent `pip
  install` side-effect.

No other dependencies are added. Python 3.10+ is already required.

## 11. Test plan

The existing test harness is pure-Python sync asserts with a `harness.run(id,
desc, fn)` shape (see [morpheus/tests/harness.py](../morpheus/tests/harness.py)).
**This feature does not introduce `pytest` or `pytest-asyncio`** — that would
be a test-infra change out of scope here. Async operations in new tests will
be wrapped in `asyncio.run(...)` inside sync `fn` bodies. This is ugly but
minimal.

If Phase 2 finds the SDK's streamable-HTTP client cannot be cleanly wrapped
this way (for example, it holds an open event loop across calls that breaks
`asyncio.run` re-entry), **implementation stops and the question is raised**
before any change to the harness.

### 11.1. Regression coverage

- The existing Layer 11 tests stay as-is. They become the regression suite
  for the `plain_jsonrpc` path. They must pass unchanged.
- One new test confirms the **default transport** (no flag, no env) still
  routes through `PlainJsonRpcTransport` against the existing
  [tests/mock_mcp_server.py](../morpheus/tests/mock_mcp_server.py) mock.

### 11.2. New coverage

A new test layer (e.g. Layer 11b) covers:

- Unit: transport selection from CLI flag and env var, including the
  "unknown value → hard failure" path.
- Unit: `StreamableHttpTransport` against a mock streamable-HTTP server
  stood up in-process. The mock is either (a) a FastMCP instance configured
  for streamable-HTTP, or (b) an HTTP server we write that implements the
  minimum spec surface the SDK needs. FastMCP is preferred (we already
  depend on it) unless it proves too heavy to start in a test thread.
- Unit: one-shot session re-init on simulated `404 session-not-found`.
- Unit: audit log contains the `transport` field on forwarded calls.
- Integration: a real FastMCP server in streamable-HTTP mode on a loopback
  port, with `tools/list` and `tools/call` round-tripping through
  `MorpheusProxy`. This is the closest analogue to the Superset target.

All new tests must pass without requiring external services.

## 12. Non-goals (explicit)

- **Auto-detection of transport.** Considered, deferred. Not in v1.
- **Stdio transport changes.** `mcp_bridge.py` is untouched.
- **Changes to the `/proxy/*` REST API.** Out of scope.
- **Changes to Control 1, IBAC, Plan Review, Decision Engine.** Out of scope.
- **Fixing the known `_validated_intent` global bug.** Tempting, but
  separate issue.
- **Fixing the `0.0.0.0` default bind and empty `MORPHEUS_PROXY_KEY` dev
  mode.** Tempting, but separate issue.
- **OAuth / auth negotiation on the downstream leg.** The MCP SDK supports
  it, but no current user needs it, and designing for it widens the blast
  radius of this feature.

## 13. Open questions flagged for Phase 2

- **Async/sync bridge choice.** `anyio.from_thread.run` vs a per-transport
  event loop running in a background thread vs something else. Phase 2
  decides based on what survives Layer 11 regression testing.
- **How the SDK surfaces session-loss.** The design here assumes detectable
  exceptions / HTTP status codes; the exact mapping is a Phase 2
  verification step against SDK 1.26.0 source.
- **Whether the mock streamable-HTTP server in tests is FastMCP-backed or
  hand-rolled.** Defaulting to FastMCP; fall back to hand-rolled only if
  FastMCP startup is too slow or too stateful for the test harness.

## 14. Summary of decisions

| Decision                          | Choice                                           |
| --------------------------------- | ------------------------------------------------ |
| New module                        | `morpheus/proxy/transport.py`                    |
| Abstraction                       | `DownstreamTransport` interface                  |
| Implementations                   | `PlainJsonRpcTransport`, `StreamableHttpTransport` |
| Transport IDs                     | `plain_jsonrpc`, `streamable_http`               |
| Selection                         | Explicit flag / env, default `plain_jsonrpc`     |
| Auto-detection                    | Deferred, not v1                                 |
| SDK                               | `mcp>=1.26,<2`, direct dependency                |
| Session lifecycle                 | One shared session per proxy, lazy init          |
| Session loss                      | One-shot re-init, then surface error             |
| Shutdown                          | Best-effort terminate, don't block               |
| REST API surface                  | Unchanged                                        |
| Audit shape                       | Additive only (`transport` field, new event)     |
| Test framework                    | No pytest. Sync asserts + `asyncio.run`          |
| Backward compatibility            | Byte-identical on default code path              |
