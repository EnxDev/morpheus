# Morpheus: A Control Layer for AI Agents with Deterministic Decisions

## The Problem Nobody Is Solving

There is a recurring pattern in modern AI systems: the user types something, the model interprets it, decides, and acts. All in one opaque step that cannot be verified or audited.

When a user asks *"delete all orders from last month"*, an output validator sees valid JSON. A traditional guardrail checks that the text is not toxic. But nobody asks: **is this action authorized? Is the scope consistent with what the user intended? Are you about to delete 847 records?**

AI safety frameworks today focus on what the model **says**. Nobody checks what the model **decides to do**.

Morpheus was built to fill this gap.

## What Morpheus Does

Morpheus is a control layer that sits between user input and AI action execution. It is not an output guardrail. It is not a prompt filter. It is a validation system with two independent checkpoints: one intercepts the input before it reaches the model, the other intercepts the model's actions before they reach the tools.

Given a JSON intent with certain confidence values, the system's behavior is completely predictable, reproducible, and explainable — regardless of whether those values were produced by a probabilistic process.

```
# Without Morpheus
User → LLM → calls tool → executes
                           ↑
                    no control here

# With Morpheus
User → [Control 1: is the intent clear and valid?]
     → LLM
     → [Control 2: is this action authorized and consistent?]
     → executes (or gets blocked)
```

Control 2 — the MCP proxy that intercepts every tool call — is arguably the most differentiating feature. Most AI safety systems operate only on textual input or output. Morpheus operates at the **point of action**: the moment the model is about to invoke a real tool with real parameters.

The two controls are independent. You can enable just one, both, or neither. When a control is disabled, the action is not silently ignored — it is logged as `bypassed`. Every state is a tracked decision.

### Why This Matters

The problem with AI systems is not that they use probability. It is that probability influences decisions in an opaque way. In Morpheus, that contamination is explicitly blocked: the probabilistic number enters, gets compared against a fixed threshold, and the result is binary and auditable. Uncertainty does not propagate silently — it is made explicit, measured, and resolved before the system acts.

## Control 1 — Input Validation

Before the prompt reaches the model, Morpheus analyzes and decomposes it into a **structured intent** with a confidence level for each field:

```json
{
  "measure": [{"value": "revenue", "confidence": 0.95}],
  "dimension": [{"value": "by region", "confidence": 0.88}],
  "time_range": [{"value": "Q1 2025", "confidence": 0.96}],
  "filters": [{"value": null, "confidence": 0.1}]
}
```

Any field below a configurable confidence threshold triggers a **clarification cycle** — the system explicitly asks the user to specify what is missing, up to a maximum of 3 iterations. Ambiguity is never silently resolved by the model.

Only when the intent is complete and validated does the prompt get sent to the model.

## Control 2 — Action Validation (MCP Proxy)

The second control intercepts what the model is **about to do**, before the action is executed. It works as a transparent MCP proxy: the model sees the same tools and the same schemas, but every call goes through Morpheus. The proxy automatically discovers available tools using the `tools/list` method from the MCP standard — no per-tool configuration, it works with any MCP server.

The proxy operates on two levels:

**Level 1 — Deterministic** (always active). Risk classification by pattern:

```yaml
delete_*, remove_*, drop_*  →  HIGH   (blocked, requires confirmation)
send_*, create_*, update_*  →  MEDIUM (requires coherence check)
get_*, list_*, read_*       →  LOW    (automatically approved)
```

Morpheus does not know what `delete_repo` does on GitHub. It knows it starts with `delete_` — high risk — and blocks it until confirmation. This is always deterministic, always predictable.

**Level 2 — LLM-assisted coherence check** (optional). Verifies semantic consistency between the user's validated intent and the action parameters:

```
Validated intent:
  task:     "send_report"
  audience: "team_sales"

Model's action:
  tool:   send_email
  params: { to: "everyone@company.com" }

→ confidence: 0.12 → below threshold 0.70 → BLOCKED
```

