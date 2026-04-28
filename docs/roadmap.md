# Morpheus — Roadmap

Post-demo backlog of work on the Morpheus repo itself. This is not a product
roadmap in the marketing sense — it is a technical backlog of concrete
pieces of work identified during the Superset demo integration exercise.

Each item has three fields: **Why** (what problem it solves), **Scope**
(what exactly needs to change), and **Size** (rough effort estimate to
calibrate prioritization).

Ordering in each section reflects current priority. It is not fixed.

---

## 1. Features

### 1.1. MCP streamable-HTTP **server** endpoint on the HTTP proxy

**Why.** Today Morpheus's HTTP proxy exposes only five custom REST endpoints
(`/proxy/call`, `/proxy/tools`, `/proxy/status`, `/proxy/intent`,
`/proxy/audit`). These are proprietary — native MCP clients (LangChain's
`MultiServerMCPClient`, Claude Desktop over HTTP, n8n MCP integrations,
anything speaking the MCP spec) cannot connect to Morpheus as a transparent
sidecar. This forces integrators to either call Morpheus's REST API
manually from their tool-calling loop (Option C in the Superset demo) or
bypass Morpheus entirely for tool dispatch.

With an upstream MCP server endpoint, the proxy becomes architecturally
symmetric to its downstream (which already speaks streamable-HTTP as of
`feat/streamable-http-downstream`): clients connect via standard MCP,
calls flow through Control 2 (Level 1 pattern rules + Level 2 coherence),
and are forwarded to the real downstream. The proxy becomes a true
policy-enforcing MCP sidecar.

**Scope.**

- New endpoint surface at `/mcp` on the existing FastAPI app, speaking
  full MCP streamable-HTTP: `initialize` handshake, `Mcp-Session-Id`
  management, SSE-or-JSON response bodies, session lifecycle
- Two implementation strategies to evaluate during Phase 1 of this work:
  - S1: Mount FastMCP as a sub-application of the FastAPI app
    (`app.mount("/mcp", mcp_asgi_app)`) — simplest, one process
  - S2: Standalone FastMCP server in a background thread, sharing
    state with the REST app — more complex but possibly more flexible
    for concurrency
- Dynamic tool exposure: the proxy discovers tools from downstream at
  runtime, so FastMCP tool registration cannot be static — need to
  verify the SDK supports runtime tool injection or forwarding
- Every MCP tool call received on `/mcp` routes through the existing
  `MorpheusProxy.call_tool()` → Control 2 pipeline → downstream forward
- Existing REST endpoints at `/proxy/*` continue to work unchanged
- Transport selection: when the upstream endpoint is active, it should
  coexist with the downstream transport config (upstream = MCP server,
  downstream = `streamable_http` or `plain_jsonrpc`)

**Size.** 1-2 weeks following the same five-phase methodology used for
streamable-HTTP downstream (reconnaissance → design → implementation →
tests → docs). Probable final artifact: a new `StreamableHttpServer`
class in `morpheus/proxy/` analogous to `StreamableHttpTransport`, plus
300-500 lines of test coverage.

**Blocked by.** Nothing. Can start anytime.

**Unblocks.** Superset demo Option A (proxy as transparent MCP sidecar),
any future integration with n8n, LangGraph, Langchain, or any HTTP-native
MCP client.

---

### 1.2. Transport auto-detection

**Why.** Today downstream transport selection is explicit:
`--transport plain_jsonrpc` or `--transport streamable_http`. For power
users this is fine. For less experienced integrators pointing Morpheus at
an unknown MCP server, an auto-detect mode would reduce the "does this
work?" friction to zero.

**Scope.**

- Add `--transport auto` as a third option
- On startup, probe the downstream once: attempt `initialize` as
  streamable-HTTP; on failure, fall back to `plain_jsonrpc`
- Cache the result for the process lifetime
- Log the detected transport clearly on startup so operators know what
  happened
- Do NOT make `auto` the default — explicit remains the default

**Open design question.** How to signal probe failure safely. The risk is
that `auto` silently falls back from streamable-HTTP to plain_jsonrpc
because of a transient issue, and the operator never notices that
Morpheus is now speaking a less secure dialect to their production server.
A mitigation: if `auto` falls back, require a config flag
`--allow-plain-fallback` to actually enable the fallback behavior; without
the flag, a failed probe is a startup error.

