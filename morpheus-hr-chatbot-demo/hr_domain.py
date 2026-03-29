"""
HR Assistant — Morpheus domain configuration.

Registers a custom 'hr_assistant' domain with Intent Guard so that
employee queries about leave, payroll, attendance and org-chart are
parsed, validated and controlled through the standard pipeline.
"""

HR_DOMAIN_CONFIG = {
    "name": "hr_assistant",
    "domain_description": "HR self-service assistant for employees — leave, payroll, attendance, org-chart",

    # ── Intent fields ────────────────────────────────────────────────
    "fields": [
        {
            "name": "action_type",
            "label": "🎯 Action",
            "description": "what the employee wants to do (view, request, approve, cancel, export)",
            "threshold": 0.85,
            "weight": 0.35,
            "priority": 1,
            "default_value": "view",
            "fallback_question": "What would you like to do? (view data, request leave, approve requests, export report)",
            "examples": ["view", "request_leave", "approve", "cancel", "export"],
            "ambiguity_threshold": 0.15,
        },
        {
            "name": "data_subject",
            "label": "👤 Subject",
            "description": "about whom — the employee themselves, a team, or a specific person",
            "threshold": 0.80,
            "weight": 0.20,
            "priority": 2,
            "default_value": "self",
            "fallback_question": "Who does this request refer to? (yourself, your team, a specific person)",
            "examples": ["self", "my team", "Mario Rossi", "all employees"],
            "ambiguity_threshold": 0.12,
        },
        {
            "name": "hr_category",
            "label": "📂 Category",
            "description": "the HR data category being queried",
            "threshold": 0.85,
            "weight": 0.25,
            "priority": 3,
            "default_value": None,
            "fallback_question": "Which HR category are you interested in? (leave, payroll, attendance, org chart, benefits)",
            "examples": ["leave", "payroll", "attendance", "org_chart", "benefits"],
            "ambiguity_threshold": 0.15,
        },
        {
            "name": "time_range",
            "label": "📅 Time range",
            "description": "the time period of the request",
            "threshold": 0.75,
            "weight": 0.10,
            "priority": 4,
            "default_value": "current_month",
            "fallback_question": "For which time period? (this month, Q1 2025, next week, current year)",
            "examples": ["this month", "Q1 2025", "next week", "current year"],
            "ambiguity_threshold": 0.12,
        },
        {
            "name": "filters",
            "label": "🔍 Filters",
            "description": "any filtering conditions (department, contract type, status)",
            "threshold": 0.70,
            "weight": 0.05,
            "priority": 5,
            "default_value": "none",
            "fallback_question": "Do you want to filter by department, contract type, or status? (e.g. Engineering only, full-time only)",
            "examples": ["Engineering department", "full-time only", "pending requests"],
            "ambiguity_threshold": 0.10,
        },
        {
            "name": "output_format",
            "label": "📊 Format",
            "description": "desired output format",
            "threshold": 0.60,
            "weight": 0.05,
            "priority": 6,
            "default_value": "text",
            "fallback_question": "What format do you want the result in? (text, table, CSV, PDF)",
            "examples": ["text", "table", "csv", "pdf"],
            "ambiguity_threshold": 0.10,
        },
    ],

    # ── Capabilities ─────────────────────────────────────────────────
    "capabilities": [
        {
            "action": "query_leave_balance",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 0.8,
                "hr_category": 1.0,
                "time_range": 0.5,
                "filters": 0.1,
                "output_format": 0.0,
            },
            "match_fields": {
                "action_type": "view",
                "hr_category": "leave",
            },
            "min_score": 0.6,
        },
        {
            "action": "request_leave",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 0.9,
                "hr_category": 1.0,
                "time_range": 0.9,
                "filters": 0.0,
                "output_format": 0.0,
            },
            "match_fields": {
                "action_type": ["request_leave", "request"],
                "hr_category": "leave",
            },
            "min_score": 0.7,
        },
        {
            "action": "approve_leave",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 1.0,
                "hr_category": 0.8,
                "time_range": 0.3,
                "filters": 0.2,
                "output_format": 0.0,
            },
            "match_fields": {
                "action_type": "approve",
                "hr_category": "leave",
            },
            "min_score": 0.7,
        },
        {
            "action": "query_payroll",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 0.9,
                "hr_category": 1.0,
                "time_range": 0.7,
                "filters": 0.2,
                "output_format": 0.3,
            },
            "match_fields": {
                "action_type": "view",
                "hr_category": ["payroll", "salary"],
            },
            "min_score": 0.6,
        },
        {
            "action": "query_attendance",
            "field_weights": {
                "action_type": 0.8,
                "data_subject": 0.9,
                "hr_category": 1.0,
                "time_range": 0.7,
                "filters": 0.2,
                "output_format": 0.2,
            },
            "match_fields": {
                "action_type": "view",
                "hr_category": "attendance",
            },
            "min_score": 0.6,
        },
        {
            "action": "export_report",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 0.5,
                "hr_category": 0.8,
                "time_range": 0.7,
                "filters": 0.3,
                "output_format": 1.0,
            },
            "match_fields": {
                "action_type": "export",
            },
            "min_score": 0.7,
        },
        {
            "action": "delete_leave_requests",
            "field_weights": {
                "action_type": 1.0,
                "data_subject": 1.0,
                "hr_category": 1.0,
                "time_range": 0.5,
                "filters": 0.3,
                "output_format": 0.0,
            },
            "match_fields": {
                "action_type": ["cancel", "delete"],
                "hr_category": "leave",
            },
            "min_score": 0.7,
        },
    ],

    # ── Execution plans ──────────────────────────────────────────────
    "execution_plans": {
        "query_leave_balance": [
            {"step": "identify_employee", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "fetch_leave_balance", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
            {"step": "format_response", "type": "pure", "timeout_ms": 500, "retry": 0},
        ],
        "request_leave": [
            {"step": "identify_employee", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "check_balance", "type": "side_effect", "timeout_ms": 3000, "retry": 1},
            {"step": "check_conflicts", "type": "side_effect", "timeout_ms": 3000, "retry": 1},
            {"step": "submit_request", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
            {"step": "notify_manager", "type": "side_effect", "timeout_ms": 3000, "retry": 2},
        ],
        "approve_leave": [
            {"step": "identify_request", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "verify_authority", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "update_status", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
            {"step": "notify_employee", "type": "side_effect", "timeout_ms": 3000, "retry": 2},
        ],
        "query_payroll": [
            {"step": "identify_employee", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "verify_access", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "fetch_payroll_data", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
            {"step": "format_response", "type": "pure", "timeout_ms": 500, "retry": 0},
        ],
        "query_attendance": [
            {"step": "identify_employee", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "fetch_attendance", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
            {"step": "format_response", "type": "pure", "timeout_ms": 500, "retry": 0},
        ],
        "export_report": [
            {"step": "build_query", "type": "pure", "timeout_ms": 1000, "retry": 0},
            {"step": "fetch_data", "type": "side_effect", "timeout_ms": 10000, "retry": 2},
            {"step": "format_export", "type": "pure", "timeout_ms": 3000, "retry": 0},
            {"step": "deliver_file", "type": "side_effect", "timeout_ms": 5000, "retry": 1},
        ],
        "delete_leave_requests": [
            {"step": "identify_scope", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "verify_authority", "type": "pure", "timeout_ms": 500, "retry": 0},
            {"step": "delete_records", "type": "side_effect", "timeout_ms": 5000, "retry": 0},
            {"step": "log_deletion", "type": "side_effect", "timeout_ms": 1000, "retry": 1},
        ],
    },

    # ── Parser prompt ────────────────────────────────────────────────
    "parser_prompt_template": (
        "You are an HR assistant intent parser. Extract structured intent from employee HR queries.\n\n"
        "For every query, extract these {field_count} fields. Each field is a list of hypotheses sorted by confidence (highest first).\n\n"
        "Fields:\n{field_definitions}\n\n"
        'Each hypothesis: {"value": string or null, "confidence": float 0.0-1.0}\n\n'
        "Rules:\n"
        "- Never invent values not in the query\n"
        "- Never omit fields — always include all {field_count}\n"
        '- If a field is unclear: {"value": null, "confidence": 0.1}\n'
        "- Output strict JSON only — no markdown, no explanation\n\n"
        'Example — Vague: "how many days do I have left?"\n'
        '{\n'
        '  "action_type": [{"value": "view", "confidence": 0.80}],\n'
        '  "data_subject": [{"value": "self", "confidence": 0.92}],\n'
        '  "hr_category": [{"value": "leave", "confidence": 0.55}, {"value": "attendance", "confidence": 0.30}],\n'
        '  "time_range": [{"value": "current_year", "confidence": 0.60}],\n'
        '  "filters": [{"value": null, "confidence": 0.1}],\n'
        '  "output_format": [{"value": "text", "confidence": 0.70}]\n'
        '}\n\n'
        'Example — Clear: "I want to request 3 days of vacation from April 14 to 16"\n'
        '{\n'
        '  "action_type": [{"value": "request_leave", "confidence": 0.97}],\n'
        '  "data_subject": [{"value": "self", "confidence": 0.95}],\n'
        '  "hr_category": [{"value": "leave", "confidence": 0.98}],\n'
        '  "time_range": [{"value": "14-16 April", "confidence": 0.96}],\n'
        '  "filters": [{"value": null, "confidence": 0.1}],\n'
        '  "output_format": [{"value": "text", "confidence": 0.70}]\n'
        '}\n\n'
        'Now parse:\nUser: "{user_input}"'
    ),

    "validation_prompt_template": (
        "Is this a structurally coherent HR intent with at least the key fields "
        "({field_names}) present and non-null?\n\n{intent_text}\n\n"
        "Answer ONLY with YES or NO."
    ),

    # ── Clarification policy ─────────────────────────────────────────
    "clarification_policy": {
        "max_iterations": 3,
        "ask_one_field_at_a_time": True,
        "fallback_on_max_iterations": "reject",
    },
}