A crucial point: **the LLM returns a score, not a decision**. The final decision (block or approve) is deterministic, based on a configurable threshold. The LLM proposes. Morpheus decides.

## The `bypassed` State: Safety Even When Controls Are Off

Most safety systems have two states: active or disabled. When disabled, nothing happens — no logs, no trace.

Morpheus introduces a third state: `bypassed`. When a control is deliberately disabled, every action that passes through it is still recorded in the audit trail with this state. It is not a gap. It is an explicit, tracked decision with a timestamp and context.

This means a security or compliance team can answer the question: *"on March 14 at 10:32 AM, the coherence check was disabled — what went through during that period?"* The answer is in the log, not in a black hole.

```json
{
  "decision": "bypassed",
  "controls_active": {
    "input_validation": true,
    "action_validation": false,
    "coherence_check": false
  },
  "reason": "controls disabled by admin for load testing"
}
```

For systems that require complete audits — finance, healthcare, critical infrastructure — this distinction between "off and silent" and "off and tracked" is not cosmetic. It is the difference between compliance and an audit gap.

## Audit Trail

Every event produces a structured record, regardless of the controls' state:

```json
{
  "event": "action_intercepted",
  "tool": "send_email",
  "params": { "to": "everyone@company.com" },
  "risk_level": "medium",
  "level_1_result": "approved",
  "level_2_result": {
    "coherence_score": 0.12,
    "threshold": 0.7,
    "reason": "recipient scope exceeds authorized audience"
  },
  "decision": "blocked",
  "controls_active": {
    "input_validation": true,
    "action_validation": true,
    "coherence_check": true
  }
}
```

### Every Action Is Attributable

Morpheus's audit trail does not just log decisions — it logs who did what, with which original prompt, through which security controls, and with what outcome. This includes the security actions themselves: if the Input Sanitizer blocked a request, if the Coherence Check zeroed out a field, if the Session Guard detected field drift in the clarification loop.

The result is a complete chain of custody: given a production event, you can trace back to the original input, see how it was parsed, which security flags were triggered, how many clarification iterations occurred, and why the final action was approved or blocked.

## Where the LLM Is Used (and Where It Is Not)

Morpheus uses the LLM at specific, bounded points:

| Component | Type | Purpose |
|---|---|---|
| Parser | LLM | Natural language → structured intent |
| Validator | LLM | Structural coherence check |
| Clarifier | LLM | Generate clarification questions |
| → User | Human input | Answer clarification questions |
| → Parser (re-run) | LLM | Update the intent with the user's response |
| Coherence check (Level 2) | LLM | Semantic consistency: intent ↔ action parameters |

The clarification loop — Clarifier → User → Parser — repeats until all fields reach the confidence threshold, or until the maximum iteration limit (3). The user is never bypassed. Ambiguity is never silently resolved.

A note on the distinction: the **Validator** (LLM) checks the structural coherence of the intent — for example, verifying that the extracted fields are semantically plausible. The **Coherence Check** in the "Security by Design" section is a different component: it lexically compares the original input with the parser's output, without involving an LLM. They are separate layers with separate responsibilities.

Everything else — confidence thresholds, decision engine, pattern matching, risk classification, execution — is **deterministic Python with no LLM calls**.

## The Case of the 847 Records

Let us return to the opening example. A user types: *"delete all orders from last month"*.

Without Morpheus, the model interprets the request, generates a `DELETE` SQL query, and executes it. The result is technically correct. 847 records disappear.

With Morpheus:

1. **Control 1** — The parser extracts the intent: `task: "delete_orders"`, `time_range: "last month"`, `scope: "all"`. The `scope` field has confidence 0.92, but the value `"all"` on a destructive operation triggers clarification: *"Do you confirm you want to delete all orders, with no filters for status or customer?"*
2. The user responds: *"only the cancelled ones"*. The intent is updated: `filters: "status = cancelled"`, confidence 0.95.
3. The user confirms the complete intent.
4. The model generates the tool call: `delete_orders({status: "cancelled", date_range: "2025-02"})`.
5. **Control 2** — The proxy intercepts. `delete_*` → high risk → requires explicit confirmation. The coherence check verifies that the parameters are consistent with the validated intent. Everything matches.
6. The action is approved, executed, and logged with full detail in the audit trail.

