# API Reference

Base URL: `http://localhost:8000`

## POST /api/parse

Parse a user query into structured intent.

**Request:**
```json
{
  "query": "Show me revenue by region for Q1 2025",
  "domain": null
}
```

`domain` is optional. Defaults to the built-in `generic_bi` domain.

**Response (200):**
```json
{
  "intent": {
    "measure": [{"value": "revenue", "confidence": 0.95}],
    "dimension": [{"value": "by region", "confidence": 0.88}],
    "time_range": [{"value": "Q1 2025", "confidence": 0.96}],
    "filters": [{"value": null, "confidence": 0.1}],
    "granularity": [{"value": null, "confidence": 0.1}],
    "comparison": [{"value": null, "confidence": 0.1}]
  },
  "low_confidence": ["filters", "granularity", "comparison"],
  "suspicious": false,
  "sanitizer_flags": [],
  "valid": true,
  "errors": []
}
```

**Error (400):** Input blocked by safety filter.

**Error (502):** LLM call failed.

When `input_validation` control is disabled, validation and confidence checks are skipped. The decision is logged as `"bypassed"`.

## POST /api/clarify

Clarify a low-confidence field with a user answer.

**Request:**
```json
{
  "intent": {"measure": [{"value": "revenue", "confidence": 0.95}], "...": "..."},
  "field": "filters",
  "answer": "online only",
  "domain": null,
  "session_id": null
}
```

**Response (200):**
```json
{
  "intent": {"...updated intent..."},
  "low_confidence": []
}
```

The clarified field confidence depends on answer validation:
- Exact match with known example → `0.95`
- Partial match → `0.90`
- Token overlap → `0.85`
- LLM-validated → `0.85`
- No match but meaningful text → `0.70`
- Garbage input → `422` rejected
- Denial ("no", "skip") → field skipped (uses default or above-threshold null)

## POST /api/decide

Select action based on validated intent.

**Request:**
```json
{
  "intent": {"...full intent dict..."},
  "domain": null,
  "session_id": null,
  "original_query": null
}
```

**Response (200):**
```json
{
  "action": "query_chart",
  "score": 0.85,
  "explained": {"measure": 0.95, "time_range": 0.96},
  "audit_log": [{"event_type": "execution_started", "...": "..."}],
  "action_validation": {"status": "approved", "reason": "...", "risk_level": "low"},
  "plan_review": {"approved": true, "issue_count": 0, "plan_summary": {"total_steps": 4}}
}
```

The response includes:
- `action_validation` — Control 2 result (risk classification + coherence check)
- `plan_review` — structural and constraint checks on the execution plan
- If IBAC tuples are configured, steps without matching tuples are blocked

`action` is `null` if no capability meets its minimum score.

**Error (422):** Intent has missing or empty fields.

## GET /api/controls

Get current control toggle state.

**Response (200):**
```json
{
  "input_validation": true,
  "action_validation": true,
  "coherence_check": true
}
```

## POST /api/controls

Update control toggles. Only provided fields are changed.

**Request:**
```json
{
  "input_validation": false,
  "action_validation": null,
  "coherence_check": null,
  "reason": "testing without validation"
}
```

**Response (200):**
```json
{
  "input_validation": false,
  "action_validation": true,
  "coherence_check": true
}
```

Every state change is logged to the audit trail with previous and new state.

## POST /api/domains/register

Register a custom domain configuration.

**Request:**
```json
{
  "config": {
    "name": "my_domain",
    "domain_description": "My custom domain",
    "fields": [
      {
        "name": "action",
        "label": "Action",
        "description": "What the user wants to do",
        "threshold": 0.8,
        "weight": 0.5,
        "priority": 1,
        "fallback_question": "What action would you like?",
        "examples": ["create report", "send email"]
      }
    ],
    "capabilities": [
      {
        "action": "create_report",
        "field_weights": {"action": 1.0},
        "min_score": 0.6
      }
    ],
    "execution_plans": {
      "create_report": [
        {"step": "build", "type": "pure", "timeout_ms": 500, "retry": 0}
      ]
    }
  }
}
```

**Response (200):**
```json
{"status": "ok", "domain": "my_domain", "fields": ["action"]}
```

## GET /api/domains

List all registered domains.

**Response (200):**
```json
{
  "generic_bi": {
    "description": "Business Intelligence query parsing for Apache Superset",
    "fields": [
      {"name": "measure", "label": "Measure", "description": "...", "threshold": 0.8, "ambiguity_threshold": 0.5},
      {"name": "time_range", "label": "Time Range", "description": "...", "threshold": 0.8, "ambiguity_threshold": 0.5},
      {"name": "dimension", "label": "Dimension", "description": "...", "threshold": 0.7, "ambiguity_threshold": 0.5},
      {"name": "filters", "label": "Filters", "description": "...", "threshold": 0.7, "ambiguity_threshold": 0.5},
      {"name": "granularity", "label": "Granularity", "description": "...", "threshold": 0.7, "ambiguity_threshold": 0.5},
      {"name": "comparison", "label": "Comparison", "description": "...", "threshold": 0.7, "ambiguity_threshold": 0.5}
    ],
    "capabilities": ["query_chart", "export_csv", "save_dashboard", "compare_periods"]
  }
}
```

## GET /audit

Returns last 50 audit events.

**Response (200):** Array of audit event objects, each containing:

```json
{
  "timestamp": "2026-03-26T12:00:00+00:00",
  "user": "system",
  "event_type": "intent_parsed",
  "payload": {},
  "decision": "approved",
  "level_1_result": null,
  "level_2_result": null,
  "controls_active": {"input_validation": true, "action_validation": true, "coherence_check": true},
  "policy_applied": null
}
```

## GET /audit/summary

Returns event count by type.

**Response (200):**
```json
{"input_received": 5, "intent_parsed": 5, "confidence_checked": 5, "decision_made": 2}
```

## GET /audit/export?format=json

Full audit log as JSON array download.

## GET /audit/export?format=csv

Full audit log as CSV download with headers: `timestamp, user, event_type, decision, policy_applied, level_1_result, level_2_result, controls_active, payload`.

## DELETE /api/domains/{name}

Delete a registered domain by name.

**Response (200):**
```json
{"status": "ok", "deleted": "my_domain"}
```

**Error (404):** Domain not found.

## GET /health

**Response (200):**
```json
{"status": "ok"}
```
