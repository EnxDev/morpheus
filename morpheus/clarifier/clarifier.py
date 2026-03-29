from __future__ import annotations

import re
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from intent.schema import DynamicIntent, Hypothesis
from domain.config import DomainConfig, FieldDefinition
from domain.registry import DomainRegistry
from llm import get_default_provider

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# ── Answer validation ────────────────────────────────────────────────────────

@dataclass
class AnswerValidation:
    """Result of validating a clarification answer."""
    valid: bool
    reason: str
    confidence: float  # how confident we are in this answer (0.0-0.95)


MIN_ANSWER_LENGTH = 2
DENIAL_PATTERNS = re.compile(
    r"^(no|nope|nah|nein|non|skip|none|nothing|not sure|idk|dunno|pass|n/a|na|-|—)$",
    re.IGNORECASE,
)


def validate_answer(answer: str, field_def: FieldDefinition) -> AnswerValidation:
    """Validate a clarification answer against the field definition.

    Checks:
    1. Not empty or too short (noise like "ss", "x", "a")
    2. Not a denial/skip response ("no", "skip", "none")
    3. Similarity to known examples (if available)

    Returns confidence 0.95 for strong matches, lower for weak ones,
    and valid=False for garbage input.
    """
    stripped = answer.strip()

    # Empty or whitespace-only
    if not stripped:
        return AnswerValidation(valid=False, reason="Empty answer", confidence=0.0)

    # Too short to be meaningful (but allow "Q1", "no", etc.)
    if len(stripped) < MIN_ANSWER_LENGTH:
        return AnswerValidation(
            valid=False,
            reason=f"Answer too short ({len(stripped)} chars) — please provide a meaningful response",
            confidence=0.0,
        )

    # Denial / skip patterns → treat as "field unresolved"
    if DENIAL_PATTERNS.match(stripped):
        return AnswerValidation(
            valid=True,
            reason="User declined to answer",
            confidence=0.0,  # Will be treated as unresolved
        )

    # Check against known examples (if the field has them)
    if field_def.examples:
        answer_lower = stripped.lower()

        # Exact match with an example
        example_lower = [e.lower() for e in field_def.examples]
        if answer_lower in example_lower:
            return AnswerValidation(
                valid=True,
                reason=f"Exact match with known value",
                confidence=0.95,
            )

        # Partial match: answer is a substring of an example or vice versa
        for ex in example_lower:
            if answer_lower in ex or ex in answer_lower:
                return AnswerValidation(
                    valid=True,
                    reason=f"Partial match with known value '{ex}'",
                    confidence=0.90,
                )

        # Token overlap: at least one meaningful word from examples
        answer_tokens = set(answer_lower.split())
        example_tokens = set()
        for ex in example_lower:
            example_tokens.update(ex.split())
        # Remove very short tokens
        answer_tokens = {t for t in answer_tokens if len(t) >= 2}
        example_tokens = {t for t in example_tokens if len(t) >= 2}

        if answer_tokens and example_tokens:
            overlap = answer_tokens & example_tokens
            if overlap:
                return AnswerValidation(
                    valid=True,
                    reason=f"Token overlap with known values: {overlap}",
                    confidence=0.85,
                )

        # No match at all with examples — ask LLM if this is a valid answer
        if len(stripped) >= 3:
            llm_valid = _llm_validate_answer(stripped, field_def)
            if llm_valid is not None:
                return llm_valid
            # LLM unavailable — accept with low confidence
            return AnswerValidation(
                valid=True,
                reason="No match with known values, but answer seems meaningful",
                confidence=0.70,
            )

        # Short and no match — likely noise
        return AnswerValidation(
            valid=False,
            reason=f"Answer '{stripped}' doesn't match any expected values. "
                   f"Examples: {', '.join(field_def.examples[:5])}",
            confidence=0.0,
        )

    # No examples defined — accept if length is reasonable
    if len(stripped) >= 3:
        return AnswerValidation(valid=True, reason="Accepted (no examples to validate against)", confidence=0.85)

    return AnswerValidation(
        valid=False,
        reason=f"Answer too short and no known values to validate against",
        confidence=0.0,
    )


def _llm_validate_answer(answer: str, field_def: FieldDefinition) -> AnswerValidation | None:
    """Ask the LLM if an answer is semantically valid for a field.

    Only called when deterministic matching gives low confidence.
    Returns None if LLM is unavailable (graceful degradation).
    The LLM returns YES/NO — it proposes, the threshold decides.
    """
    try:
        prompt = (
            f"Is '{answer}' a valid answer for a field that represents: {field_def.description}?\n"
            f"Known valid values include: {', '.join(field_def.examples[:6])}\n"
            f"Answer ONLY with YES or NO."
        )
        response = get_default_provider().generate(prompt).strip().upper()
        if response.startswith("YES"):
            return AnswerValidation(
                valid=True,
                reason=f"LLM validated: '{answer}' is a valid {field_def.name}",
                confidence=0.85,
            )
        elif response.startswith("NO"):
            return AnswerValidation(
                valid=False,
                reason=f"'{answer}' is not a valid value for {field_def.label}. "
                       f"Examples: {', '.join(field_def.examples[:4])}",
                confidence=0.0,
            )
    except Exception:
        pass  # LLM unavailable — fall through to deterministic
    return None


