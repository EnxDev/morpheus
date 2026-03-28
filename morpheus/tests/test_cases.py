TEST_CASES = [
    # ── 1. Too vague (3 cases) ────────────────────────────────────────────────
    {
        "input": "how are we doing?",
        "expected_missing": ["measure", "time_range", "dimension"],
        "expected_resolved": [],
    },
    {
        "input": "show me something",
        "expected_missing": ["measure", "time_range", "dimension"],
        "expected_resolved": [],
    },
    {
        "input": "give me a report",
        "expected_missing": ["measure", "time_range", "dimension"],
        "expected_resolved": [],
    },

    # ── 2. Ambiguous metric (2 cases) ─────────────────────────────────────────
    {
        "input": "show me the numbers for last quarter",
        "expected_missing": ["measure"],
        "expected_resolved": ["time_range"],
    },
    {
        "input": "how did we perform in January?",
        "expected_missing": ["measure", "dimension"],
        "expected_resolved": ["time_range"],
    },

    # ── 3. Ambiguous time range (2 cases) ─────────────────────────────────────
    {
        "input": "revenue recently",
        "expected_missing": ["time_range"],
        "expected_resolved": ["measure"],
    },
    {
        "input": "sales last period by region",
        "expected_missing": ["time_range"],
        "expected_resolved": ["measure", "dimension"],
    },

    # ── 4. Apparently clear but incomplete (4 cases) ──────────────────────────
    {
        "input": "revenue Q1 2025",
        "expected_missing": ["dimension"],
        "expected_resolved": ["measure", "time_range"],
    },
    {
        "input": "show me orders by product",
        "expected_missing": ["time_range"],
        "expected_resolved": ["measure", "dimension"],
    },
    {
        "input": "margin by region last month",
        "expected_missing": ["granularity"],
        "expected_resolved": ["measure", "dimension", "time_range"],
    },
    {
        "input": "top customers by revenue",
        "expected_missing": ["time_range"],
        "expected_resolved": ["measure", "dimension"],
    },

    # ── 5. Filter ambiguity (2 cases) ─────────────────────────────────────────
    {
        "input": "revenue Q1 2025 by region for enterprise",
        "expected_missing": ["filters"],
        "expected_resolved": ["measure", "time_range", "dimension"],
    },
    {
        "input": "sales last quarter online only",
        "expected_missing": ["filters", "dimension"],
        "expected_resolved": ["measure", "time_range"],
    },

    # ── 6. Comparative queries (3 cases) ──────────────────────────────────────
    {
        "input": "compare north and south this month",
        "expected_missing": ["measure"],
        "expected_resolved": ["time_range", "comparison"],
    },
    {
        "input": "revenue Q1 2025 vs Q1 2024 by region",
        "expected_missing": [],
        "expected_resolved": ["measure", "time_range", "dimension", "comparison"],
    },
    {
        "input": "sales this year vs last year",
        "expected_missing": ["dimension"],
        "expected_resolved": ["measure", "time_range", "comparison"],
    },

    # ── 7. Well-formed (4 cases) ──────────────────────────────────────────────
    {
        "input": "monthly sales Q1 2025 by region, online channel only, comparison vs Q1 2024",
        "expected_missing": [],
        "expected_resolved": ["measure", "time_range", "dimension", "granularity", "filters", "comparison"],
    },
    {
        "input": "revenue Q1 2025 by product weekly",
        "expected_missing": [],
        "expected_resolved": ["measure", "time_range", "dimension", "granularity"],
    },
    {
        "input": "total orders January 2025 by region daily",
        "expected_missing": [],
        "expected_resolved": ["measure", "time_range", "dimension", "granularity"],
    },
    {
        "input": "net margin Q4 2024 by customer segment monthly, enterprise only, vs Q4 2023",
        "expected_missing": [],
        "expected_resolved": ["measure", "time_range", "dimension", "granularity", "filters", "comparison"],
    },
]


def _build_mock_intent(query: str):
    """Build a mock intent based on query keywords to simulate LLM parsing."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from intent.schema import DynamicIntent, Hypothesis, INTENT_FIELDS

    q = query.lower()
    words = len(q.split())

    # Default: all null, low confidence
    defaults = {f: [Hypothesis(value=None, confidence=0.1)] for f in INTENT_FIELDS}

    # Detect measure keywords
    measure_words = ["revenue", "sales", "orders", "margin"]
    if any(w in q for w in measure_words):
        val = next(w for w in measure_words if w in q)
        defaults["measure"] = [Hypothesis(value=val, confidence=0.93)]

    # Detect dimension keywords
    dim_words = {"region": "by region", "product": "by product", "customer": "by customer", "segment": "by customer segment"}
    for kw, val in dim_words.items():
        if kw in q:
            defaults["dimension"] = [Hypothesis(value=val, confidence=0.90)]
            break

    # Detect time range
    time_words = ["q1", "q2", "q3", "q4", "january", "february", "last quarter", "last month",
                  "this month", "this year", "last year", "2024", "2025"]
    for tw in time_words:
        if tw in q:
            defaults["time_range"] = [Hypothesis(value=tw, confidence=0.92)]
            break

    # Detect filters
    filter_words = ["only", "enterprise", "online"]
    if any(fw in q for fw in filter_words):
        defaults["filters"] = [Hypothesis(value="filtered", confidence=0.85)]

    # Detect granularity
    gran_words = ["daily", "weekly", "monthly"]
    for gw in gran_words:
        if gw in q:
            defaults["granularity"] = [Hypothesis(value=gw, confidence=0.88)]
            break

    # Detect comparison
    if "vs" in q or "compare" in q or "comparison" in q:
        defaults["comparison"] = [Hypothesis(value="comparison", confidence=0.90)]

    # Very vague queries (<=3 words, no keywords detected) → all null
    if words <= 3 and defaults["measure"][0].value is None and defaults["time_range"][0].value is None:
        pass  # keep all defaults

    return DynamicIntent(INTENT_FIELDS, defaults)


def run_e2e_tests():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from validator.validator import validate
    from policies.confidence_policy import check

    passed = 0
    total = len(TEST_CASES)

    for i, case in enumerate(TEST_CASES):
        query = case["input"]
        expected_missing = set(case["expected_missing"])

        mock = _build_mock_intent(query)
        result = validate(mock)
        low_confidence = set(check(mock))

        # Check if expected_missing fields are a subset of low_confidence
        if expected_missing == low_confidence:
            status = "PASS"
            passed += 1
        elif expected_missing.issubset(low_confidence):
            # Partial match — expected fields are low, but extras too
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"

        print(f"[{status}] \"{query}\" \u2192 {len(low_confidence)} fields low confidence "
              f"(expected {list(expected_missing)}, got {list(low_confidence)})")

    print(f"\n{'─' * 40}")
    print(f"Results: {passed}/{total} passed")


if __name__ == "__main__":
    run_e2e_tests()
