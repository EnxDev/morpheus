from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from domain.config import DomainConfig
from domain.registry import DomainRegistry

STEP_TYPES = {
    "pure":        "safe, recomputable, no side effects",
    "reversible":  "can be undone",
    "side_effect": "irreversible (e.g. email export, save)",
}


def build_plan(action: str, config: DomainConfig | None = None) -> list[dict]:
    if config is None:
        config = DomainRegistry.default()
    plans = config.execution_plans
    if action not in plans:
        raise ValueError(f"Unknown action: {action}")
    return [dict(step) for step in plans[action]]


# Backwards compatibility
PLANS = {
    "query_chart": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2},
        {"step": "render_chart",        "type": "pure",        "timeout_ms": 3000,  "retry": 0},
    ],
    "export_csv": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2},
        {"step": "format_csv",          "type": "pure",        "timeout_ms": 1000,  "retry": 0},
        {"step": "export_file",         "type": "side_effect", "timeout_ms": 5000,  "retry": 1},
    ],
    "save_dashboard": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2},
        {"step": "render_chart",        "type": "pure",        "timeout_ms": 3000,  "retry": 0},
        {"step": "save_to_dashboard",   "type": "side_effect", "timeout_ms": 5000,  "retry": 1},
    ],
    "compare_periods": [
        {"step": "resolve_time_ranges", "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_queries",   "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_queries",     "type": "side_effect", "timeout_ms": 15000, "retry": 2},
        {"step": "compute_comparison",  "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "render_comparison",   "type": "pure",        "timeout_ms": 3000,  "retry": 0},
    ],
}