# ── Core clarifier functions ─────────────────────────────────────────────────

def get_next_field(low_confidence_fields: list[str], config: DomainConfig | None = None) -> str | None:
    if config is None:
        config = DomainRegistry.default()
    for field in config.field_priority:
        if field in low_confidence_fields:
            return field
    return None


def generate_question(field: str, config: DomainConfig | None = None) -> str:
    if config is None:
        config = DomainRegistry.default()

    fd = config.get_field(field)

    # Prefer the domain-configured fallback question — it's deterministic,
    # written in natural language, and avoids LLM leaking technical names.
    if fd.fallback_question:
        return fd.fallback_question

    import re as _re
    label = fd.label or field
    clean_label = _re.sub(r'^[^\w]+', '', label).strip() or label

    try:
        examples_hint = f" Possible values: {', '.join(fd.examples[:5])}." if fd.examples else ""
        prompt = (
            f"Generate a short, natural clarification question to ask a user "
            f"about '{clean_label}' in their query. "
            f"The field represents: {fd.description}.{examples_hint} "
            f"Use plain language — never use technical names like '{field}'. "
            f"Output ONLY the question, nothing else."
        )
        return get_default_provider().generate(prompt).strip()
    except Exception:
        return f"Could you clarify the {clean_label}?"


def update_intent(
    intent: DynamicIntent,
    field: str,
    answer: str,
    config: DomainConfig | None = None,
) -> tuple[DynamicIntent, AnswerValidation]:
    """Update intent with a clarification answer.

    Validates the answer first. Returns (updated_intent, validation).
    - valid + high confidence → field resolved
    - valid + zero confidence (denial) → field stays unresolved
    - invalid → field stays unresolved, validation.reason explains why
    """
    if config is None:
        config = DomainRegistry.default()

    fd = config.get_field(field)
    validation = validate_answer(answer, fd)

    new_intent = deepcopy(intent)

    if not validation.valid:
        # Don't update — keep field as-is
        return new_intent, validation

    if validation.confidence == 0.0:
        # Denial response — user explicitly declined this field.
        # Use default_value if available, otherwise mark as "explicitly skipped"
        # with confidence above threshold so it won't be re-asked.
        if fd.default_value is not None:
            new_intent.set_hypotheses(field, [Hypothesis(value=fd.default_value, confidence=0.95)])
            validation = AnswerValidation(
                valid=True, reason=f"User skipped — using default '{fd.default_value}'", confidence=0.95,
            )
        else:
            # No default — mark as explicitly skipped (above threshold, null value)
            skip_confidence = fd.threshold + 0.05  # just above threshold so it won't be re-asked
            new_intent.set_hypotheses(field, [Hypothesis(value=None, confidence=skip_confidence)])
            validation = AnswerValidation(
                valid=True, reason="User explicitly skipped this field", confidence=skip_confidence,
            )
        return new_intent, validation

    # Valid answer — set with validated confidence
    new_intent.set_hypotheses(field, [Hypothesis(value=answer.strip(), confidence=validation.confidence)])
    return new_intent, validation


def render_confirmation(intent: DynamicIntent, config: DomainConfig | None = None) -> str:
    if config is None:
        config = DomainRegistry.default()
    lines = ["I understood your request:\n"]
    for fd in config.fields:
        top_val = intent.top(fd.name)
        display = top_val if top_val is not None else "\u2014"
        lines.append(f"  {fd.label}:  {display}")
    return "\n".join(lines)


# Backwards compatibility
POLICY = {
    "max_iterations": 3,
    "ask_one_field_at_a_time": True,
    "field_priority": ["measure", "time_range", "filters", "dimension", "granularity"],
    "fallback_on_max_iterations": "reject",
}

FALLBACK_QUESTIONS = {
    "measure":     "Which metric do you want to see? (e.g. revenue, orders, margin)",
    "dimension":   "How do you want to group the data? (e.g. by region, by product, by customer)",
    "time_range":  "What time period are you interested in? (e.g. Q1 2025, last 30 days, January 2025)",
    "filters":     "Do you want to filter the data? (e.g. online channel only, enterprise segment)",
    "granularity": "What level of detail? (e.g. daily, weekly, monthly)",
    "comparison":  "Do you want to compare with another period or segment? (e.g. vs last year, vs budget)",
}

FIELD_LABELS = {
    "measure":     "\U0001f4ca Measure",
    "dimension":   "\U0001f50e Dimension",
    "time_range":  "\U0001f4c5 Period",
    "filters":     "\U0001f50d Filters",
    "granularity": "\U0001f9ee Granularity",
    "comparison":  "\U0001f4c8 Comparison",
}


if __name__ == "__main__":
    question = generate_question("measure")
    print(f"Clarification question: {question}")