**Size.** 2-4 days, mostly tests and documentation.

**Blocked by.** Nothing.

**Priority note.** Not urgent. Explicit transport is fine for current
users. This is a nice-to-have for broader adoption.

---

### 1.3. OAuth / downstream auth negotiation

**Why.** Some MCP servers require OAuth or bearer-token authentication
before accepting `tools/call` requests. The MCP spec supports this via a
dedicated auth dance. Morpheus currently does not implement it.

**Scope.**

- Downstream auth support: when configured, the proxy initiates the OAuth
  flow with the downstream server, stores tokens securely (not in logs,
  not in audit), refreshes them as needed
- Upstream auth pass-through: if a client connects to Morpheus with its
  own auth token, decide whether to forward to downstream, substitute
  with proxy-owned tokens, or both
- Configuration: env vars or CLI flags for client ID, client secret,
  token URL, refresh URL

**Size.** 1-2 weeks. OAuth has edge cases (token refresh races, scope
changes, revocation) that demand real test coverage.

**Blocked by.** Need a concrete use case. No current Morpheus user has
asked for this.

**Priority note.** Defer until an integration requires it.

---

### 1.4. Stdio MCP transport for the HTTP proxy (bidirectional)

**Why.** Today there are two separate products: the HTTP proxy
(`proxy_server.py` + `http_proxy.py`) and the stdio bridge
(`mcp_bridge.py`). They share the `MorpheusProxy` core but present two
surfaces. A user wanting Morpheus to sit between Claude Desktop (stdio)
and a Superset MCP server (HTTP) currently has no single-command setup.

**Scope.**

- Unify the two under one "proxy" concept with transport options for
  both upstream and downstream:
  - `--upstream-transport stdio | streamable_http`
  - `--downstream-transport plain_jsonrpc | streamable_http`
- Any combination should work: stdio→HTTP, HTTP→stdio, HTTP→HTTP,
  stdio→stdio
- The stdio bridge's existing functionality migrates into this unified
  structure, not a rewrite

**Size.** 1 week after items 1.1 (upstream HTTP) is done. Before that,
this item is blocked because the upstream HTTP surface doesn't exist yet.

**Blocked by.** 1.1.

**Priority note.** Natural follow-up to 1.1. Do it only if user demand
justifies it.

---

## 2. Bug fixes (known, tracked, not yet addressed)

### 2.1. `_validated_intent` module-level global in `http_proxy.py`

**Why.** The proxy has a module-level global used as a fallback when a
`/proxy/call` request doesn't include an intent inline. Under concurrent
users, user A's intent can leak into user B's decision. Discovered during
Superset demo design.

**Scope.**

- Replace the module global with session-scoped state
- The session identifier comes from the inline intent's session field,
  or from a header like `X-Morpheus-Session-Id`, or from the MCP
  `Mcp-Session-Id` if the upstream MCP server endpoint (item 1.1) is in
  use
- Add tests specifically for multi-session state isolation

**Size.** 3-5 days.

**Blocked by.** Nothing. Can be done independently at any time.

**Mitigation currently in place.** Single-user deployments (like the
Superset demo) are unaffected as long as the client always passes the
intent inline. Documented as an invariant in the demo's `CLAUDE.md`.

**Priority.** High. This is a correctness bug in any multi-user
deployment.

---

### 2.2. Default `0.0.0.0` bind and empty `MORPHEUS_PROXY_KEY` allow open dev mode

**Why.** Today `http_proxy.py` binds to `0.0.0.0` by default, and
`MORPHEUS_PROXY_KEY` being empty is accepted as "dev mode" with no auth.
Combined, these two defaults mean an operator who starts the proxy
naively exposes it on the local network with no authentication. This is
a foot-gun for anyone running Morpheus on a developer laptop connected
to a corporate network.

**Scope.**

- Change default bind to `127.0.0.1`
- If the operator explicitly sets `--host 0.0.0.0`, require either a
  `MORPHEUS_PROXY_KEY` to be set, or an explicit
  `--allow-unauthenticated` flag — both absent means startup failure
  with a clear error message
- Update README and docs

**Size.** 1-2 days. Most of the work is tests for the various combinations.

**Blocked by.** Nothing.

