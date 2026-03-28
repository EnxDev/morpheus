"""
Intent Guard — MCP Server

Exposes the Intent Guard pipeline as MCP tools that any compatible client
(Claude Desktop, VS Code, Cursor, etc.) can call.

Run with:
    cd morpheus && python mcp_server.py

Or configure in Claude Desktop's config:
    {
      "mcpServers": {
        "intent-guard": {
          "command": "python",
          "args": ["/absolute/path/to/morpheus/mcp_server.py"]
        }
      }
    }
"""

import sys
from pathlib import Path
from uuid import uuid4

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastmcp import FastMCP
from intent.schema import DynamicIntent, INTENT_FIELDS
from parser.parser import parse
from validator.validator import validate
from policies.confidence_policy import check
from clarifier.clarifier import update_intent, generate_question, get_next_field
from decision_engine.engine import select_action
from execution.plan import build_plan
from execution.engine import execute_plan
from execution.review import PlanReviewer
from audit.logger import AuditLogger
from controls import ControlManager
from proxy.policy_checker import PolicyChecker

mcp = FastMCP(
    "Intent Guard",
    instructions=(
        "You are a BI query assistant. Use these tools to understand what the user wants to query, "
        "clarify any ambiguous fields, and decide what action to take.\n\n"
        "Workflow:\n"
        "1. When the user asks a BI question, call parse_query first\n"
        "2. If there are low_confidence fields, ask the user about them one at a time, "
        "   then call clarify_field for each answer\n"
        "3. Once all fields are resolved (or the user says to proceed), call decide_action\n"
        "4. Present the result to the user"
    ),
)

logger = AuditLogger()
control_manager = ControlManager(logger=logger)
policy_checker = PolicyChecker()
plan_reviewer = PlanReviewer()

# Session-based intent storage (keyed by session_id)
# Each parse_query call creates a new session and returns the session_id.
# Subsequent calls (clarify_field, decide_action) must pass the same session_id.
_sessions: dict[str, dict] = {}
_MAX_SESSIONS = 100  # Prevent unbounded growth


def _cleanup_sessions() -> None:
    """Remove oldest sessions if we exceed the cap."""
    while len(_sessions) > _MAX_SESSIONS:
        oldest_key = next(iter(_sessions))
        del _sessions[oldest_key]


@mcp.tool()
def parse_query(query: str) -> dict:
    """Parse a natural language BI query into structured intent.

    Call this first when a user asks a business intelligence question.
    Returns the parsed intent with confidence scores per field,
    a list of low-confidence fields that need clarification,
    and validation results.

    IMPORTANT: The response includes a session_id. Pass this session_id
    to clarify_field and decide_action calls.

    Example queries:
    - "show me revenue by region"
    - "monthly sales Q1 2025 online only"
    - "compare orders this year vs last year"
    """
    session_id = str(uuid4())
    intent = parse(query)
    result = validate(intent)
    low = check(intent)

    _sessions[session_id] = intent.to_dict()
    _cleanup_sessions()

    logger.log("mcp_parse", {"session_id": session_id, "query": query, "low_confidence": low})

    # Build a readable summary
    summary = {}
    for field in INTENT_FIELDS:
        top = intent.top(field)
        hyps = getattr(intent, field)
        conf = hyps[0].confidence if hyps else 0.0
        summary[field] = {"value": top, "confidence": conf}

    # Generate questions for low-confidence fields
    questions = {}
    for field in low:
        questions[field] = generate_question(field)

    return {
        "session_id": session_id,
        "intent": summary,
        "low_confidence": low,
        "next_to_clarify": get_next_field(low),
        "questions": questions,
        "valid": result.is_valid,
        "errors": result.errors,
    }


