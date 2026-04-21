# MCP SDK notes — Phase 2.0 reconnaissance

**Purpose:** verify the design doc's assumptions against the installed `mcp`
SDK (version 1.26.0) before writing any transport code. Scope is limited to the
four questions in the Phase 2.0 brief.

**Files inspected:**
- `mcp/client/streamable_http.py` — `StreamableHTTPTransport`, `streamable_http_client`
- `mcp/client/session.py` — `ClientSession` (`initialize`, `list_tools`, `call_tool`)
- `mcp/shared/session.py` — `BaseSession.send_request` (the request/response core)
- `mcp/shared/exceptions.py` — `McpError`
- `mcp/client/session_group.py` — canonical multi-session usage pattern
- `mcp/types.py` — error codes

---

## 1. Exception hierarchy on session loss

**Answer:** The single exception class the proxy needs to catch is
`mcp.shared.exceptions.McpError`. It carries an `ErrorData` payload whose
`.code` distinguishes the sub-cases.

- `mcp/shared/exceptions.py:8-18` defines `class McpError(Exception)` with an
  `error: ErrorData` attribute containing `.code`, `.message`, `.data`.
- `mcp/shared/session.py:305-306` is the single point where `BaseSession.send_request`
  converts a JSON-RPC error response into a raise: `raise McpError(response_or_error.error)`.
  Every path that ultimately surfaces an error to `send_request` flows through this.

**Session-loss signal:** on HTTP 404 from the downstream with a session header
(`mcp/client/streamable_http.py:350-356`) the client calls
`_send_session_terminated_error` (lines 510-522) which injects a
`JSONRPCError(code=32600, message="Session terminated")` into the read stream.
`send_request` picks it up and raises `McpError` with `error.code == 32600`.

**Connection-closed signal:** on stream teardown (network drop, server
shutdown), `mcp/shared/session.py:446-452` injects
`ErrorData(code=CONNECTION_CLOSED, message="Connection closed")` into every
outstanding response stream, surfacing as `McpError` with
`error.code == CONNECTION_CLOSED` (the integer constant is defined in
`mcp/types.py` — let the transport code import `types.CONNECTION_CLOSED`
rather than hardcode the number).

**Practical detection rule for the proxy:**

- `McpError` with `error.code == 32600` and `error.message == "Session terminated"`
  → session loss, eligible for one-shot re-init.
- `McpError` with `error.code == CONNECTION_CLOSED` → transport is dead,
  also eligible for one-shot re-init (and in that case we also need to
  re-open the `streamable_http_client` context manager, not just re-initialize).
- Any other `McpError` (wrong method, tool not found, tool errored) → surface
  to caller, no retry.

The "magic number" 32600 deserves a comment in the transport module because
the SDK does not export it as a named constant. Grep confirms it only appears
as a literal in `streamable_http.py:519`.

---

## 2. Session reuse idiom

**Answer:** the canonical SDK pattern is **one session held open by a context
manager for its entire usable lifetime**. You cannot call `ClientSession.initialize()`,
let the context close, and re-use the session later — closing the context
tears down the anyio task group, the memory streams, and the httpx client.

- `mcp/client/streamable_http.py:600-681`: `streamable_http_client` is an
  `@asynccontextmanager` that yields `(read_stream, write_stream,
  get_session_id)`. All resources are scoped to the `async with` body.
- `mcp/client/session.py:103-197`: `ClientSession` is a subclass of
  `BaseSession`, which is itself an async context manager
  (`mcp/shared/session.py:221-238` — `__aenter__` starts the receive loop,
  `__aexit__` cancels the task group and closes the exit stack).
- Canonical paired usage is in `mcp/client/session_group.py:321-344` — both
  context managers are entered onto an `AsyncExitStack`, then
  `await session.initialize()`, then the session is used. The stack is held
  for the lifetime of the session's usefulness.

**Implication for the Morpheus proxy (long-lived server):**

The proxy cannot just wrap each `call_tool` in an `async with` — that would
`initialize` on every call, which is precisely what the design doc says we
want to avoid. So the `StreamableHttpTransport` must:

1. Own a dedicated background event loop (running in its own thread, because
   FastAPI's sync endpoints run on the threadpool and we don't want the
   session coupled to per-request loops).
2. On first use, schedule a coroutine on that loop that enters an
   `AsyncExitStack`, enters `streamable_http_client`, enters `ClientSession`,
   awaits `initialize()`, and then **parks** waiting for shutdown or
   re-init. The stack stays open.
3. Route each `list_tools`/`call_tool` call from the proxy's caller thread
   as a coroutine submitted to that loop via `asyncio.run_coroutine_threadsafe`.