**Priority.** Medium-high. This is a security posture fix, not a
correctness bug, so it doesn't break anything today — but any public
Morpheus release should land this first.

---

### 2.3. CORS `allow_origins=["*"]` in `http_proxy.py`

**Why.** The proxy currently allows any origin in its CORS config. The
code comment says "restrict in production" but provides no mechanism.

**Scope.**

- Add a `--cors-origin` / `MORPHEUS_CORS_ORIGINS` config that accepts a
  list of allowed origins
- Default to an empty list (no CORS) if CORS isn't needed
- Current behavior (wildcard) should only be selectable via explicit
  `--cors-allow-all` or similar opt-in
- Document the three modes (off, whitelist, wildcard) with examples

**Size.** 1-2 days.

**Blocked by.** Nothing.

**Priority.** Low. Practically irrelevant for server-to-server use
(which is the primary mode). Matters only for browser-to-proxy use,
which isn't a typical Morpheus deployment.

---

### 2.4. Documentation import-path bug across `docs/*.md`

**Why.** During Phase 5 of `feat/streamable-http-downstream`, Claude
Code discovered that `docs/configuration.md`, `docs/getting-started.md`,
and `docs/sdk.md` all contain `from morpheus.…` import paths that do
not match the actual package layout. The project runs from inside
`morpheus/` as cwd (`cd morpheus && python …`), so the top-level
importable package is `proxy`, not `morpheus.proxy`.

**Scope.**

- Two possible fixes:
  - (A) Update all affected doc imports to use `from proxy.…`,
    `from policies.…`, `from sdk.…`
  - (B) Add a top-level `morpheus/__init__.py` shim so that
    `from morpheus.x import y` actually works, and leave the docs as-is
- Option B is more user-friendly: the README says "pip install morpheus"
  so `import morpheus` is what users expect. But it requires
  reconsidering the package structure.

**Affected files.**

- `docs/configuration.md` — lines 10, 11, 139, 169 (4 occurrences)
- `docs/getting-started.md` — line 72 (1 occurrence)
- `docs/sdk.md` — lines 10, 64, 73, 82, 91 (5 occurrences)

**Size.**

- Option A: 1 hour (find/replace, verify imports run)
- Option B: 1 day (structural change, all tests, backward compat
  verification)

**Blocked by.** Decision between A and B.

**Priority.** Medium. Documentation that doesn't match the code is
worse than missing documentation.

---

### 2.5. `sleep(0.2)` in Layer 11b Group E test is flaky-by-design

**Why.** In Phase 3 of `feat/streamable-http-downstream`, test E.1
initially failed because `ClientSession.initialize()` sends a
`notifications/initialized` notification fire-and-forget, and flipping
the mock's `kill_next` flag immediately after `initialize()` returns
sometimes caught the in-flight notification instead of the next real
request. The fix was a `sleep(0.2)` between initialize and the real
call. This works on a fast developer machine and is documented, but
will likely flake on CI or on load.

**Scope.**

- Replace `sleep(0.2)` with one of:
  - A polling loop with timeout: wait for the mock to receive the
    notification before flipping the flag
  - An explicit synchronization hook in the mock (`event.wait()`) that
    sets when the notification arrives
  - Investigate whether the SDK exposes any "session is fully ready"
    signal we can await on properly

**Size.** A few hours.

**Blocked by.** Nothing.

**Priority.** Low. The test currently passes reliably in local runs.
Only relevant if Morpheus acquires a CI with resource-constrained
runners.

---

## 3. Infrastructure & release

### 3.1. Continuous Integration (GitHub Actions)

**Why.** Today there is no CI on the Morpheus repo. Tests only run when a
developer remembers to run them locally. Any future contributor or future
release will want CI that gates merges.

**Scope.**

- A GitHub Actions workflow that on push/PR runs:
  - `python morpheus/tests/run_all_tests.py`
  - `ruff check` (if adopted — the repo uses it elsewhere)
  - Linters and static analysis as appropriate
- Run on Python 3.10, 3.11, 3.12 (whatever range Morpheus supports)
- Matrix-test against `mcp>=1.26,<2` (and whatever the floor is)

**Size.** 1-2 days.

**Blocked by.** Nothing.

