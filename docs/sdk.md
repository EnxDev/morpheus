# Python SDK

## Installation

The SDK is included in the `morpheus` package. No additional installation needed.

## Quick Start

```python
from morpheus.sdk import MorpheusClient

client = MorpheusClient()  # defaults to http://localhost:8000

# Health check
print(client.health())  # True

# Parse a query
result = client.parse("Show me revenue by region for Q1 2025")
print(result.intent)
print(result.low_confidence)

# Clarify a field
if result.low_confidence:
    updated = client.clarify(
        intent=result.intent,
        field=result.low_confidence[0],
        answer="monthly",
    )
    print(updated.intent)

# Decide on action
decision = client.decide(intent=result.intent)
print(decision.action)
print(decision.score)
```

## API

### MorpheusClient

```python
MorpheusClient(base_url="http://localhost:8000", timeout=30)
```

#### Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `parse(query, domain=None)` | `ParseResult` | Parse a query into intent |
| `clarify(intent, field, answer, domain=None)` | `ClarifyResult` | Clarify a field |
| `decide(intent, domain=None)` | `DecisionResult` | Select action |
| `get_audit(last_n=50)` | `list[AuditEvent]` | Get audit events |
| `get_audit_summary()` | `dict` | Get event type counts |
| `export_audit(fmt="json")` | `str` | Export full log as JSON or CSV |
| `list_domains()` | `dict` | List registered domains |
| `register_domain(config)` | `dict` | Register a new domain |
| `get_controls()` | `ControlConfig` | Get control state |
| `set_controls(...)` | `ControlConfig` | Update controls |
| `health()` | `bool` | Health check |

### Types

```python
from morpheus.sdk.types import (
    ParseResult,      # intent, low_confidence, valid, errors
    ClarifyResult,    # intent, low_confidence
    DecisionResult,   # action, score, explained, audit_log, action_validation, plan_review
    AuditEvent,       # timestamp, user, event_type, decision, controls_active, ...
    ControlConfig,    # input_validation, action_validation, coherence_check
)

# IBAC types (for direct integration)
from morpheus.policies.ibac import (
    AuthorizationTuple,     # principal:action#resource with constraints
    TupleTemplate,          # template for generating tuples from intent
    IntentPolicyMapper,     # intent → authorization tuples
    DeterministicEvaluator, # default tuple evaluator (no external deps)
    TupleEvaluator,         # Protocol for Cedar/OPA adapters
)

# Plan Review
from morpheus.execution.review import PlanReviewer, PlanReviewResult
```

## FastAPI Middleware

Auto-validate incoming requests to your FastAPI app:

```python
from fastapi import FastAPI
from morpheus.sdk.adapters import MorpheusMiddleware

app = FastAPI()
app.add_middleware(
    MorpheusMiddleware,
    morpheus_url="http://localhost:8000",
    protected_routes=["/api/query", "/api/export"],
    domain="generic_bi",
    query_field="query",
)

@app.post("/api/query")
async def query(data: dict):
    # Only reached if Morpheus validates the request
    return {"result": "ok"}
```

The middleware:
- Only intercepts POST requests to protected routes
- Extracts the query from the request body
- Validates via Morpheus parse endpoint
- Blocks invalid requests with 422 status
- Passes valid requests through unchanged