Result: 23 records deleted, not 847. The difference came down to a clarification question the model would never have asked.

## Security by Design

Morpheus includes a layered security pipeline that operates independently of the intent controls.

Every input — both the initial input and responses in the clarification loop — passes through a sanitizer that detects known injection patterns, anomalous structures, and out-of-bounds sizes. An input with three or more flags never reaches the LLM parser. An input with a single flag is logged as suspicious and continues with a trace.

The Coherence Check lexically compares the parser's output with the original input. If the parser produces `"delete_database"` but the user wrote `"revenue by region"`, that field is zeroed out to confidence 0.0 — without involving an LLM, without ambiguity. It is a deterministic check that isolates parser manipulations.

The Session Guard has cross-iteration memory in the clarification loop: it detects field drift (a field that changes without being the one being clarified), confidence spikes on empty responses, and fields clarified more than three times. A multi-turn attack that distributes malicious intent across multiple responses is detected as an anomalous pattern, not as a single suspicious request.

**What remains exposed and how we are mitigating it.**

*Incomplete pattern matching against multilingual variants and obfuscation.* Pattern matching on fixed strings is the weakest layer by definition. The mitigation is Unicode normalization of the input before the sanitizer — `NFKC` normalization, removal of zero-width and lookalike characters — so that `"ign0re"` becomes `"ignore"` and visually identical Cyrillic characters are mapped back to their ASCII equivalents. The sanitizer works on the normalized text, not the original. This covers most practical variants without introducing an LLM into the security layer.

*Semantic multi-turn attacks in the clarification loop.* Three individually innocuous responses that construct a malicious intent are not detectable with pattern matching. Two mitigations are on the roadmap: (A) a cumulative deterministic coherence check that compares the final intent against the original input and the full set of user responses — not just iteration by iteration; (B) an optional semantic similarity check that, before accepting the final intent, asks the LLM whether it is semantically consistent with the original request. It costs one extra LLM call but is bounded — it happens once, after the loop, before the Decision Engine. As always, the LLM returns a score, Morpheus decides.

These vulnerabilities are documented because an honest security system describes its own limitations.

## The Guiding Principle

We do not trust the model's interpretation. We surface it, validate it, and confirm it with the user. From that point on, every decision is deterministic with respect to the validated intent — no LLM intervenes in choosing actions or evaluating risk.

This approach fits within the emerging taxonomy of **Intent-Based Access Control** (IBAC) — an authorization model that shifts the focus from "who can do what" to "for what purpose, under what constraints, on which resources." Unlike traditional models (RBAC, ABAC), IBAC ties every action to a declared and validated intent. For a technical deep dive on the theoretical framework, see [Intent-Based Access Control: A Technical Primer](https://kenhuangus.substack.com/p/intentbased-access-control-a-technical) by Ken Huang.

Morpheus implements the full IBAC stack — intent parser, policy engine, tool gateway — with two additions: the dual checkpoint and the clarification cycle that resolves ambiguity *before* the model acts, not after.

## Try Morpheus

Morpheus is open source (MIT). The backend is a FastAPI API, it includes a Python SDK, an MCP server for Claude Desktop and VS Code, and a React UI for interactive pipeline testing.

```bash
git clone https://github.com/EnxDev/morpheus.git
cd intent-guard
pip install -r intent_guard/requirements.txt
cd intent_guard && uvicorn main:app --reload --port 8000
```

The LLM provider is auto-detected from the API key present in the environment (OpenAI, Anthropic, or Ollama as a local fallback).

Repository: [github.com/EnxDev/morpheus](https://github.com/EnxDev/morpheus)
