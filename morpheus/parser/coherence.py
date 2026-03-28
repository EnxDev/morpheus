"""Parser output coherence check — deterministic, no LLM.

Verifies that the intent extracted by the parser is semantically consistent
with the original user input. Catches cases where a manipulated parser
produces structurally valid intent that has nothing to do with what the user said.

This is a lexical check: do the key values in the parsed intent appear
(or have close variants) in the original input text?

Example:
    Input: "show me revenue by region for Q1 2025"
    Intent: {"measure": "revenue", "dimension": "by region", "time_range": "Q1 2025"}
    → COHERENT (all values traceable to input)

    Input: "show me revenue by region"
    Intent: {"measure": "delete_database", "dimension": "all_users"}
    → INCOHERENT (values not in input)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from intent.schema import DynamicIntent


@dataclass
class CoherenceResult:
    """Result of parser output coherence check."""

    is_coherent: bool
    score: float  # 0.0 (fully incoherent) to 1.0 (fully coherent)
    incoherent_fields: list[str]  # fields whose values can't be traced to input
    details: dict[str, str]  # field → explanation

    def to_dict(self) -> dict:
        return {
            "is_coherent": self.is_coherent,
            "score": round(self.score, 2),
            "incoherent_fields": self.incoherent_fields,
            "details": self.details,
        }


def _normalize(text: str) -> str:
    """Normalize text for comparison: lowercase, strip, collapse whitespace."""
    return re.sub(r'\s+', ' ', text.lower().strip())


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens (2+ chars) from text."""
    normalized = _normalize(text)
    # Split on non-alphanumeric, keep tokens of 2+ chars
    tokens = re.findall(r'[a-z0-9]{2,}', normalized)
    return set(tokens)


def _value_traceable(value: str, input_tokens: set[str], input_normalized: str) -> bool:
    """Check if a parsed value can be traced back to the original input.

    A value is traceable if:
    1. It appears as a substring in the input (exact or close match), OR
    2. Most of its tokens appear in the input tokens
    """
    if not value or not value.strip():
        return True  # null/empty values are always "traceable"

    val_normalized = _normalize(value)

    # Direct substring match (most common case)
    if val_normalized in input_normalized:
        return True

    # Token overlap: at least 50% of value tokens must appear in input
    val_tokens = _tokenize(value)
    if not val_tokens:
        return True

    overlap = val_tokens & input_tokens
    ratio = len(overlap) / len(val_tokens)
    return ratio >= 0.5


def check_coherence(
    original_input: str,
    intent: DynamicIntent,
    min_score: float = 0.5,
    known_values: dict[str, list[str]] | None = None,
) -> CoherenceResult:
    """Check if parsed intent values are traceable to the original input.

    Returns CoherenceResult with per-field analysis.
    A field is incoherent if its top value cannot be found in/derived from
    the original input text and is not a known domain value.

    Args:
        original_input: the raw user query
        intent: the parsed DynamicIntent
        min_score: minimum coherence score to consider the intent valid (0.0-1.0)
        known_values: optional dict mapping field names to lists of known valid
            values from the domain config (e.g. examples, default values).
            Values in this set are always considered traceable.
    """
    input_normalized = _normalize(original_input)
    input_tokens = _tokenize(original_input)
    known_values = known_values or {}

    incoherent: list[str] = []
    details: dict[str, str] = {}
    checked = 0
    passed = 0

    for field in intent.field_names:
        top_value = intent.top(field)
        if top_value is None:
            continue  # null fields don't count

        checked += 1

        # Check against known domain values first
        field_known = {_normalize(v) for v in known_values.get(field, [])}
        if _normalize(top_value) in field_known:
            passed += 1
            details[field] = f"'{top_value}' is a known domain value"
        elif _value_traceable(top_value, input_tokens, input_normalized):
            passed += 1
            details[field] = f"'{top_value}' traceable in input"
        else:
            incoherent.append(field)
            details[field] = f"'{top_value}' NOT found in input or known values"

    score = passed / checked if checked > 0 else 1.0

    return CoherenceResult(
        is_coherent=score >= min_score and len(incoherent) == 0,
        score=score,
        incoherent_fields=incoherent,
        details=details,
    )
