from domain.config import DomainConfig, FieldDefinition, CapabilityDefinition


BI_FIELDS = [
    FieldDefinition(
        name="measure",
        label="\U0001f4ca Measure",
        description="the metric being queried",
        threshold=0.90,
        weight=0.4,
        priority=1,
        default_value=None,
        fallback_question="Which metric do you want to see? (e.g. revenue, orders, margin)",
        examples=["revenue", "orders", "margin"],
        ambiguity_threshold=0.15,
    ),
    FieldDefinition(
        name="time_range",
        label="\U0001f4c5 Period",
        description="the time period",
        threshold=0.85,
        weight=0.3,
        priority=2,
        default_value=None,
        fallback_question="What time period are you interested in? (e.g. Q1 2025, last 30 days, January 2025)",
        examples=["Q1 2025", "last 30 days", "January 2025"],
        ambiguity_threshold=0.15,
    ),
    FieldDefinition(
        name="dimension",
        label="\U0001f50e Dimension",
        description="how data should be grouped",
        threshold=0.80,
        weight=0.15,
        priority=4,
        default_value=None,
        fallback_question="How do you want to group the data? (e.g. by region, by product, by customer)",
        examples=["by region", "by product", "by customer"],
        ambiguity_threshold=0.12,
    ),
    FieldDefinition(
        name="filters",
        label="\U0001f50d Filters",
        description="any filtering conditions",
        threshold=0.80,
        weight=0.1,
        priority=3,
        default_value=None,
        fallback_question="Do you want to filter the data? (e.g. online channel only, enterprise segment)",
        examples=["online channel only", "enterprise segment"],
        ambiguity_threshold=0.12,
    ),
    FieldDefinition(
        name="granularity",
        label="\U0001f9ee Granularity",
        description="the time granularity",
        threshold=0.70,
        weight=0.05,
        priority=5,
        default_value="monthly",
        fallback_question="What level of detail? (e.g. daily, weekly, monthly)",
        examples=["daily", "weekly", "monthly"],
        ambiguity_threshold=0.10,
    ),
    FieldDefinition(
        name="comparison",
        label="\U0001f4c8 Comparison",
        description="any comparison reference",
        threshold=0.60,
        weight=0.0,
        priority=6,
        default_value=None,
        fallback_question="Do you want to compare with another period or segment? (e.g. vs last year, vs budget)",
        examples=["vs Q1 2024", "vs last year", "vs budget"],
        ambiguity_threshold=0.10,
    ),
]

BI_CAPABILITIES = [
    CapabilityDefinition(
        action="query_chart",
        field_weights={
            "measure":     1.0,
            "time_range":  0.8,
            "dimension":   0.3,
            "filters":     0.2,
            "granularity": 0.15,
            "comparison":  0.0,
        },
        min_score=0.6,
        authorized_tuples=[
            {"action": "read", "resource": "chart:{measure}", "required_fields": ["measure"]},
            {"action": "read", "resource": "data:*"},
        ],
    ),
    CapabilityDefinition(
        action="export_csv",
        field_weights={
            "measure":     1.0,
            "time_range":  0.8,
            "filters":     0.3,
            "dimension":   0.0,
            "granularity": 0.0,
            "comparison":  0.0,
        },
        min_score=0.7,
        authorized_tuples=[
            {"action": "read", "resource": "data:*"},
            {"action": "write", "resource": "export:*"},
        ],
    ),
    CapabilityDefinition(
        action="save_dashboard",
        field_weights={
            "measure":     1.0,
            "time_range":  0.8,
            "dimension":   0.7,
            "filters":     0.2,
            "granularity": 0.15,
            "comparison":  0.0,
        },
        min_score=0.7,
        authorized_tuples=[
            {"action": "read", "resource": "data:*"},
            {"action": "write", "resource": "dashboard:*"},
        ],
    ),
    CapabilityDefinition(
        action="compare_periods",
        field_weights={
            "measure":     1.0,
            "time_range":  0.8,
            "comparison":  0.9,
            "dimension":   0.3,
            "filters":     0.2,
            "granularity": 0.0,
        },
        min_score=0.7,
        authorized_tuples=[
            {"action": "read", "resource": "data:*"},
            {"action": "read", "resource": "comparison:*"},
        ],
    ),
]

