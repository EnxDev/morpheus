# Streamable-HTTP Upstream MCP Endpoint for the Morpheus Proxy

**Branch:** `feat/streamable-http-upstream`
**Sibling design doc (downstream side):** [streamable-http-transport.md](./streamable-http-transport.md)
**Scope:** the upstream (client-facing) leg of the Morpheus HTTP Proxy. The
proprietary `/proxy/*` REST surface, Control 1, IBAC, Plan Review, the stdio
`mcp_bridge.py`, and the existing downstream transport abstraction are
untouched.

## 1. Status

Designed in Phase 1, implementation pending. No production code changes have
landed for this feature yet — only this document.

## 2. Motivation

Today, Morpheus's HTTP proxy exposes proprietary REST endpoints under
`/proxy/*` (`/proxy/call`, `/proxy/tools`, `/proxy/status`, `/proxy/intent`,
`/proxy/audit`). These work, but they are not the MCP wire protocol. Native
MCP clients — applications that speak the MCP spec over HTTP — cannot
connect to Morpheus over HTTP. The only MCP-speaking endpoint Morpheus
exposes today is `morpheus/proxy/mcp_bridge.py`, and that is stdio-only.
Anyone wanting to put Morpheus in front of a real MCP backend over HTTP
either has to translate at the client (rewriting calls into Morpheus's REST
shape) or stand up a separate stdio bridge per client process.

This feature closes that gap. Morpheus's HTTP proxy gains a native MCP
streamable-HTTP server endpoint, exposed at `/mcp/` on the same FastAPI
app and the same port. Any MCP client that speaks streamable-HTTP — the
spec's HTTP transport — can connect to Morpheus directly and see what
looks like a normal MCP server: `initialize`, `tools/list`, `tools/call`,
session IDs, `tools/list_changed` notifications, all of it.

The symmetry with the downstream work is the point. Where
`feat/streamable-http-downstream` taught Morpheus to *speak* streamable-HTTP
to backend MCP servers, this feature teaches Morpheus to *expose*
streamable-HTTP to client-facing connections. With both sides in place, the
proxy becomes a transparent MCP sidecar: clients see the same tool names,
descriptions, and schemas as the real backend, while every `tools/call`
flows through Control 2's policy checker, IBAC evaluator, and audit log
before reaching the backend. Zero downstream code changes, zero client
code changes, full policy enforcement at the MCP boundary.

The value proposition is the same as the proxy's overall value
proposition, but now realised over the protocol clients already speak:
**policy enforcement at the MCP boundary, with the proxy invisible to both
sides.**

## 3. Architecture

```
                 MCP Client (HTTP)
                        │
                        │  MCP streamable-HTTP
                        │  (initialize → Mcp-Session-Id → SSE / JSON)
                        ▼
        ┌──────────────────────────────────────────┐
        │  Morpheus HTTP Proxy on :5020 (FastAPI)  │
        │                                          │
        │   ┌─ /mcp/    ── NEW: streamable-HTTP MCP server
        │   │              (mounts a FastMCP ASGI sub-app;
        │   │               tool catalogue is synced live
        │   │               from MorpheusProxy.get_proxied_tools.
        │   │               Every tools/call →
        │   │               MorpheusProxy.call_tool)
        │   │
        │   └─ /proxy/* ── existing REST endpoints, unchanged
        │
        └──────────────────────────────────────────┘
                        │
                        │  MCP streamable-HTTP via
                        │  StreamableHttpTransport (Phase 2 of
                        │  feat/streamable-http-downstream)
                        ▼
                 Downstream MCP server
```

The shape is one FastAPI app with two mount points. The existing
`/proxy/*` endpoints stay where they are. The new endpoint is a
FastMCP-backed ASGI sub-app mounted at `/mcp/`. Every `tools/call` the MCP
endpoint receives is dispatched into `MorpheusProxy.call_tool` —
**identical** to the path REST traffic takes through `POST /proxy/call`.
There is no second policy code path, no parallel Control 2 implementation,
no bypass.

Lifespan wiring is the one non-obvious bit (see §8). FastAPI's `lifespan=`
parameter is set to thread the FastMCP sub-app's lifespan context, so the
SDK's `StreamableHTTPSessionManager.run()` is properly entered at app
startup and cancelled at shutdown. Without that wiring, requests to
`/mcp/` fail with `"Task group is not initialized"`.

