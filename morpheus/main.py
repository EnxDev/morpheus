import json
import os
import sys
from pathlib import Path
from uuid import uuid4

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")


from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from intent.schema import DynamicIntent
from parser.parser import parse
from parser.sanitizer import sanitize
from parser.session_guard import SessionGuard
from validator.validator import validate, ValidationResult
from policies.confidence_policy import check
from clarifier.clarifier import update_intent
from decision_engine.engine import select_action
from execution.plan import build_plan
from execution.engine import execute_plan
from execution.review import PlanReviewer
from audit.logger import AuditLogger, FileAuditSink, ConsoleAuditSink
from domain.registry import DomainRegistry
from domain.config import DomainConfig
from controls import ControlManager
from proxy.policy_checker import PolicyChecker
from policies.ibac import IntentPolicyMapper, DeterministicEvaluator, TupleTemplate

app = FastAPI(title="Intent Guard")

# Policy checker for Control 2 (action validation)
_policy_checker = PolicyChecker()
_plan_reviewer = PlanReviewer()
_ibac_mapper = IntentPolicyMapper()
_ibac_evaluator = DeterministicEvaluator()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Response size guard ───────────────────────────────────────────────────────
# Protects LLM context windows from oversized responses (~100KB limit)
MAX_RESPONSE_BYTES = 100 * 1024  # 100KB


class ResponseSizeGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Only check JSON API responses, not file downloads
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_RESPONSE_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Response too large",
                        "detail": f"Response exceeds {MAX_RESPONSE_BYTES} bytes. "
                                  "Try reducing the query scope or adding filters.",
                    },
                )
        return response


app.add_middleware(ResponseSizeGuard)

# Configure audit sinks based on environment
_audit_sinks = [ConsoleAuditSink()]
_audit_file = os.environ.get("MORPHEUS_AUDIT_FILE")
if _audit_file:
    _audit_sinks.append(FileAuditSink(_audit_file))

logger = AuditLogger(sinks=_audit_sinks)
control_manager = ControlManager(logger=logger)

# Session guards for cross-iteration anomaly detection in clarification loop
_session_guards: dict[str, SessionGuard] = {}


def _get_config(domain: str | None = None) -> DomainConfig:
    if domain:
        try:
            return DomainRegistry.get(domain)
        except KeyError:
            registered = DomainRegistry.list_domains()
            raise HTTPException(
                status_code=404,
                detail=f"Domain '{domain}' not registered. Available domains: {registered}",
            )
    return DomainRegistry.default()


# ─── Request / Response Models ────────────────────────────────────────────────