BI_EXECUTION_PLANS = {
    "query_chart": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2, "requires": "read:data"},
        {"step": "render_chart",        "type": "pure",        "timeout_ms": 3000,  "retry": 0},
    ],
    "export_csv": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2, "requires": "read:data"},
        {"step": "format_csv",          "type": "pure",        "timeout_ms": 1000,  "retry": 0},
        {"step": "export_file",         "type": "side_effect", "timeout_ms": 5000,  "retry": 1, "requires": "write:export"},
    ],
    "save_dashboard": [
        {"step": "resolve_time_range",  "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_query",     "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_query",       "type": "side_effect", "timeout_ms": 10000, "retry": 2, "requires": "read:data"},
        {"step": "render_chart",        "type": "pure",        "timeout_ms": 3000,  "retry": 0},
        {"step": "save_to_dashboard",   "type": "side_effect", "timeout_ms": 5000,  "retry": 1, "requires": "write:dashboard"},
    ],
    "compare_periods": [
        {"step": "resolve_time_ranges", "type": "pure",        "timeout_ms": 500,   "retry": 0},
        {"step": "build_sql_queries",   "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "execute_queries",     "type": "side_effect", "timeout_ms": 15000, "retry": 2, "requires": "read:data"},
        {"step": "compute_comparison",  "type": "pure",        "timeout_ms": 2000,  "retry": 0},
        {"step": "render_comparison",   "type": "pure",        "timeout_ms": 3000,  "retry": 0},
    ],
}

BI_PARSER_PROMPT = """\
You are a BI query intent parser. Your task is to extract structured intent from a natural language business intelligence query.

For every query, extract these {field_count} fields. Each field is a list of hypotheses sorted by confidence (highest first).

Fields:
{field_definitions}

Each hypothesis has this format:
{{"value": string or null, "confidence": float between 0.0 and 1.0}}

Rules:
- Never invent values not present or implied by the query
- Never omit fields — always include all {field_count} even if null
- If a field is unclear or not mentioned: {{"value": null, "confidence": 0.1}}
- Output must be strict JSON only — no markdown, no explanation, no preamble
- Do not wrap the JSON in code fences or add any text before or after it

Example 1 — Vague input:
User: "how are we doing?"
{{
  "measure": [{{"value": null, "confidence": 0.1}}],
  "dimension": [{{"value": null, "confidence": 0.1}}],
  "time_range": [{{"value": null, "confidence": 0.15}}],
  "filters": [{{"value": null, "confidence": 0.1}}],
  "granularity": [{{"value": null, "confidence": 0.1}}],
  "comparison": [{{"value": null, "confidence": 0.1}}]
}}

Example 2 — Partial input:
User: "revenue Q1 by region"
{{
  "measure": [{{"value": "revenue", "confidence": 0.95}}],
  "dimension": [{{"value": "by region", "confidence": 0.92}}],
  "time_range": [{{"value": "Q1", "confidence": 0.75}}],
  "filters": [{{"value": null, "confidence": 0.1}}],
  "granularity": [{{"value": null, "confidence": 0.15}}],
  "comparison": [{{"value": null, "confidence": 0.1}}]
}}

Example 3 — Well-formed input:
User: "monthly sales Q1 2025 by region, online channel only, comparison vs Q1 2024"
{{
  "measure": [{{"value": "sales", "confidence": 0.97}}],
  "dimension": [{{"value": "by region", "confidence": 0.95}}],
  "time_range": [{{"value": "Q1 2025", "confidence": 0.98}}],
  "filters": [{{"value": "online channel only", "confidence": 0.93}}],
  "granularity": [{{"value": "monthly", "confidence": 0.96}}],
  "comparison": [{{"value": "vs Q1 2024", "confidence": 0.97}}]
}}

Now parse the following user query. Output ONLY the JSON object.

User: "{user_input}\""""

BI_VALIDATION_PROMPT = (
    "Is this a structurally coherent intent with at least the key fields "
    "({field_names}) present and non-null?\n\n{intent_text}\n\n"
    "Answer ONLY with YES or NO, nothing else."
)

DEFAULT_BI_CONFIG = DomainConfig(
    name="generic_bi",
    domain_description="Business Intelligence query parsing",
    fields=BI_FIELDS,
    capabilities=BI_CAPABILITIES,
    execution_plans=BI_EXECUTION_PLANS,
    parser_prompt_template=BI_PARSER_PROMPT,
    validation_prompt_template=BI_VALIDATION_PROMPT,
    clarification_policy={
        "max_iterations": 3,
        "ask_one_field_at_a_time": True,
        "fallback_on_max_iterations": "reject",
    },
)
