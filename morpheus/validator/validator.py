from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from intent.schema import DynamicIntent, Hypothesis
from domain.config import DomainConfig
from domain.registry import DomainRegistry
from llm import get_default_provider

load_dotenv()


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate(intent: DynamicIntent, config: DomainConfig | None = None) -> ValidationResult:
    if config is None:
        config = DomainRegistry.default()

    errors: list[str] = []
    warnings: list[str] = []

    # ─── Phase 1: Deterministic checks ────────────────────────────────────────

    for fd in config.fields:
        field_name = fd.name
        hyps = intent.get_hypotheses(field_name)

        if not isinstance(hyps, list):
            errors.append(f"Field '{field_name}' must be a list")
            continue

        if len(hyps) == 0:
            errors.append(f"Field '{field_name}' must have at least one hypothesis")
            continue

        for i, h in enumerate(hyps):
            if not isinstance(h, Hypothesis):
                errors.append(f"Field '{field_name}' hypothesis {i} is not a Hypothesis")
                continue
            if not isinstance(h.confidence, (int, float)):
                errors.append(f"Field '{field_name}' hypothesis {i} has non-numeric confidence")
            elif not (0.0 <= h.confidence <= 1.0):
                errors.append(f"Field '{field_name}' hypothesis {i} confidence {h.confidence} out of range [0.0, 1.0]")

        if len(hyps) > 1:
            confidences = [h.confidence for h in hyps if isinstance(h, Hypothesis)]
            if confidences != sorted(confidences, reverse=True):
                warnings.append(f"Field '{field_name}' hypotheses are not sorted by confidence descending")

    if errors:
        return ValidationResult(is_valid=False, errors=errors, warnings=warnings)

    # ─── Phase 2: LLM structural check ─────────────────────────────────────────

    intent_summary = []
    for fd in config.fields:
        top_val = intent.top(fd.name)
        intent_summary.append(f"  {fd.name}: {top_val if top_val is not None else 'null'}")
    intent_text = "\n".join(intent_summary)

    prompt = config.generate_validation_prompt(intent_text)

    try:
        answer = get_default_provider().generate(prompt).strip().upper()

        if answer.startswith("YES"):
            return ValidationResult(is_valid=True, errors=[], warnings=warnings)
        elif answer.startswith("NO"):
            warnings.append("LLM structural check failed")
            return ValidationResult(is_valid=False, errors=[], warnings=warnings)
        else:
            warnings.append(f"LLM returned unexpected answer: {answer[:50]}")
            return ValidationResult(is_valid=True, errors=[], warnings=warnings)
    except Exception as e:
        warnings.append(f"LLM unreachable ({e}), using deterministic result only")
        return ValidationResult(is_valid=True, errors=[], warnings=warnings)


if __name__ == "__main__":
    from intent.schema import SupersetIntent

    valid = SupersetIntent(
        measure=[Hypothesis(value="revenue", confidence=0.92)],
        dimension=[Hypothesis(value="by region", confidence=0.88)],
        time_range=[Hypothesis(value="Q1 2025", confidence=0.95)],
        filters=[Hypothesis(value=None, confidence=0.1)],
        granularity=[Hypothesis(value="monthly", confidence=0.85)],
        comparison=[Hypothesis(value=None, confidence=0.1)],
    )
    r1 = validate(valid)
    print(f"Valid:   is_valid={r1.is_valid}, errors={r1.errors}, warnings={r1.warnings}")