@mcp.tool()
def clarify_field(session_id: str, field: str, answer: str) -> dict:
    """Update a specific field of the current intent with the user's answer.

    Call this after asking the user about a low-confidence field.
    Pass the session_id returned by parse_query.
    The field parameter must be one of: measure, dimension, time_range,
    filters, granularity, comparison.

    Returns the updated intent and any remaining low-confidence fields.
    """
    if session_id not in _sessions:
        return {"error": "No active intent. Call parse_query first."}

    intent = DynamicIntent.from_dict(_sessions[session_id], INTENT_FIELDS)
    updated, answer_val = update_intent(intent, field, answer)

    if not answer_val.valid:
        return {"error": answer_val.reason, "field": field, "valid": False}

    _sessions[session_id] = updated.to_dict()

    low = check(updated)
    logger.log("mcp_clarify", {"field": field, "answer": answer, "remaining_low": low})

    summary = {}
    for f in INTENT_FIELDS:
        top = updated.top(f)
        hyps = getattr(updated, f)
        conf = hyps[0].confidence if hyps else 0.0
        summary[f] = {"value": top, "confidence": conf}

    questions = {}
    for f in low:
        questions[f] = generate_question(f)

    return {
        "intent": summary,
        "low_confidence": low,
        "next_to_clarify": get_next_field(low),
        "questions": questions,
    }


@mcp.tool()
def decide_action(session_id: str) -> dict:
    """Decide what action to take based on the current intent.

    Call this after all fields are resolved or the user wants to proceed.
    Pass the session_id returned by parse_query.
    Returns the selected action, confidence score, and execution plan results.

    Possible actions: query_chart, export_csv, save_dashboard, compare_periods.
    """
    if session_id not in _sessions:
        return {"error": "No active intent. Call parse_query first."}

    intent = DynamicIntent.from_dict(_sessions[session_id], INTENT_FIELDS)
    result = validate(intent)

    if not result.is_valid:
        return {
            "error": "Intent is not valid",
            "details": result.errors,
        }

    action = select_action(intent)
    if action is None:
        logger.log("mcp_decide", {"action": None})
        return {
            "action": None,
            "message": "No suitable action found for this intent. Try providing more details.",
        }

    action_name = action["action"]
    score = action["score"]
    explained = action["explained"]  # pre-computed by select_action()

    # ── Control 2: Action Validation ─────────────────────────────────
    controls = control_manager.get_controls()
    action_decision = policy_checker.check_action(
        tool_name=action_name,
        arguments=explained,
        original_intent=_sessions.get(session_id),
        controls_active=controls.to_dict(),
    )

    logger.log("mcp_action_validated", {
        "action": action_name,
        "decision": action_decision.status,
        "reason": action_decision.reason,
        "risk_level": action_decision.risk_level,
    })

    if action_decision.status == "blocked":
        return {
            "action": action_name,
            "score": round(score, 4),
            "blocked": True,
            "block_reason": action_decision.reason,
            "risk_level": action_decision.risk_level,
            "message": f"Action '{action_name}' was blocked by Control 2: {action_decision.reason}",
        }

    # ── Plan Review: is this plan safe for this intent? ────────────
    plan = build_plan(action_name)  # uses default config
    review = plan_reviewer.review(plan, action_name, _sessions.get(session_id))

    logger.log("mcp_plan_reviewed", {
        "action": action_name,
        "approved": review.approved,
        "issues": [i.to_dict() for i in review.issues],
    })

    if review.blocked:
        return {
            "action": action_name,
            "score": round(score, 4),
            "blocked": True,
            "block_reason": f"Plan blocked: {review.issues[0].description}" if review.issues else "Plan review failed",
            "plan_review": review.to_dict(),
            "message": f"Execution plan for '{action_name}' was blocked by plan review.",
        }

    # ── Execute plan (action approved, plan approved) ────────────────
    exec_logger = AuditLogger()
    success = execute_plan(plan, exec_logger)

    logger.log("mcp_decide", {
        "action": action_name,
        "score": score,
        "success": success,
        "control_2_status": action_decision.status,
    })

    # Build readable intent summary
    summary = {}
    for f in INTENT_FIELDS:
        summary[f] = intent.top(f) or "—"

    return {
        "action": action_name,
        "score": round(score, 4),
        "explained": explained,
        "intent_summary": summary,
        "execution_success": success,
        "execution_log": exec_logger.get_log(),
        "action_validation": {
            "status": action_decision.status,
            "reason": action_decision.reason,
            "risk_level": action_decision.risk_level,
        },
        "plan_review": review.to_dict(),
    }


@mcp.tool()
def get_audit_log(last_n: int = 20) -> dict:
    """Get the recent audit log entries.

    Useful for debugging or reviewing what happened in the pipeline.
    """
    return {
        "events": logger.last(last_n),
        "summary": logger.summary(),
    }


if __name__ == "__main__":
    mcp.run()