The dynamic tool catalogue is the second key piece. At construction time,
`MorpheusProxy.get_proxied_tools()` returns the discovered downstream
tools, and the upstream module registers each one with FastMCP via
`add_tool`. When the downstream emits `tools/list_changed`, Morpheus's
existing `MorpheusProxy._on_tools_changed` callback fires; the upstream
module re-syncs by calling `add_tool` for new tools and `remove_tool` for
removed tools. Active client sessions stay alive throughout, and FastMCP
emits the corresponding `tools/list_changed` notification to its connected
MCP clients automatically.

## 4. Locked design decisions

These six decisions came out of the Phase 0 capability tests and open
questions. They are the contract Phase 2 will follow literally.

### 4.1. Strategy — S1: mount FastMCP at `/mcp/` on the existing FastAPI app

The Phase 0 reconnaissance compared two strategies: S1 mounts the FastMCP
ASGI sub-app on the existing FastAPI app (single uvicorn process), S2 runs
FastMCP in a dedicated background thread reusing the dedicated-loop
pattern from `StreamableHttpTransport`. **S1 wins.**

A live test confirmed FastMCP's `http_app(transport="streamable-http")`
returns a real Starlette ASGI app, that it mounts cleanly into FastAPI,
that lifespan threads through, and that runtime `add_tool`/`remove_tool`
calls take effect mid-flight. Given that, S2 buys nothing concrete: it
adds a thread, a second lifecycle, and (if exposed externally) a second
port, with no compensating capability. S1 is one process, one port, one
auth surface, and a smaller diff.

### 4.2. Auth — same `MORPHEUS_PROXY_KEY` mechanism as REST, applied via ASGI middleware

