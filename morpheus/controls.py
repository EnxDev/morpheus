"""Independent control toggles for the three Morpheus controls.

  Control 1: Input Validation
  Control 2 — Level 1: Action Validation (deterministic)
  Control 2 — Level 2: Coherence Check (LLM-assisted, optional)

Every control state change is logged to the AuditLogger.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from audit.logger import AuditLogger


@dataclass
class ControlConfig:
    """Current state of the three independent controls."""

    input_validation: bool = True    # Control 1
    action_validation: bool = True   # Control 2 — Level 1
    coherence_check: bool = True     # Control 2 — Level 2

    def to_dict(self) -> dict:
        return {
            "input_validation": self.input_validation,
            "action_validation": self.action_validation,
            "coherence_check": self.coherence_check,
        }


class ControlManager:
    """Manages three independent control toggles with audit logging."""

    def __init__(self, logger: AuditLogger | None = None) -> None:
        self._config = ControlConfig()
        self._logger = logger or AuditLogger()

    @property
    def logger(self) -> AuditLogger:
        return self._logger

    def get_controls(self) -> ControlConfig:
        return self._config

    def set_controls(
        self,
        input_validation: bool | None = None,
        action_validation: bool | None = None,
        coherence_check: bool | None = None,
        reason: str = "",
        user: str = "system",
    ) -> ControlConfig:
        """Update control toggles. Only provided values are changed.

        Every change is audit-logged with previous and new state.
        """
        previous = self._config.to_dict()

        if input_validation is not None:
            self._config.input_validation = input_validation
        if action_validation is not None:
            self._config.action_validation = action_validation
        if coherence_check is not None:
            self._config.coherence_check = coherence_check

        new_state = self._config.to_dict()

        if previous != new_state:
            self._logger.log("control_state_changed", {
                "user": user,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "previous_state": previous,
                "new_state": new_state,
                "reason": reason,
            })

        return self._config

    def is_input_validation_enabled(self) -> bool:
        return self._config.input_validation

    def is_action_validation_enabled(self) -> bool:
        return self._config.action_validation

    def is_coherence_check_enabled(self) -> bool:
        return self._config.coherence_check