class ParseRequest(BaseModel):
    query: str = Field(max_length=10000)
    domain: str | None = Field(default=None, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')

class ParseResponse(BaseModel):
    intent: dict
    low_confidence: list[str]
    valid: bool
    errors: list[str]
    suspicious: bool = False
    sanitizer_flags: list[str] = []

class ClarifyRequest(BaseModel):
    intent: dict
    field: str = Field(max_length=100)
    answer: str = Field(max_length=10000)
    domain: str | None = Field(default=None, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    session_id: str | None = Field(default=None, max_length=200)

class ClarifyResponse(BaseModel):
    intent: dict
    low_confidence: list[str]

class DecideRequest(BaseModel):
    intent: dict
    domain: str | None = Field(default=None, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')
    session_id: str | None = Field(default=None, max_length=200)
    original_query: str | None = Field(default=None, max_length=10000)

class DecideResponse(BaseModel):
    action: str | None
    score: float
    explained: dict
    audit_log: list[dict]
    action_validation: dict | None = None  # Control 2 result (if enabled)
    plan_review: dict | None = None  # Plan review result (if plan was built)

class RegisterDomainRequest(BaseModel):
    config: dict

class ControlsRequest(BaseModel):
    input_validation: bool | None = None
    action_validation: bool | None = None
    coherence_check: bool | None = None
    reason: str = ""

class ControlsResponse(BaseModel):
    input_validation: bool
    action_validation: bool
    coherence_check: bool


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.post("/api/parse", response_model=ParseResponse)
async def api_parse(req: ParseRequest):
    config = _get_config(req.domain)
    request_id = str(uuid4())
    logger.log("input_received", {"request_id": request_id, "domain": config.name},
               policy_applied="input_sanitizer")

    # ── Input sanitization (prompt injection defense) ────────────────
    sanitization = sanitize(req.query)
    if sanitization.is_suspicious:
        logger.log("input_suspicious", {
            "request_id": request_id,
            "flags": sanitization.flags,
            "blocked": sanitization.blocked,
        }, policy_applied="input_sanitizer")
    if sanitization.blocked:
        raise HTTPException(status_code=400, detail="Input blocked by safety filter")

    try:
        intent = parse(req.query, config)
    except Exception as e:
        logger.log("parse_failed", {"request_id": request_id, "error": str(e)})
        raise HTTPException(status_code=502, detail="LLM parse service unavailable")

    logger.log("intent_parsed", {"request_id": request_id})

    controls = control_manager.get_controls()

    if controls.input_validation:
        result = validate(intent, config)
        low = check(intent, config)
        decision = "approved"
    else:
        result = ValidationResult(is_valid=True)
        low = []
        decision = "bypassed"

    logger.log("confidence_checked", {
        "request_id": request_id,
        "low_confidence": low,
        "decision": decision,
        "controls_active": controls.to_dict(),
    }, policy_applied="confidence_policy" if controls.input_validation else "bypassed")

    return ParseResponse(
        intent=intent.to_dict(),
        low_confidence=low,
        valid=result.is_valid,
        errors=result.errors,
        suspicious=sanitization.is_suspicious,
        sanitizer_flags=sanitization.flags,
    )


@app.post("/api/clarify", response_model=ClarifyResponse)
async def api_clarify(req: ClarifyRequest):
    config = _get_config(req.domain)
    request_id = str(uuid4())

    # ── Sanitize the answer (same defense as parse) ──────────────────
    answer_sanitization = sanitize(req.answer)
    if answer_sanitization.blocked:
        logger.log("clarification_blocked", {
            "request_id": request_id,
            "field": req.field,
            "flags": answer_sanitization.flags,
        })
        raise HTTPException(status_code=400, detail="Answer blocked by safety filter")

    intent = DynamicIntent.from_dict(req.intent, config.field_names)
    updated, answer_validation = update_intent(intent, req.field, req.answer, config)

    if not answer_validation.valid:
        logger.log("clarification_rejected", {
            "request_id": request_id,
            "field": req.field,
            "answer": req.answer,
            "reason": answer_validation.reason,
        })
        raise HTTPException(status_code=422, detail=answer_validation.reason)

    # ── Cross-iteration anomaly detection ────────────────────────────
    guard_key = req.session_id or request_id
    if guard_key not in _session_guards:
        _session_guards[guard_key] = SessionGuard()
    guard = _session_guards[guard_key]
    guard.record_iteration(updated, req.field, req.answer)
    anomalies = guard.check_anomalies()

    if anomalies:
        logger.log("clarification_anomaly", {
            "request_id": request_id,
            "anomalies": [
                {"field": a.field, "type": a.anomaly_type, "description": a.description}
                for a in anomalies
            ],
        })

    logger.log("clarification_resolved", {"request_id": request_id, "field": req.field})

    low = check(updated, config)

    return ClarifyResponse(
        intent=updated.to_dict(),
        low_confidence=low,
    )


@app.post("/api/decide", response_model=DecideResponse)
async def api_decide(req: DecideRequest):
    config = _get_config(req.domain)
    request_id = str(uuid4())
    intent = DynamicIntent.from_dict(req.intent, config.field_names)

    # Validate all fields are present
    for fd in config.fields:
        hyps = intent.get_hypotheses(fd.name)
        if not isinstance(hyps, list) or len(hyps) == 0:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid intent: field '{fd.name}' is missing or empty",
            )

    controls = control_manager.get_controls()

    # ── Cumulative session coherence check ────────────────────────────
    # If we have the original query and a session with clarification history,
    # verify the final intent is still traceable to legitimate sources
    # (original input + all clarification answers).
    if req.session_id and req.original_query and req.session_id in _session_guards:
        guard = _session_guards[req.session_id]
        session_anomalies = guard.check_session_coherence(req.original_query)
        if session_anomalies:
            logger.log("session_coherence_failed", {
                "request_id": request_id,
                "session_id": req.session_id,
                "anomalies": [
                    {"field": a.field, "type": a.anomaly_type, "description": a.description}
                    for a in session_anomalies
                ],
            })
            # Demote incoherent fields to confidence 0.0
            for anomaly in session_anomalies:
                from intent.schema import Hypothesis
                intent.set_hypotheses(anomaly.field, [Hypothesis(value=None, confidence=0.0)])

    result = select_action(intent, config)
    if result is None:
        logger.log("decision_made", {
            "request_id": request_id,
            "action": None,
            "decision": "no_match",
            "controls_active": controls.to_dict(),
        }, policy_applied="decision_engine")
        return DecideResponse(action=None, score=0.0, explained={}, audit_log=logger.last(5))

    action_name = result["action"]

    # ── Control 2: Action Validation ─────────────────────────────────────
    # Run the selected action through the policy checker with the
    # validated intent, so we can verify coherence before execution.
    action_decision = _policy_checker.check_action(
        tool_name=action_name,
        arguments=result.get("explained", {}),
        original_intent=req.intent,
        controls_active=controls.to_dict(),
    )

    logger.log("action_validated", {
        "request_id": request_id,
        "action": action_name,
        "decision": action_decision.status,
        "reason": action_decision.reason,
        "risk_level": action_decision.risk_level,
        "controls_active": controls.to_dict(),
        "policy_applied": action_decision.policy_applied,
    })

    if action_decision.status == "blocked":
        return DecideResponse(
            action=action_name,
            score=result["score"],
            explained=result["explained"],
            audit_log=logger.last(5),
            action_validation={
                "status": "blocked",
                "reason": action_decision.reason,
                "risk_level": action_decision.risk_level,
            },
        )

    # ── Build and review plan before execution ──────────────────────────
    plan = build_plan(action_name, config)

    review = _plan_reviewer.review(plan, action_name, req.intent)
    logger.log("plan_reviewed", {
        "request_id": request_id,
        "action": action_name,
        "approved": review.approved,
        "issues": [i.to_dict() for i in review.issues],
        "summary": review.plan_summary,
    })

    if review.blocked:
        return DecideResponse(
            action=action_name,
            score=result["score"],
            explained=result["explained"],
            audit_log=logger.last(5),
            action_validation={
                "status": action_decision.status,
                "reason": action_decision.reason,
                "risk_level": action_decision.risk_level,
            },
            plan_review=review.to_dict(),
        )

    # ── IBAC: Authorization tuple enforcement ──────────────────────────
    # Generate authorization tuples from the validated intent
    # and verify each execution step against them.
    capability = None
    for cap in config.capabilities:
        if cap.action == action_name:
            capability = cap
            break

    ibac_result = None
    if capability and capability.authorized_tuples:
        # Build intent values and confidences
        intent_values = {}
        intent_confs = {}
        for fname in config.field_names:
            intent_values[fname] = intent.top(fname)
            hyps = intent.get_hypotheses(fname)
            intent_confs[fname] = hyps[0].confidence if hyps else 0.0

        templates = [
            TupleTemplate(
                action=t["action"],
                resource=t["resource"],
                constraints=t.get("constraints", {}),
                required_fields=t.get("required_fields", []),
            )
            for t in capability.authorized_tuples
        ]

        mapping = _ibac_mapper.map(
            intent_values=intent_values,
            intent_confidences=intent_confs,
            templates=templates,
            thresholds=config.thresholds,
            principal="system",
            action_name=action_name,
        )

        logger.log("ibac_tuples_generated", {
            "request_id": request_id,
            "action": action_name,
            "tuple_count": len(mapping.tuples),
            "errors": [{"field": e.field_name, "reason": e.reason} for e in mapping.errors],
        })

        if mapping.has_errors:
            return DecideResponse(
                action=action_name,
                score=result["score"],
                explained=result["explained"],
                audit_log=logger.last(5),
                action_validation={
                    "status": "blocked",
                    "reason": f"IBAC: cannot resolve authorization tuples — {mapping.errors[0].reason}",
                    "risk_level": "high",
                },
                plan_review=review.to_dict(),
            )

        # Verify each step against tuples
        blocked_steps = []
        for step in plan:
            step_result = _ibac_evaluator.evaluate(mapping.tuples, step)
            if not step_result.allowed:
                blocked_steps.append(step_result)

        if blocked_steps:
            logger.log("ibac_step_blocked", {
                "request_id": request_id,
                "blocked_steps": [s.to_dict() for s in blocked_steps],
            })
            return DecideResponse(
                action=action_name,
                score=result["score"],
                explained=result["explained"],
                audit_log=logger.last(5),
                action_validation={
                    "status": "blocked",
                    "reason": f"IBAC: step '{blocked_steps[0].step_name}' has no authorization — {blocked_steps[0].reason}",
                    "risk_level": "high",
                },
                plan_review=review.to_dict(),
            )

        ibac_result = mapping.to_dict()

    # ── Execute plan (all gates passed) ──────────────────────────────────
    logger.log("decision_made", {
        "request_id": request_id,
        "action": action_name,
        "decision": action_decision.status,
        "controls_active": controls.to_dict(),
        "ibac_tuples": ibac_result,
    }, policy_applied=action_decision.policy_applied or "decision_engine")

    plan_logger = AuditLogger()
    plan_logger.log("execution_started", {"request_id": request_id, "action": action_name})
    execute_plan(plan, plan_logger)
    plan_logger.log("execution_finished", {"request_id": request_id})

    return DecideResponse(
        action=action_name,
        score=result["score"],
        explained=result["explained"],
        audit_log=plan_logger.get_log(),
        action_validation={
            "status": action_decision.status,
            "reason": action_decision.reason,
            "risk_level": action_decision.risk_level,
        },
        plan_review=review.to_dict(),
    )


@app.post("/api/domains/register")
async def api_register_domain(req: RegisterDomainRequest):
    try:
        config = DomainConfig.from_dict(req.config)
        DomainRegistry.register(config)
        return {"status": "ok", "domain": config.name, "fields": list(config.field_names)}
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid domain config: {e}")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid domain configuration")


@app.delete("/api/domains/{name}")
async def api_delete_domain(name: str):
    try:
        DomainRegistry.delete(name)
        return {"status": "ok", "deleted": name}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Domain '{name}' not found")


@app.get("/api/domains")
async def api_list_domains():
    # Ensure default is loaded
    DomainRegistry.default()
    domains = {}
    for name in DomainRegistry.list_domains():
        config = DomainRegistry.get(name)
        domains[name] = {
            "description": config.domain_description,
            "fields": [
                {
                    "name": fd.name,
                    "label": fd.label,
                    "description": fd.description,
                    "threshold": fd.threshold,
                    "ambiguity_threshold": fd.ambiguity_threshold,
                }
                for fd in config.fields
            ],
            "capabilities": [cap.action for cap in config.capabilities],
        }
    return domains


@app.get("/api/controls", response_model=ControlsResponse)
async def api_get_controls():
    controls = control_manager.get_controls()
    return ControlsResponse(
        input_validation=controls.input_validation,
        action_validation=controls.action_validation,
        coherence_check=controls.coherence_check,
    )


@app.post("/api/controls", response_model=ControlsResponse)
async def api_set_controls(req: ControlsRequest):
    controls = control_manager.set_controls(
        input_validation=req.input_validation,
        action_validation=req.action_validation,
        coherence_check=req.coherence_check,
        reason=req.reason,
    )
    return ControlsResponse(
        input_validation=controls.input_validation,
        action_validation=controls.action_validation,
        coherence_check=controls.coherence_check,
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/audit")
async def audit(last_n: int = Query(default=50, ge=1, le=1000)):
    return logger.last(last_n)


@app.get("/audit/summary")
async def audit_summary():
    return logger.summary()


@app.get("/audit/export")
async def audit_export(format: str = Query(default="json")):
    if format == "csv":
        return PlainTextResponse(
            content=logger.export_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit.csv"},
        )
    return JSONResponse(content=json.loads(logger.export_json()))
