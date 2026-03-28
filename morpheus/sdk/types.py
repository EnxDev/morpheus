"""Pydantic v2 models matching API contracts."""

from __future__ import annotations

from pydantic import BaseModel


class ParseResult(BaseModel):
    intent: dict
    low_confidence: list[str]
    valid: bool
    errors: list[str]


class ClarifyResult(BaseModel):
    intent: dict
    low_confidence: list[str]


class DecisionResult(BaseModel):
    action: str | None
    score: float
    explained: dict
    audit_log: list[dict]


class AuditEvent(BaseModel):
    timestamp: str
    user: str = "system"
    event_type: str
    payload: dict = {}
    decision: str | None = None
    level_1_result: dict | None = None
    level_2_result: dict | None = None
    controls_active: dict[str, bool] = {
        "input_validation": True,
        "action_validation": True,
        "coherence_check": True,
    }
    policy_applied: str | None = None


class ControlConfig(BaseModel):
    input_validation: bool
    action_validation: bool
    coherence_check: bool
