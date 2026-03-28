from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class Hypothesis:
    value: str | None
    confidence: float

    MAX_VALUE_LENGTH = 10000

    def __post_init__(self):
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )
        if self.value is not None and len(self.value) > self.MAX_VALUE_LENGTH:
            raise ValueError(
                f"value length {len(self.value)} exceeds max {self.MAX_VALUE_LENGTH}"
            )


class DynamicIntent:
    """Domain-agnostic intent with dynamic fields backed by a dict."""

    def __init__(self, fields: tuple[str, ...], data: dict[str, list[Hypothesis]] | None = None):
        object.__setattr__(self, "_fields", fields)
        object.__setattr__(self, "_data", {f: [] for f in fields})
        if data:
            for f in fields:
                if f in data:
                    self._data[f] = data[f]

    @classmethod
    def from_config(cls, config) -> DynamicIntent:
        return cls(config.field_names)

    @classmethod
    def from_dict(cls, raw: dict, fields: tuple[str, ...] | None = None) -> DynamicIntent:
        if fields is None:
            fields = tuple(raw.keys())
        data = {}
        for f in fields:
            raw_list = raw.get(f, [])
            if isinstance(raw_list, list):
                data[f] = [
                    Hypothesis(
                        value=h.get("value"),
                        confidence=float(h.get("confidence", 0.0)),
                    )
                    for h in raw_list
                ]
            else:
                data[f] = []
        return cls(fields, data)

    def to_dict(self) -> dict:
        result = {}
        for f in self._fields:
            hyps = self._data.get(f, [])
            result[f] = [
                {"value": h.value, "confidence": h.confidence} for h in hyps
            ]
        return result

    def top(self, field_name: str) -> str | None:
        hyps = self._data.get(field_name, [])
        if not hyps:
            return None
        best = max(hyps, key=lambda h: h.confidence)
        return best.value

    def is_empty(self, field_name: str) -> bool:
        hyps = self._data.get(field_name, [])
        return all(h.value is None for h in hyps)

    @property
    def field_names(self) -> tuple[str, ...]:
        return self._fields

    def get_hypotheses(self, field_name: str) -> list[Hypothesis]:
        return self._data.get(field_name, [])

    def set_hypotheses(self, field_name: str, hyps: list[Hypothesis]) -> None:
        if field_name not in self._fields:
            raise KeyError(f"Unknown field: {field_name}")
        self._data[field_name] = hyps

    def __getattr__(self, name: str) -> list[Hypothesis]:
        # Allow intent.measure syntax
        if name.startswith("_"):
            raise AttributeError(name)
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        raise AttributeError(f"No field '{name}'")

    def __setattr__(self, name: str, value):
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        data = object.__getattribute__(self, "_data")
        if name in data:
            data[name] = value
            return
        object.__setattr__(self, name, value)

    def __deepcopy__(self, memo):
        new_data = {f: deepcopy(hyps, memo) for f, hyps in self._data.items()}
        return DynamicIntent(self._fields, new_data)

    def __repr__(self) -> str:
        parts = []
        for f in self._fields:
            top_val = self.top(f)
            parts.append(f"{f}={top_val!r}")
        return f"DynamicIntent({', '.join(parts)})"


# ── Backwards compatibility ──────────────────────────────────────────────────

INTENT_FIELDS = ("measure", "dimension", "time_range", "filters", "granularity", "comparison")


def SupersetIntent(
    measure=None, dimension=None, time_range=None,
    filters=None, granularity=None, comparison=None,
) -> DynamicIntent:
    """Factory for backwards-compatible Superset BI intents."""
    data = {}
    for name, val in [
        ("measure", measure), ("dimension", dimension), ("time_range", time_range),
        ("filters", filters), ("granularity", granularity), ("comparison", comparison),
    ]:
        data[name] = val if val is not None else []
    return DynamicIntent(INTENT_FIELDS, data)