**Priority.** Medium. Not critical while Morpheus has a single
maintainer, but essential before opening the project to external
contributors.

---

### 3.2. First tagged release

**Why.** The CHANGELOG has a `[Unreleased]` entry (added during Phase 4 of
`feat/streamable-http-downstream`). At some point, that entry becomes
`[0.2.0]` or similar, a git tag is cut, and Morpheus has its first real
release.

**Scope.**

- Decide the version number (0.2.0? 0.1.0? semver from scratch?)
- Move CHANGELOG `[Unreleased]` to a versioned section with a date
- Git tag matching the version
- PyPI publish if Morpheus wants to be installable via pip (separate
  decision — currently source-install only)
- README update with install instructions matching the release model

**Size.** Half a day once the decision about PyPI vs source-only is made.

**Blocked by.** Items 1.1 and 2.1 arguably should ship before a tagged
release, because they are both known-important-and-unshipped. But this is
a judgment call — the current streamable-HTTP downstream work is
release-worthy as-is.

**Priority.** Medium. Tag the first release when there's a natural
milestone.

---

### 3.3. PyPI package

**Why.** Today Morpheus is installed via source clone. A PyPI package
would allow `pip install morpheus-control-layer` (or whatever the name is)
and dramatically lower the barrier to trial.

**Scope.**

- Verify/finalize the Python package structure (relates to item 2.4 —
  the import path bug)
- Create `pyproject.toml` with the right metadata, dependencies, entry
  points
- Reserve a name on PyPI (`morpheus` is taken by NVIDIA; another name
  needed)
- Automate publish via GitHub Actions on release

**Size.** 2-3 days, most of the time in the naming decision and the
first publish dry-run.

**Blocked by.** 2.4 (import path fix) and 3.2 (first release).

**Priority.** Low-medium. Depends on whether Morpheus's growth strategy
is via pip distribution or via GitHub visibility.

---

## 4. Research / open questions

These are not actionable items — they are questions that, if answered,
might reshape the roadmap.

### 4.1. Is Morpheus a library, a sidecar, or both?

Today Morpheus is structurally a sidecar: you run it as a separate
service and integrate via HTTP. But parts of it (Control 1: parser,
validator, clarifier, decision engine, IBAC) could plausibly be used as a
Python library embedded inside another application. Deciding this
explicitly shapes future API design.

### 4.2. What's the relationship between Morpheus's audit trail and Superset's, OpenTelemetry, or other observability systems?

Morpheus's audit log is currently in-memory and proprietary. Teams using
Superset, Prometheus, or OpenTelemetry will want Morpheus events in their
existing pipelines. A "structured audit sink" abstraction (pluggable:
in-memory, file, OTEL, custom) is a natural next step but currently
unsketched.

### 4.3. Should Morpheus's Control 1 coherence check be extractable as a standalone library?

The coherence check between parsed intent and action parameters is the
most novel piece of Morpheus. Other intent-based-access-control projects
(and generally, any LLM-tool-calling system) might want to use it alone,
without the full Morpheus pipeline. Worth considering if the demand
shows up.

---

## 5. Notes on methodology

The streamable-HTTP downstream work (feat/streamable-http-downstream,
shipped Apr 2026, 20 commits, 187 tests) established a five-phase
methodology that has worked well:

1. **Phase 0 — Reconnaissance**: read the code, produce a report, no
   changes
2. **Phase 1 — Design**: a written design doc committed before
   implementation
3. **Phase 2 — Implementation**: atomic commits, one per step, tests
   remain green at every step
4. **Phase 3 — Tests**: new test coverage for the new feature +
   regression coverage for the old
5. **Phase 4 — Documentation**: README, CHANGELOG, design doc status
   update
6. **Phase 5 — Follow-ups**: close any inconsistencies surfaced during
   documentation

Apply this to all items in section 1 and section 2 that are non-trivial.
Items below ~3 days can be done more informally (one phase, one commit).

---

## 6. How this document evolves

- New items added as they surface from real use
- Priority reviewed whenever work is picked up
- Completed items moved to a `CHANGELOG.md` entry (or a dedicated
  "Completed" section here if kept for historical context)
- If an item is explicitly deferred forever, move to a "Rejected"
  section with the reason

This is a living document. The current form is post-Superset-demo;
expect it to look different six months from now.
