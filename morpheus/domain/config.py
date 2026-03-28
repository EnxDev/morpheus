from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldDefinition:
    name: str
    label: str
    description: str
    threshold: float
    weight: float
    priority: int
    default_value: Any = None
    fallback_question: str = ""
    examples: list[str] = field(default_factory=list)
    ambiguity_threshold: float = 0.1  # min gap between top two hypotheses

    def __post_init__(self):
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError(f"threshold must be 0.0–1.0, got {self.threshold}")
        if self.weight < 0.0:
            raise ValueError(f"weight must be >= 0, got {self.weight}")
        if not (0.0 <= self.ambiguity_threshold <= 1.0):
            raise ValueError(f"ambiguity_threshold must be 0.0–1.0, got {self.ambiguity_threshold}")


@dataclass
class CapabilityDefinition:
    action: str
    field_weights: dict[str, float]
    min_score: float = 0.5
    match_fields: dict[str, str | list[str]] = field(default_factory=dict)  # field_name → expected value(s)
    authorized_tuples: list[dict] = field(default_factory=list)  # IBAC tuple templates

    def __post_init__(self):
        if not (0.0 <= self.min_score <= 1.0):
            raise ValueError(f"min_score must be 0.0–1.0, got {self.min_score}")


@dataclass
class DomainConfig:
    name: str
    domain_description: str
    fields: list[FieldDefinition]
    capabilities: list[CapabilityDefinition]
    execution_plans: dict[str, list[dict]] = field(default_factory=dict)
    parser_prompt_template: str = ""
    validation_prompt_template: str = ""
    clarification_policy: dict = field(default_factory=lambda: {
        "max_iterations": 3,
        "ask_one_field_at_a_time": True,
        "fallback_on_max_iterations": "reject",
    })

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(fd.name for fd in self.fields)

    def get_field(self, name: str) -> FieldDefinition:
        for fd in self.fields:
            if fd.name == name:
                return fd
        raise KeyError(f"Unknown field: {name}")

    @property
    def thresholds(self) -> dict[str, float]:
        return {fd.name: fd.threshold for fd in self.fields}

    @property
    def weights(self) -> dict[str, float]:
        return {fd.name: fd.weight for fd in self.fields}

    @property
    def field_priority(self) -> list[str]:
        return [fd.name for fd in sorted(self.fields, key=lambda f: f.priority)]

    @property
    def fallback_questions(self) -> dict[str, str]:
        return {fd.name: fd.fallback_question for fd in self.fields}

    @property
    def field_labels(self) -> dict[str, str]:
        return {fd.name: fd.label for fd in self.fields}

    def generate_parser_prompt(self, user_input: str) -> str:
        field_defs = "\n".join(
            f"- {fd.name}: {fd.description} (e.g. {', '.join(fd.examples)})"
            if fd.examples
            else f"- {fd.name}: {fd.description}"
            for fd in self.fields
        )
        return (
            self.parser_prompt_template
            .replace("{field_definitions}", field_defs)
            .replace("{user_input}", user_input)
            .replace("{field_count}", str(len(self.fields)))
            .replace("{field_names}", ", ".join(self.field_names))
        )

    def generate_validation_prompt(self, intent_text: str) -> str:
        return (
            self.validation_prompt_template
            .replace("{intent_text}", intent_text)
            .replace("{field_names}", ", ".join(self.field_names))
        )

    @classmethod
    def from_dict(cls, data: dict) -> DomainConfig:
        fields = [FieldDefinition(**fd) for fd in data["fields"]]
        capabilities = [CapabilityDefinition(**cap) for cap in data["capabilities"]]
        return cls(
            name=data["name"],
            domain_description=data.get("domain_description", ""),
            fields=fields,
            capabilities=capabilities,
            execution_plans=data.get("execution_plans", {}),
            parser_prompt_template=data.get("parser_prompt_template", ""),
            validation_prompt_template=data.get("validation_prompt_template", ""),
            clarification_policy=data.get("clarification_policy", {
                "max_iterations": 3,
                "ask_one_field_at_a_time": True,
                "fallback_on_max_iterations": "reject",
            }),
        )