4. On shutdown, signal the parked coroutine to close the stack, terminating
   the session.

Using a per-transport event loop thread also sidesteps `asyncio.run`
re-entry problems in the sync test harness — each test can construct a
transport, use it synchronously, and close it.

**This matches the design doc's "one shared session per proxy" model**, but
the lifecycle work required is non-trivial. This is the biggest
implementation risk for Phase 2 Step 4.

---

## 3. Concurrency safety

**Answer:** the SDK has no explicit docstring contract. Reading the code:
**safe for concurrent `await`s from the same event loop, unsafe across
threads unless marshalled back onto the owning loop.**

- `mcp/shared/session.py:256-257`: `send_request` does
  `request_id = self._request_id; self._request_id = request_id + 1`.
  That is two Python operations separated by zero awaits, so on a single
  event loop they execute atomically (no coroutine switch can happen between
  them). No lock is needed. But on two threads this is a classic race on
  the counter.
- The per-request response stream is keyed by the unique request_id in
  `self._response_streams[request_id]`, so even if two coroutines concurrently
  await `send_request`, their responses do not cross-wire.
- There is no `asyncio.Lock`, `threading.Lock`, or docstring warning in
  either `ClientSession` or `BaseSession`.
- The streamable-HTTP writer (`post_writer`, lines 524-577) pulls messages
  off a single memory-object stream and spawns one task per request via
  `tg.start_soon` — so multiple in-flight requests are expected and handled.

**Conclusion for Morpheus:** because we are running the session on its own
event loop thread and marshalling calls in via
`asyncio.run_coroutine_threadsafe`, every `send_request` runs on the same
loop in a natural order. We do not need an extra lock in the proxy. I
considered flagging this as UNCLEAR and adding a defensive lock, but the
evidence is strong enough that a lock would be cargo-cult. **Not adding a
lock.** If Phase 3 integration tests turn up a race, we revisit.

---

## 4. Response handling — JSON vs SSE

**Answer:** **confirmed normalised.** The caller of `ClientSession.call_tool()`
/ `ClientSession.list_tools()` sees the same shape regardless of whether the
downstream responded with `application/json` or `text/event-stream`.

- `mcp/client/streamable_http.py:364-374`: in `_handle_post_request`, a
  content-type check routes the body to either `_handle_json_response` or
  `_handle_sse_response`.
- `_handle_json_response` (lines 376-395) reads the body, parses it as
  `JSONRPCMessage.model_validate_json(content)`, wraps it in `SessionMessage`,
  and sends it to `read_stream_writer`.
- `_handle_sse_response` (lines 397-435) iterates SSE events, extracts the
  `data:` field, parses each as `JSONRPCMessage.model_validate_json(sse.data)`,
  wraps in `SessionMessage`, and sends to the same `read_stream_writer`.
- Both paths converge on `SessionMessage(JSONRPCMessage(...))` in the read
  stream. The consumer (`BaseSession.send_request`) sees only
  `JSONRPCResponse | JSONRPCError` and has no awareness of whether the
  message arrived as JSON or SSE.

**The design doc's normalization assumption is correct.** No code in the
transport layer needs to branch on response content-type.

---

## Summary

| Assumption from design doc              | Verdict                             |
| --------------------------------------- | ----------------------------------- |
| Single exception to catch on errors     | ✅ `McpError` with `.error.code`    |
| Session loss is detectable              | ✅ code 32600 or CONNECTION_CLOSED  |
| One-session-per-proxy is SDK-idiomatic  | ✅ but CM must be held open         |
| SDK safe for concurrent awaits          | ✅ on single loop; no lock needed   |
| JSON vs SSE normalized by SDK           | ✅ confirmed                        |

**No design-doc assumption was falsified. Phase 2 implementation can
proceed without amending the design.**

**Lifecycle caveat for Phase 2 Step 4:** the `streamable_http_client` +
`ClientSession` pair is an async context manager that must be held open for
the session's lifetime. A naive "open on every call, close after" would
defeat session reuse; a naive "open once, use from any thread" would break
because the context is tied to the event loop that opened it. The
implementation must own a dedicated background event loop thread and
marshal sync calls onto it via `asyncio.run_coroutine_threadsafe`. This
is the bridging choice for Step 4 — `anyio.from_thread.run` requires a
running anyio loop on another thread, which is essentially the same
pattern. I'll use raw asyncio rather than anyio for the bridge because
the project already uses stdlib-only for the proxy's sync paths and
anyio.from_thread would require every call to go through a portal object
with the same setup cost.
