# Multilingual Support in Morpheus — Analysis

## TL;DR

Morpheus is, today, an English-coupled system. The deterministic checks that constitute its security guarantee — Level 1 risk classification, prompt-injection detection, and IBAC action inference — all reduce to English-language pattern matching. The good news: most of the deterministic surface fails *closed* on non-English input (unknown risk → confirmation required), so the security claim survives a multilingual deployment with degraded UX rather than collapsing. The bad news: one path fails *open*. The IBAC step-name inference at [morpheus/policies/ibac.py:304-324](../morpheus/policies/ibac.py#L304-L324) defaults unknown English-prefix step names to the most permissive action (`execute`), which is a vulnerability the multilingual lens uncovered and which should be fixed independently of any broader i18n work. The recommended path forward is sequenced: ship the IBAC fix and an operator-declared `risk` field on tool registration first (week one, ~60% of the practical value); then parameterize the L2 coherence prompt by language and extend the config schema with per-language fields; then curate polyglot prompt-injection patterns for a finite, declared set of languages; and finally — only finally — invest in a layered detection architecture with a multilingual embedding fallback tier behind the existing regex. *Do not* replace the deterministic regex with embeddings: that trades auditability for reproducibility, which is not the same property.

## 1. Context

This document was written in response to a concern raised during an evaluation of Morpheus as a candidate authorization layer for an enterprise BI deployment whose customer base operates in multiple languages. The concern, paraphrased: *the deterministic checks appear to be language-coupled, and won't scale to a multilingual environment.* That concern is technically correct. This analysis is intended for two audiences — the team that raised it, and the broader open-source community using Morpheus — and is framed neutrally for both. It treats the originating deployment as an example, not as the unit of generalization.

The scope is deliberately narrow: this is an audit and a set of recommendations, not a design document. No code is changed here, no API is specified, no schema is finalized. The goal is to give an honest account of where the system sits today and a defensible argument for where it should go.

The structure that follows: §2 audits the language couplings with file-and-line citations; §3 frames what "multilingual support" actually means for an authorization layer; §4 evaluates six approaches; §5 makes a single, sequenced recommendation; §6 names what is out of scope; §7 lists the questions that the team needs to answer before any of this becomes implementable.

## 2. Audit: Where Morpheus is language-coupled today

A useful taxonomy before reading the findings: every coupling below is classified along two axes. *Severity*: hard (system silently fails or degrades dramatically on non-English input) vs soft (system works with degraded UX or accuracy). *Logic type*: deterministic Python (regex, string equality, dict keys) vs LLM-based (prompts, completions). The two axes interact: a hard-deterministic coupling is the easiest to fix but the worst to leave alone, since it produces incorrect behavior with no graceful degradation. A hard-LLM coupling tends to degrade gracefully on modern multilingual models. A soft coupling rarely warrants its own fix.

### 2.1 Control 1 — intent parser

The parser sends a fixed English prompt to the LLM on every parse call. The prompt is at [morpheus/domain/default_bi.py:176-229](../morpheus/domain/default_bi.py#L176-L229) for the default BI domain, and at [morpheus-hr-chatbot-demo/hr_domain.py:250-279](../morpheus-hr-chatbot-demo/hr_domain.py#L250-L279) for the demo HR domain. Both are unilingual English instructions with English example values (`["revenue", "orders", "margin"]`, `["Q1 2025", "last 30 days"]`, `"how many days do I have left?"`).

In practice this is a *soft* coupling: GPT-4o and Claude Sonnet are competent multilingual parsers and will extract intent from a Spanish or French query against an English prompt. But the embedded examples anchor the model's expectations, and the confidence calibration against those examples is implicitly English-tuned. A non-English query parses, often correctly, but with confidence scores that may be miscalibrated against the per-field thresholds at [morpheus/domain/default_bi.py:9-76](../morpheus/domain/default_bi.py#L9-L76). The validation prompt at [morpheus/domain/default_bi.py:231-235](../morpheus/domain/default_bi.py#L231-L235) is similarly English; downstream code checks `.startswith("YES")`/`.startswith("NO")`, which only fails if the model responds in another language — which a well-prompted multilingual LLM will not. The retry path at [morpheus/parser/parser.py:107](../morpheus/parser/parser.py#L107) appends an English instruction on parse failure.

### 2.2 Control 1 — clarifier

This is where the user-visible language gap becomes hardest. The clarifier owns the dialogue: when the parser is unsure, the clarifier asks. Its fallback question dictionary at [morpheus/clarifier/clarifier.py:281-288](../morpheus/clarifier/clarifier.py#L281-L288) hard-codes six English questions (`"Which metric do you want to see?"`, `"How do you want to group the data?"`, etc.). Per-field overrides at [morpheus/domain/default_bi.py:13, 25, 37, 49, 61, 73](../morpheus/domain/default_bi.py#L13) are also English. The LLM-generated variant at [morpheus/clarifier/clarifier.py:202-208](../morpheus/clarifier/clarifier.py#L202-L208) prompts the model in English and never instructs it to reply in the user's language. Confirmation rendering at [morpheus/clarifier/clarifier.py:265](../morpheus/clarifier/clarifier.py#L265) prefixes the user's intent with `"I understood your request:"` regardless of locale.

A non-English user who triggers a clarification gets an English question. They can answer in their own language, but the system has no awareness of the locale switch. Hard coupling, mostly deterministic.

One curiosity worth noting: the denial pattern regex at [morpheus/clarifier/clarifier.py:32-35](../morpheus/clarifier/clarifier.py#L32-L35) recognizes `nein` and `non` alongside `no`/`nope`/`idk`. It is the only place in the codebase that displays awareness of non-English input — a half-measure that suggests the language question has been considered, just not systematically.

The coherence-check tokenizer at [morpheus/parser/coherence.py:55](../morpheus/parser/coherence.py#L55) splits text via `[a-z0-9]{2,}`, which works for Latin-script languages and degrades silently on CJK, Arabic, or scripts without spaces.

### 2.3 Decision engine

The decision engine is the cleanest part of the audit. The value-matching function at [morpheus/decision_engine/engine.py:21-28](../morpheus/decision_engine/engine.py#L21-L28) is case-insensitive string comparison against `match_fields` values declared by the operator. The *logic* is language-agnostic; the *content it compares against* is whatever the operator wrote, which in the default BI and HR domains is English. No coupling in the algorithm, hard coupling in the configuration.

Numeric thresholds (`measure: 0.90`, etc.) are language-independent in form but were calibrated against English examples, so the calibration itself is implicitly English-tuned. This is rarely a runtime issue but is worth flagging.

### 2.4 Control 2 — Level 1 deterministic risk classification

This is the most security-relevant section. The Level 1 layer is the project's headline guarantee: a tool call's risk is determined by code a human can read, not a model.

`RISK_PATTERNS` at [morpheus/proxy/policy_checker.py:37-41](../morpheus/proxy/policy_checker.py#L37-L41) is a dictionary of fnmatch globs against tool *names*: `delete_*`, `remove_*`, `drop_*`, `send_*`, `get_*`, etc. Tool names in any non-English language fall through. `DESCRIPTION_RISK_KEYWORDS` at [morpheus/proxy/policy_checker.py:48-63](../morpheus/proxy/policy_checker.py#L48-L63) is a regex set against tool *descriptions* — `\b(permanently|irreversib|destruct|wipe|erase|nuke|truncat)\w*\b` and similar. A Spanish description such as *"borra los datos de forma irreversible"* matches none of these. The `classify_risk` function at [morpheus/proxy/policy_checker.py:65-84](../morpheus/proxy/policy_checker.py#L65-L84) priorities name-pattern, then description-pattern, then returns `"unknown"`.

The saving grace is at [morpheus/proxy/policy_checker.py:102-127](../morpheus/proxy/policy_checker.py#L102-L127): the `unknown` default rule sets `requires_confirmation=True`. So a non-English tool that escapes classification fails *closed* — high friction, but not insecure. The security claim survives. The UX does not.

Test coverage for this layer ([morpheus/tests/test_layer10_policy_checker.py](../morpheus/tests/test_layer10_policy_checker.py)) is 100% English across roughly 46 test cases.

### 2.5 Control 2 — Level 2 LLM coherence check

The L2 coherence prompt at [morpheus/proxy/policy_checker.py:182-205](../morpheus/proxy/policy_checker.py#L182-L205) is English-only, with structural delimiters and anti-injection framing. Soft coupling: cross-lingual coherence (English instructions + non-English intent or arguments) is slower and less reliable than monolingual coherence, but capable multilingual models handle it. Smaller local models (Ollama with default Mistral) degrade noticeably; the cloud defaults degrade less.

The argument injection sanitizer at [morpheus/proxy/policy_checker.py:215-228](../morpheus/proxy/policy_checker.py#L215-L228) is the more concerning finding. Its 12 regex patterns target English-language injection vocabulary: `"ignore previous"`, `"disregard prior"`, `"you are now"`, `"act as"`, `"pretend"`, `"new instructions"`, etc. A Chinese, Russian, or French equivalent passes through Defense Layer 1 untouched. The LLM coherence check (Defense Layer 3 in the same file) is the secondary line — but it is probabilistic, and pinning the security claim on it alone weakens it. Hard coupling, deterministic, security-critical.

Schema pre-validation at [morpheus/proxy/policy_checker.py:270-289](../morpheus/proxy/policy_checker.py#L270-L289) is language-agnostic except insofar as the schemas themselves embed English enums.

### 2.6 IBAC and the step-name inference fail-open *(security finding)*

This subsection is broken out because it is the single most consequential finding in the audit, and one the multilingual analysis surfaced rather than was sent to find. What we initially identified as a single fail-open path turned out, on closer reading during the fix, to be two coordinated fail-opens — fixing only the first leaves the second intact.

IBAC tuple matching at [morpheus/policies/ibac.py:68-69](../morpheus/policies/ibac.py#L68-L69) is exact string equality on a fixed action vocabulary (`{read, write, execute, delete}` plus the wildcard `*`). The action of a step is *inferred* from its name by [morpheus/policies/ibac.py:304-324](../morpheus/policies/ibac.py#L304-L324): a prefix match against a hard-coded list of English verbs (`fetch_`, `get_`, `read_`, `query_`, `delete_`, `remove_`, `send_`, `create_`, etc.). When no prefix matches:

```python
else:
    action = "execute"
```

`execute` is, in the IBAC vocabulary, the most permissive action — the catch-all for "do something." A non-English step name like `borrar_registros` (Spanish, "delete records") matches no prefix, falls to the `else` branch, and is classified as `execute`. The `delete:*` denial tuples a security-conscious operator may have written to prohibit destructive actions are then never consulted, because the step is no longer a `delete` step from IBAC's perspective. It is an `execute` step — and the operator may have written a permissive `execute:*` allow tuple for routine operations.

That is the first fail-open. The second is at [morpheus/policies/ibac.py:269-273](../morpheus/policies/ibac.py#L269-L273), in `DeterministicEvaluator.evaluate`, and it surprised us. The candidate-list construction is:

```python
step_action, step_resource = self._infer_action_resource(step_name)
candidates = [(step_action, step_resource)]
candidates.append((step_action, step_name))
candidates.append(("execute", step_name))
```

The third entry is unconditional. Even if the inference function were corrected to return a sentinel like `("unknown", "borrar_registros")`, this third candidate `("execute", "borrar_registros")` is still tried against every authorization tuple. An operator with a permissive `execute:*` allow tuple still matches and the step is still authorized. A surface-level fix to the inference function alone is cosmetic; the candidate-list fallback has to go too.

This is a fail-open path. It is not an *intentional* fail-open; it is an artifact of the prefix dictionary being curated against English conventions, the `else` branch picking the wrong default, and an unconditional `execute` fallback in the caller compounding the problem. The fix has to be coordinated: change the inference default to a sentinel that never matches a concrete operator action *and* suppress the `("execute", step_name)` candidate when that sentinel is in play. Wildcard tuples (`*:*`) are intentionally preserved — an operator who writes a true everything-wildcard means it. The fix does not need to wait for any of the multilingual recommendations below; it is a security improvement that the multilingual lens happened to expose.

The test suite at [morpheus/tests/test_layer15_ibac.py](../morpheus/tests/test_layer15_ibac.py) does not exercise this path with non-English step names.

(*Implemented on branch `fix/ibac-action-default` in commits `79bd913`, `9bfd65e`, `a735502`. The complete fix addresses both paths described above and ships with five regression tests covering the English prefix matrix, the non-English fail-closed behavior, the preserved wildcard semantic, the explicit-`requires:` migration path, and the sentinel constant's exposability.*)

### 2.7 Capabilities, audit, configuration

Capability action names across [morpheus/domain/default_bi.py:79-144](../morpheus/domain/default_bi.py#L79-L144) and [morpheus-hr-chatbot-demo/hr_domain.py:90-201](../morpheus-hr-chatbot-demo/hr_domain.py#L90-L201) are English identifiers (`query_chart`, `request_leave`, `delete_leave_requests`). These are not user-facing; they are internal labels that operators write. Hard coupling in form, but the form is appropriate — they are vocabulary, not text.

The audit decision enum at [morpheus/audit/logger.py:260-266](../morpheus/audit/logger.py#L260-L266) is `{approved, blocked, bypassed}`. Reason strings throughout `main.py`, `policy_checker.py`, and `policies/ibac.py` are English f-strings. Soft coupling — the audit log is consumed by SIEMs and operators, not end users. Translating it would break downstream queries.

`README.md`, `docs/`, and `CHANGELOG.md` make no claims about language scope. The implicit assumption is English-only; it is never stated.

## 3. Conceptual frame

It helps to decompose what "multilingual" means in this system before evaluating fixes. Three axes of language exist in Morpheus, and they do not move together:

1. **User input language.** What the human types. LLM-mediated; modern multilingual models handle this reasonably.
2. **Tool/system language.** What the upstream MCP server names and describes its tools as. Set by the tool author. May be English even when users are not.
3. **Configuration language.** What the operator writes in capability definitions, IBAC tuples, and prompts. Set by the Morpheus deployer.

A common deployment shape — and the shape of the originating example — has axis 2 in English (most commercial MCP servers are English-coded), axis 3 in English (operators speak English), and axis 1 in many languages. The most urgent multilingualism is therefore on axis 1. We are not asked to localize tool catalogues or operator vocabularies, only to handle non-English user input gracefully.

A second decomposition: the right fix for security failures differs from the right fix for UX failures. A *security* failure (Level 1 missing a destructive tool because its description is in Japanese) requires a deterministic answer — operators need to read the code and predict the classification. A *UX* failure (a French user receiving an English clarification question) tolerates an LLM-based fix; clarification questions are not security boundaries.

Third: deterministic vs LLM-based components. Deterministic patterns multilingualize via curation, with a maintenance treadmill and a long tail that's never quite complete. LLM components multilingualize for free, with the right model — but adding LLM calls to the deterministic core erodes Morpheus's distinctive property: decisions are made by code, not models.

The recommendations below are organized around these three frames.

## 4. Approaches considered

Six approaches are evaluated. Two are recommended against and recorded for completeness.

### A — Polyglot pattern library

Maintain regex/keyword sets in N languages — top 5–10 by deployment priority — and dispatch by detected language. Effort scales linearly with language count: roughly half a week per Romance/Germanic language for a competent speaker plus reviewer, longer for agglutinative or non-Latin scripts. Strengths: preserves the deterministic, code-readable property. Weaknesses: maintenance treadmill, expertise per language, and surprisingly hard for languages where the imperative-mood markers used in injection vocabulary have rich morphology (Turkish, Japanese, Finnish). Best fit: prompt-injection patterns specifically, where the security guarantee must remain code-readable.

### B — Translate-then-process *(recommended against)*

Detect, translate to English, run the existing pipeline. Minimal code change, but adds latency, cost, and accuracy loss. The deeper problem: a translated injection attempt may have its injection vocabulary stripped or rephrased by the translator itself, defeating both the original detection and the user's intent.

### C — LLM-only Level 1 *(recommended against)*

Replace regex Level 1 with an LLM call. Multilingual for free. Loses determinism — the property the project advertises. Operators can no longer read the policy and predict its behavior.

### D — Multilingual embedding similarity

Use a multilingual sentence-embedding model (`multilingual-e5-large`, LaBSE) to compute similarity between a tool's description and a fixed set of "risk archetype" exemplar sentences. Multilingual without translation. Reproducible given a pinned model and threshold.

The honest caveat: reproducibility is not the same as auditability in the sense Morpheus uses today. With regex, a human reviewer reading a PR can predict the classification of any tool. With embeddings, the answer is "run the model and see"; the decision boundary cannot be reviewed by reading code. This matters for compliance contexts where a SOC2 reviewer may ask why a tool was classified medium and want an answer better than "cosine 0.71 against archetype X." Best fit: a *fallback tier* behind the regex, applied only when the regex returns `unknown`. Effort: 4–6 weeks dominated by archetype curation, threshold calibration, and packaging the model weights into the release artifact (do not fetch at runtime — embedding model deprecation is a supply-chain risk).

### E — Hybrid English-fast-path

Keep the existing English regex on the hot path; route non-English-identified tools to a fallback path with stricter defaults. This is the generic frame; the specialized form (F) is more concrete and is the architecture recommended below.

### F — Layered detection (regex → embedding fallback → confirmation backstop)

Three tiers. (1) Existing regex patterns run first and resolve the great majority of English tools at zero additional cost. (2) On `unknown`, a multilingual embedding similarity check against a fixed set of risk-archetype exemplars resolves most non-English tools. (3) Anything still `unknown` falls through to the existing `requires_confirmation=True` default. Each tier degrades to the next deterministically. The audit log records which tier produced the decision, so a reviewer can filter "decisions made by tier 2 last month" and spot-check them. The English path is unchanged — the typical English-tooled deployment sees zero behavior change. Effort: 4–6 weeks, dominated by tier-2 calibration. This is the recommended L1 architecture.

### G — Schema-declared risk (operator escape hatch)

Add an optional `risk: "high" | "medium" | "low"` field on tool registration. When present, it short-circuits classification. This is not a multilingual solution per se; it is a release valve that makes the multilingual problem opt-out for any operator willing to declare risk explicitly. For a deployment with a finite, known tool catalogue (the typical enterprise integration), this is the cheapest possible win: label once, language stops mattering. Effort: half a week. Strongly recommended as a first-sprint deliverable.

### Explicitly rejected

*Per-tenant language packs.* Tenant-scoped pattern divergence creates an N×M test matrix and a security review surface where each tenant can effectively reduce their own protection. The right unit of language scoping is the deployment, not the tenant.

*Translating the audit decision enum.* The values `{approved, blocked, bypassed}` are machine vocabulary consumed by SIEM queries and downstream tooling. Localizing them would break consumers without helping any user. Named here as a non-goal.

### Deferred

Community-contributed pattern libraries via an MCP-spec extension are interesting long-term but premature. Mention as future work; do not invest now.

## 5. Recommendation

The recommended path is sequenced, not parallel, and lead with the cheapest items because they capture most of the practical value.

**First sprint — quick wins (~half an engineer-week remaining).** The IBAC `_infer_action_resource` fail-open at [morpheus/policies/ibac.py:304-324](../morpheus/policies/ibac.py#L304-L324) is **done** — shipped on branch `fix/ibac-action-default` in commits `79bd913`, `9bfd65e`, `a735502`. The default branch now returns a sentinel `_UNKNOWN_ACTION = "unknown"` that does not match operator-declared action vocabularies, and the second fail-open in `DeterministicEvaluator.evaluate` (the unconditional `("execute", step_name)` candidate, which we caught during Phase 0 of the fix and which the original audit had missed) is suppressed when the sentinel is in play. Wildcard tuples are preserved. The fix is a security improvement rather than a multilingual feature, but the multilingual lens is what surfaced it.

That leaves the schema-declared `risk` field (Approach G) on tool/capability registration as the open first-sprint item — roughly half an engineer-week, capturing most of the *remaining* practical value of multilingual support for a fraction of the total effort.

**Second sprint — the LLM and config fixes (~three weeks).** Parameterize the L2 coherence prompt at [morpheus/proxy/policy_checker.py:182-205](../morpheus/proxy/policy_checker.py#L182-L205) with a `target_language` slot, populated from a language-detection step on the user input. Validate the parameterization on at least the cloud defaults (GPT-4o, Claude Sonnet); document the locales and models the parameterization is validated against, since smaller local models degrade noticeably. In parallel, extend the configuration schema (`FieldDefinition`, `CapabilityDefinition`) with optional per-language fields — `description_by_lang`, `examples_by_lang`, `fallback_question_by_lang` — and update the clarifier and parser to pick the right one given the detected user language. This is a deterministic config change; it does not affect the security boundary, only the UX.

**Third sprint — polyglot injection patterns (~three weeks).** Curate the `_ARG_INJECTION_PATTERNS` regex set at [morpheus/proxy/policy_checker.py:215-228](../morpheus/proxy/policy_checker.py#L215-L228) for an explicit, declared set of priority languages — Spanish, French, German, Portuguese, Japanese is a reasonable starting commitment for a globally distributed enterprise deployment. This is real linguistic work, not translation; involve a native speaker reviewer per language. Acknowledge in the documentation that the long tail is unsolved; commit to a finite list rather than to "multilingual support" as an open obligation.

**Last — layered detection (~four to six weeks).** Implement Approach F as the sustained answer to L1 risk classification on non-English tool descriptions. Vendor the embedding model weights into the Morpheus release artifact; do not fetch at runtime. Calibrate the tier-2 threshold per language; record the chosen thresholds in a versioned configuration file rather than in code, so they can be tuned without a release. Integrate the audit log to record which tier produced each decision.

Each step strengthens the system's posture without making the next harder, and each is independently shippable. A team that runs out of budget after sprint 2 has still meaningfully improved the system; a team that runs out after sprint 3 has a credible multilingual security story for its declared languages; only sprint 4 is the open-ended generalization.

## 6. What this analysis does not address

- **Right-to-left scripts and bidirectional text rendering.** Hebrew, Arabic, Persian, and Urdu introduce rendering and tokenization concerns that are out of scope here.
- **Mixed-language inputs and code-switching.** A query that switches mid-sentence between English and another language is a separate research problem; language detection on a per-utterance basis is not robust at sub-sentence granularity.
- **Locale-aware number, date, and currency formatting.** These are presentation concerns, not authorization concerns.
- **Audit-enum localization.** Named as a non-goal in §4. Decision enums are machine vocabulary.
- **Confidence threshold recalibration per language.** The thresholds at [morpheus/domain/default_bi.py:9-76](../morpheus/domain/default_bi.py#L9-L76) were calibrated against English examples. Per-language recalibration is a follow-on study, not part of this analysis.

## 7. Open questions for the team

1. **Priority languages.** "Multilingual" is not a set; it is whichever languages a deployment actually serves. The recommendations above assume a finite list. What is that list, ranked, for the originating deployment?
2. **Tool-description editability.** Approach G (schema-declared risk) is most powerful when the operator controls the tool catalogue. To what extent are tool descriptions in the upstream MCP servers operator-editable, versus fixed by the upstream maintainer?
3. **Compliance posture on embedding-based classification.** A SOC2 or equivalent reviewer asking "why was this tool classified medium?" expects a deterministic, auditable answer. Approach D / F provides a reproducible answer ("cosine similarity 0.71 against archetype X above a 0.65 threshold"), which is not the same kind of artifact. Is that answer acceptable in the target compliance contexts, or is the deterministic regex tier the only legally defensible classifier?
4. **Embedding model lifecycle policy.** If `multilingual-e5-large` is deprecated by its publisher mid-deployment, what is the operator's expected migration path? This influences whether to vendor weights into the release, freeze a fork, or commit to a model-rotation cadence.
5. **Validation corpus.** The test suite has zero non-English inputs. Building a multilingual regression corpus is itself a project — who curates it, and against what fluency standard?

---

This analysis surfaced one fail-open path in IBAC that has since been fixed independently of the broader multilingual roadmap (commits `79bd913`, `9bfd65e`, `a735502` on `fix/ibac-action-default`). The remaining work in §5 — schema-declared risk, L2 prompt parameterization, polyglot injection patterns, layered detection — is open and tracked as part of Morpheus's roadmap.