The new endpoint reuses the existing proxy-key check. A small ASGI
middleware in front of the mounted MCP sub-app extracts `X-Proxy-Key` or
`Authorization: Bearer …`, applies the same logic as
[http_proxy.py:90-96](../morpheus/proxy/http_proxy.py#L90-L96), and either
passes the request through or returns 401. When `MORPHEUS_PROXY_KEY` is
empty (current dev-mode default), every request passes — exactly how the
REST endpoints behave today.

The middleware is scoped to the MCP mount, not installed app-wide. REST
endpoints continue to call `_check_auth` per-request as they do now. This
keeps the two auth checks side-by-side and avoids any chance of changing
REST behaviour by accident.

MCP's full OAuth flow as described in the spec is **out of scope for v1**
(see §11) and tracked as a roadmap item.

### 4.3. Mount path — `/mcp/` (with trailing slash)

This matches FastMCP's default and the convention used by other servers
that implement the spec. FastAPI's automatic redirect handles the
no-slash variant (`/mcp` → `/mcp/`) so client behaviour is unaffected.
The path is configurable via `--mcp-path` / `MORPHEUS_MCP_PATH` for
operators who need it elsewhere; the default does not change.

### 4.4. Session mode — stateful by default; `--mcp-stateless` opt-out

FastMCP's session manager defaults to stateful mode: each MCP client gets
an `Mcp-Session-Id`, which is reused across the client's connection.
That is the right default for a long-running proxy with stable downstream
infrastructure — it avoids re-initialising on every POST and matches what
real-world MCP clients expect.

A `--mcp-stateless` CLI flag (and `MORPHEUS_MCP_STATELESS=true` env var)
flips to stateless mode, where each POST is an independent transport with
no session tracking. The primary use case is testing — the regression
guard in §10 Group E exercises both modes — but it is also useful for
deployments where session pinning to one proxy replica is awkward.

### 4.5. Tool argument schemas — `arguments_json: str` per `mcp_bridge.py`

Each proxied tool is registered with FastMCP using a single `arguments_json:
str` parameter, mirroring [mcp_bridge.py:160](../morpheus/proxy/mcp_bridge.py#L160).
The tool's docstring documents the expected JSON shape so the model has
something to work from.

This is not the prettiest possible UX — clients see "send a JSON string"
rather than the real per-tool argument schema. The advantage is symmetry
with the existing stdio bridge, and a much smaller diff than dynamically
generating Pydantic models from each tool's `inputSchema`. The
schema-faithful version is tracked as a roadmap item; v1 ships with the
JSON-string form.

### 4.6. Management tools — exposed by default; `--no-admin-mcp-tools` opt-out

Three management tools — `set_validated_intent`, `get_proxy_status`,
`get_proxy_audit` — are exposed alongside the proxied catalogue, exactly
as `mcp_bridge.py` does today for stdio. They sit behind the same
`MORPHEUS_PROXY_KEY` check.

A `--no-admin-mcp-tools` CLI flag (and `MORPHEUS_NO_ADMIN_MCP_TOOLS=true`
env var) suppresses them. Operators who want a strictly proxy-only MCP
surface — every tool the client sees is a real downstream tool, with no
Morpheus-specific knobs — can flip this off.

### 4.7. Discovery refresh — incremental, via `add_tool` / `remove_tool`

When the downstream emits `tools/list_changed`,
`MorpheusProxy._on_tools_changed` already fires (Phase 2 of the downstream
work plumbed this through). The upstream module subscribes to that event;
on each fire it computes the diff between the current FastMCP tool set
and the new `MorpheusProxy.get_proxied_tools()` output, calls
`mcp.remove_tool(name)` for each tool no longer present, and
`mcp.add_tool(Tool.from_function(...))` for each newly present one.

FastMCP automatically emits its own `tools/list_changed` notification to
connected MCP clients on these mutations — the propagation to clients is
free. Active client sessions stay alive across the change; no session
bounce.

The listener wiring needs `MorpheusProxy` to expose
`_on_tools_changed` (or an equivalent registration hook) as a public
callback registration. If the current implementation does not allow
external subscribers, Phase 2 will add a small public registration method
(estimated +10–20 lines in `proxy_server.py`). Flagged as optional in §5.

## 5. Module layout

Two files contain production code for this feature; a third sees a small
optional touch.

### 5.1. New: `morpheus/proxy/upstream.py` (~120-200 lines)

Owns everything MCP-server-side. Specifically:

- Builds the `FastMCP` instance from a `MorpheusProxy` reference.
- Registers each discovered tool via `add_tool` with the
  `arguments_json: str` adapter.
- Optionally registers the three management tools.
- Subscribes to `MorpheusProxy._on_tools_changed` and re-syncs the tool
  set.
- Provides a helper that returns the FastMCP-mounted ASGI sub-app and the
  lifespan context the FastAPI parent needs to thread.
- Provides the auth-middleware class.

### 5.2. Extended: `morpheus/proxy/http_proxy.py` (+50-100 lines)

The HTTP proxy file gains:

- Imports from `proxy/upstream.py`.
- An `upstream_mcp` instantiation in `init_proxy`, after `MorpheusProxy`
  is built.
- `lifespan=` wiring on the FastAPI constructor that threads the FastMCP
  lifespan context.
- A mount call (`app.mount("/mcp/", upstream_mcp.asgi_app)` or
  equivalent), wrapped by the auth middleware.
- New CLI flags: `--mcp-path`, `--mcp-stateless`, `--no-admin-mcp-tools`,
  with corresponding env-var fallbacks.

**Module boundary rule.** No MCP-specific code lives in `http_proxy.py`.
The HTTP proxy file holds FastAPI, the existing REST endpoints, and the
few lines that wire `upstream.py` in. Everything FastMCP-shaped lives in
`upstream.py`. This is the same boundary discipline `transport.py` /
`http_proxy.py` enforced for the downstream feature.

### 5.3. Optional: `morpheus/proxy/proxy_server.py` (+0-20 lines)

If `MorpheusProxy` does not currently allow external subscribers to
`_on_tools_changed`, Phase 2 adds a small public registration method
(e.g. `add_tools_changed_listener(callback)`). To verify in Phase 2; if
the existing surface already supports a listener, this file is untouched.

## 6. Public API surface

### 6.1. CLI flags (added to `http_proxy.py`)

```
--mcp-path PATH         Path to mount the MCP server endpoint (default: /mcp/)
--mcp-stateless         Run the MCP server in stateless mode (default: stateful)
--no-admin-mcp-tools    Do not expose set_validated_intent, get_proxy_status,
                        get_proxy_audit via the MCP endpoint
```

### 6.2. Environment variables

```
MORPHEUS_MCP_PATH                  → fallback for --mcp-path
MORPHEUS_MCP_STATELESS             → fallback for --mcp-stateless (truthy values)
MORPHEUS_NO_ADMIN_MCP_TOOLS        → fallback for --no-admin-mcp-tools (truthy)
```

### 6.3. Backward compatibility

The new endpoint is **always enabled by default**. No `--disable-mcp`
flag, no opt-in toggle. Adding it does not change behaviour of the
existing REST endpoints, does not change the response shape of
`/proxy/*`, does not modify the audit log shape, and does not introduce
new singleton state in the proxy beyond what `MorpheusProxy` already
holds.

Operators who want to keep only REST exposed externally can use a reverse
proxy or firewall rule to deny `/mcp/*` paths. We do not add a feature
flag because the cost of the new endpoint is one extra mounted route —
zero runtime cost when nobody connects to it — and Morpheus's value
increases monotonically with the endpoint exposed.

The default port (`5020`), the default API key behaviour (open when
`MORPHEUS_PROXY_KEY` is empty, key-required when set), and the default
downstream transport (`plain_jsonrpc`) all stay exactly as they are.

## 7. Auth handling

The mechanism is an ASGI middleware that wraps the mounted MCP sub-app.

```
Incoming request to /mcp/anything
    ↓
auth-middleware.__call__(scope, receive, send)
    ├─ MORPHEUS_PROXY_KEY empty?  ──→ pass through (dev mode)
    ├─ X-Proxy-Key header matches? ──→ pass through
    ├─ Authorization: Bearer matches? ──→ pass through
    └─ otherwise                    ──→ 401 response, sub-app never reached
```

The middleware is mounted scoped to the MCP path, not registered
app-wide. The existing `_check_auth(request)` helper continues to
guard the REST endpoints exactly as it does now; nothing about that
function or its callers changes.

Behaviour parity with REST is the explicit goal: an operator who has
configured `MORPHEUS_PROXY_KEY=secret` for REST sees the same
"requires the key" experience on `/mcp/`. An operator running in dev
mode (`MORPHEUS_PROXY_KEY=""`) sees both endpoints open. There is no
combination where REST and MCP disagree about whether the proxy is
authenticated.

## 8. Lifespan wiring (the one footgun)

Phase 0 verified that lifespan threading is the single non-obvious step
in S1. FastAPI does **not** propagate a sub-app's lifespan automatically;
the parent's `lifespan=` parameter has to wrap the sub-app's lifespan
context explicitly. The pattern (sketch — actual code lives in
`upstream.py` / `http_proxy.py`):

```python
mcp_app = mcp.http_app(transport="streamable-http", path="/mcp/")

@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp_app.router.lifespan_context(app):
        yield

api = FastAPI(lifespan=lifespan)
api.mount("/", mcp_app)
```

Without the lifespan threading, FastMCP's
`StreamableHTTPSessionManager.run()` is never entered, and the first
incoming MCP request fails with `"Task group is not initialized"`. The
failure is loud, but only at request time — startup looks fine.

Two mitigations make this a one-time hazard rather than a recurring one:

1. A regression test in §10 Group A asserts that a basic `initialize` +
   `tools/list` succeeds. If lifespan wiring breaks in a future
   refactor, this test fails immediately with a clear stack trace.
2. A comment block in `http_proxy.py` next to the `lifespan=` argument
   explains *why* the wiring exists, citing this section. Future readers
   who think the boilerplate looks redundant get the answer in-place.

The lifespan dance is the price S1 pays for being a single-process
single-port architecture. We considered it acceptable in §4.1.

## 9. Discovery refresh & dynamic tool sync

The downstream side of the proxy already detects `tools/list_changed`
notifications and refreshes its local catalogue (Phase 2 of
`feat/streamable-http-downstream`). What this feature adds is propagation
of that change to the upstream-facing FastMCP server.

### 9.1. The flow

```
Downstream MCP server emits notifications/tools/list_changed
    ↓
StreamableHttpTransport / discovery loop picks it up
    ↓
MorpheusProxy._on_tools_changed fires
    ↓ (callback registered by upstream.py)
upstream.py.handle_tools_changed():
    new_tools  = MorpheusProxy.get_proxied_tools()
    diff = compute add/remove against current FastMCP tool set
    for name in to_remove:  mcp.remove_tool(name)
    for tool in to_add:     mcp.add_tool(Tool.from_function(_make_proxy_handler(tool)))
    ↓
FastMCP emits its own notifications/tools/list_changed to connected MCP clients
    ↓
MCP clients re-list and see the updated catalogue
```

### 9.2. Active sessions stay alive

The `add_tool` / `remove_tool` calls do not bounce sessions. Connected
clients receive the spec's `tools/list_changed` notification and decide
on their own when to call `tools/list` again. In-flight tool calls for
tools that are about to be removed run to completion against the (still
working) backend.

### 9.3. Listener registration

The current `MorpheusProxy._on_tools_changed` is implementation-private.
For the upstream module to subscribe, `MorpheusProxy` may need to grow a
public listener-registration method (e.g.
`add_tools_changed_listener(callback)`). Flagged optional in §5; verified
during Phase 2.

## 10. Test strategy

A new test module `morpheus/tests/test_layer11c_upstream_streamable.py`,
~250-400 lines, mirroring the structure of the existing
`test_layer11b_streamable_http.py` (downstream tests). Same harness
conventions: sync test bodies, hand-rolled fixtures, no pytest, no
pytest-asyncio. Async client work happens inside short-lived
`asyncio.new_event_loop()` blocks.

### 10.1. Group A — Lifespan and basic wiring

- A.1: Endpoint reachable. `initialize` against `/mcp/` succeeds.
- A.2: `tools/list` returns the expected catalogue (same names as
  `MorpheusProxy.get_proxied_tools()`).
- A.3: **Regression guard for the §8 footgun.** A separate fixture
  builds a FastAPI app *without* the lifespan threading; the test
  asserts that a request to `/mcp/` produces the documented
  "Task group is not initialized" error. If a future refactor accidentally
  works around this, the test fails with a pointer to §8.

### 10.2. Group B — Auth middleware

- B.1: `MORPHEUS_PROXY_KEY` set, no auth header → 401.
- B.2: `MORPHEUS_PROXY_KEY` set, correct `X-Proxy-Key` → request reaches
  the sub-app and succeeds.
- B.3: `MORPHEUS_PROXY_KEY` set, correct `Authorization: Bearer` →
  passes.
- B.4: `MORPHEUS_PROXY_KEY` empty → all requests pass (dev-mode parity
  with REST).
- B.5: REST endpoints' auth behaviour is unchanged — a single
  cross-check that hitting `/proxy/status` still goes through
  `_check_auth` and not the new MCP middleware.

### 10.3. Group C — Tool dispatch through Control 2

- C.1: A real MCP client calls a low-risk tool. Verify
  `MorpheusProxy.call_tool` was invoked. Verify the policy checker fired.
  Verify the response shape is MCP-spec-compliant.
- C.2: A high-risk tool that L1 would block. Verify the MCP client
  receives an `isError: true` response with the block reason in the text
  content (per MCP spec, NOT a JSON-RPC protocol error — same as the
  existing block path in `proxy_server.py`).
- C.3: A bypassed tool (controls disabled). Verify the call still
  forwards through to the downstream and the audit event is logged with
  `decision="bypassed"`.

### 10.4. Group D — Dynamic tool sync

- D.1: Trigger `MorpheusProxy._on_tools_changed` (or call the listener
  directly with a synthetic catalogue change). Assert the FastMCP tool
  set updates: removed tools no longer in `tools/list`, new tools appear.
- D.2: A connected MCP client receives a `tools/list_changed`
  notification when D.1's change happens, then sees the new catalogue on
  re-list.
- D.3: An in-flight tool call against a tool that is about to be removed
  completes successfully — removal does not abort active calls.

### 10.5. Group E — Stateful vs stateless

- E.1: Default (stateful) mode. Two consecutive calls from the same
  client carry the same `Mcp-Session-Id`. Server-side, the same
  transport instance handled both.
- E.2: `--mcp-stateless` mode. Two consecutive POSTs are independent —
  no session ID is reused, no shared transport.

### 10.6. Group F — Management tools toggle

- F.1: Default. `tools/list` includes `set_validated_intent`,
  `get_proxy_status`, `get_proxy_audit`.
- F.2: With `--no-admin-mcp-tools`. Same `tools/list` does *not* include
  the three admin tools.
- F.3: Suppression is endpoint-local. A REST client hitting
  `/proxy/intent` continues to work in both modes — the flag only
  affects the MCP surface.

### 10.7. Group G — Concurrent session safety

- G.1: Three concurrent MCP clients, each making tool calls. All three
  complete without state leak. Verify each client's `Mcp-Session-Id`
  stays distinct on the server side.
- G.2: Note (in a test comment, not a fix) that the existing
  `_validated_intent` global in `http_proxy.py:54` is process-wide and
  flows through both REST and MCP paths now; concurrent clients setting
  different intents will race. **This is a pre-existing bug; the test
  documents the limitation, it does not fix it.** Tracked in §11.

## 11. Out-of-scope for v1

Explicit non-goals, each with a roadmap pointer where applicable.

- **MCP OAuth flow.** The spec describes a full OAuth-based auth dance
  for MCP clients; v1 ships with a static proxy-key check (§4.2 / §7).
  Roadmap.
- **Schema-faithful tool argument surfacing.** Tools are exposed with a
  single `arguments_json: str` parameter (§4.5). Generating Pydantic
  models from each tool's MCP `inputSchema` so the model sees real
  argument shapes is roadmap.
- **MCP capabilities negotiation beyond FastMCP defaults.** The defaults
  cover the streamable-HTTP transport and basic tool serving. Advanced
  capability negotiation (sampling, elicitation, roots, etc. on the
  server side) is roadmap if and when it becomes load-bearing.
- **Persistent MCP session storage.** Sessions are in-memory (FastMCP
  default). Roadmap if and when Morpheus is deployed as a multi-replica
  service where sessions must survive a single replica's restart, or
  must be shared across replicas.
- **Fixing the `_validated_intent` global state bug.** Pre-existing. Out
  of scope for this feature and explicitly *not* fixed (§12). Tracked
  separately.

## 12. Risk assessment

Three concrete risks ahead of Phase 2.

### 12.1. Lifespan wiring fragility — medium

S1's main load-bearing wiring step. Works, but easy to break in a future
refactor (§8). Mitigations: the regression test in §10 Group A.3 fails
loudly if the wiring is missing, and a comment block in `http_proxy.py`
next to the `lifespan=` argument explains why it exists.

### 12.2. FastMCP version churn — low-medium

`add_tool` and `remove_tool` were verified at FastMCP `3.1.1` during
Phase 0 live tests. If FastMCP changes the API in a future major
release, the upstream module breaks. Mitigation: pin FastMCP to a known
range in `requirements.txt` (e.g. `fastmcp>=3.1,<4`). Same guard pattern
as the `mcp>=1.26,<2` pin from the downstream feature.

### 12.3. Pre-existing `_validated_intent` global bug — medium, pre-existing

`http_proxy.py:54` declares `_validated_intent: dict | None = None` as
module-level state. This was a known limitation before this feature; it
will continue to be one after. The new MCP path inherits it: the `set_validated_intent`
management tool, when called, mutates the same global the REST
`/proxy/intent` endpoint mutates. With concurrent clients, intents race.

**This feature does not fix the bug.** It does not make the bug worse in
any qualitative sense — both REST and MCP paths now share the same
global, which is the same single point of contention that already
existed for REST. The Group G.2 test documents this, with a comment
making explicit that the test is an acceptance of the existing
behaviour, not a verification of correctness. The fix belongs to a
separate change (refactor `_validated_intent` to per-request /
per-session state), which is out of scope here.

## 13. Rollout

Single-step. The feature ships through the standard Phase 2 / Phase 3 /
Phase 4 sequence used for the downstream work, with atomic commits
prefixed `[streamable-http-upstream]`. No feature flag, no progressive
rollout, no migration phase. Backward compatibility is guaranteed by
construction (REST endpoints unchanged, new endpoint added).

Operators who upgrade past this feature get the new endpoint
automatically. They can ignore it, deny it at a reverse proxy, or
configure their MCP clients to use it. None of those choices requires
additional Morpheus configuration.

## 14. Future work

- MCP OAuth support, replacing the static proxy-key check at the MCP
  boundary with the spec's OAuth dance.
- Schema-faithful tool argument surfacing — generate per-tool Pydantic
  models from each tool's MCP `inputSchema` and register them with
  FastMCP, so the model sees real argument shapes rather than a JSON
  string.
- MCP server-side capabilities negotiation beyond FastMCP defaults
  (sampling, elicitation, roots, structured tasks).
- Persistent / shared MCP session storage (e.g. Redis) for multi-replica
  deployments where session pinning is unacceptable.
- Refactor `_validated_intent` to per-session state, retiring the
  process-global. Pre-existing bug; tracked outside this feature.

---

**Phase 1 design complete. Phase 2 implementation will follow this
contract literally. Any deviation discovered during implementation is
flagged and resolved before code lands, mirroring the discipline used on
`feat/streamable-http-downstream`.**
