"""Enhanced audit logger matching the Morpheus Vision requirements.

Each audit event includes: timestamp, user, event_type, payload, decision,
controls_active, and policy_applied.

Supports pluggable sinks: InMemorySink, ConsoleSink, FileAuditSink, CompositeSink.
All payloads are automatically redacted to remove secrets before storage.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


# ── Secret redaction ─────────────────────────────────────────────────────────

_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    # API keys
    (re.compile(r'sk-[a-zA-Z0-9_-]{20,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'sk-proj-[a-zA-Z0-9_-]{20,}'), '[REDACTED_API_KEY]'),
    (re.compile(r'sk-ant-[a-zA-Z0-9_-]{20,}'), '[REDACTED_API_KEY]'),
    # AWS keys
    (re.compile(r'AKIA[A-Z0-9]{16}'), '[REDACTED_AWS_KEY]'),
    # GitHub tokens
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), '[REDACTED_GH_TOKEN]'),
    (re.compile(r'gho_[a-zA-Z0-9]{36}'), '[REDACTED_GH_TOKEN]'),
    # Bearer tokens
    (re.compile(r'Bearer\s+[a-zA-Z0-9._-]{20,}'), '[REDACTED_BEARER]'),
    # Connection strings
    (re.compile(r'(postgresql|mysql|mongodb|redis)://[^\s"\']+'), '[REDACTED_CONN_STRING]'),
    # SSH keys
    (re.compile(r'ssh-(rsa|ed25519|ecdsa)\s+[A-Za-z0-9+/=]+'), '[REDACTED_SSH_KEY]'),
    # IP addresses (private ranges)
    (re.compile(r'\b(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3})\b'), '[REDACTED_IP]'),
    # File paths that look like home directories
    (re.compile(r'/home/[a-zA-Z0-9_-]+/'), '/home/[REDACTED]/'),
    (re.compile(r'C:\\\\Users\\\\[a-zA-Z0-9_-]+\\\\'), 'C:\\\\Users\\\\[REDACTED]\\\\'),
]


def redact_secrets(value: str) -> str:
    """Redact known secret patterns from a string."""
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def _redact_dict(data: dict) -> dict:
    """Recursively redact secrets from a dict."""
    result = {}
    for k, v in data.items():
        if isinstance(v, str):
            result[k] = redact_secrets(v)
        elif isinstance(v, dict):
            result[k] = _redact_dict(v)
        elif isinstance(v, list):
            result[k] = [
                _redact_dict(item) if isinstance(item, dict)
                else redact_secrets(item) if isinstance(item, str)
                else item
                for item in v
            ]
        else:
            result[k] = v
    return result


# ── AuditEvent dataclass ─────────────────────────────────────────────────────

@dataclass
class AuditEvent:
    """Formalized audit event structure per the Vision spec."""

    timestamp: str
    user: str
    event_type: str
    payload: dict
    decision: str | None = None          # "approved" | "blocked" | "bypassed" | None
    level_1_result: dict | None = None   # {risk_level, rule_applied, status}
    level_2_result: dict | None = None   # {coherence_score, threshold, reason, llm_used}
    controls_active: dict[str, bool] = field(default_factory=lambda: {
        "input_validation": True,
        "action_validation": True,
        "coherence_check": True,
    })
    policy_applied: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


# ── Audit Sinks ──────────────────────────────────────────────────────────────

class AuditSink(ABC):
    """Abstract base class for audit event sinks."""

    @abstractmethod
    def write(self, event: AuditEvent) -> None:
        ...


class InMemorySink(AuditSink):
    """Stores events in memory (for tests and API queries).

    Capped at max_events to prevent unbounded memory growth.
    """

    def __init__(self, max_events: int = 10000) -> None:
        self._events: list[AuditEvent] = []
        self._max_events = max_events

    def write(self, event: AuditEvent) -> None:
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get_events(self) -> list[AuditEvent]:
        return list(self._events)

    def last(self, n: int) -> list[AuditEvent]:
        return self._events[-n:]

    def clear(self) -> None:
        self._events.clear()


class ConsoleAuditSink(AuditSink):
    """Prints events to stdout as JSON."""

    def write(self, event: AuditEvent) -> None:
        print(event.to_json())


class FileAuditSink(AuditSink):
    """Appends events as JSONL to a file with optional rotation.

    - Creates file if not exists
    - Appends atomically (one write per event, append mode)
    - Handles file rotation (max_bytes default 10MB, keep max_files=5)
    - Safe for concurrent writes (append mode)
    """

    def __init__(
        self,
        path: str,
        max_bytes: int = 10 * 1024 * 1024,  # 10MB
        max_files: int = 5,
    ) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._max_files = max_files

    def write(self, event: AuditEvent) -> None:
        self._rotate_if_needed()
        with open(self._path, "a") as f:
            f.write(event.to_json() + "\n")

    def _rotate_if_needed(self) -> None:
        """Rotate the log file if it exceeds max_bytes."""
        if not os.path.exists(self._path):
            return
        try:
            size = os.path.getsize(self._path)
        except OSError:
            return
        if size < self._max_bytes:
            return

        # Rotate: file.jsonl -> file.jsonl.1, file.jsonl.1 -> file.jsonl.2, etc.
        for i in range(self._max_files - 1, 0, -1):
            src = f"{self._path}.{i}"
            dst = f"{self._path}.{i + 1}"
            if os.path.exists(src):
                if i + 1 >= self._max_files:
                    os.remove(src)
                else:
                    os.rename(src, dst)

        # Current file becomes .1
        os.rename(self._path, f"{self._path}.1")


class CompositeSink(AuditSink):
    """Fans out events to multiple sinks."""

    def __init__(self, sinks: list[AuditSink]) -> None:
        self._sinks = sinks

    def write(self, event: AuditEvent) -> None:
        for sink in self._sinks:
            sink.write(event)


# ── AuditLogger ──────────────────────────────────────────────────────────────

class AuditLogger:
    """Enhanced audit logger with pluggable sinks.

    Default: InMemorySink (for backward compatibility with existing code).
    """

    def __init__(self, sinks: list[AuditSink] | None = None) -> None:
        self._memory = InMemorySink()
        if sinks is None:
            self._sink = self._memory
        else:
            # Always include in-memory for API queries
            all_sinks = [self._memory] + sinks
            self._sink = CompositeSink(all_sinks)

    def log(
        self,
        event: str,
        data: dict | None = None,
        *,
        user: str = "system",
        decision: str | None = None,
        level_1_result: dict | None = None,
        level_2_result: dict | None = None,
        controls_active: dict[str, bool] | None = None,
        policy_applied: str | None = None,
    ) -> None:
        """Log an audit event.

        Backwards compatible: existing log(event, data) calls still work.
        New fields can be passed as keyword args or embedded in the data dict.
        """
        if data is None:
            data = {}

        # Redact secrets from payload before storage
        data = _redact_dict(data)

        # Allow new fields to be passed inside data dict (backward compat)
        if decision is None:
            decision = data.pop("decision", None)
        if level_1_result is None:
            level_1_result = data.pop("level_1_result", None)
        if level_2_result is None:
            level_2_result = data.pop("level_2_result", None)
        if controls_active is None:
            controls_active = data.pop("controls_active", {
                "input_validation": True,
                "action_validation": True,
                "coherence_check": True,
            })
        if policy_applied is None:
            policy_applied = data.pop("policy_applied", None)

        audit_event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            user=user,
            event_type=event,
            payload=data,
            decision=decision,
            level_1_result=level_1_result,
            level_2_result=level_2_result,
            controls_active=controls_active,
            policy_applied=policy_applied,
        )

        self._sink.write(audit_event)

    def get_log(self) -> list[dict]:
        """Return all events as dicts (backward compatible)."""
        return [e.to_dict() for e in self._memory.get_events()]

    def get_events(self) -> list[AuditEvent]:
        """Return all events as AuditEvent objects."""
        return self._memory.get_events()

    def last(self, n: int) -> list[dict]:
        """Return last n events as dicts (backward compatible)."""
        return [e.to_dict() for e in self._memory.last(n)]

    def clear(self) -> None:
        self._memory.clear()

    def to_json(self) -> str:
        return self.export_json()

    def summary(self) -> dict:
        counts: dict[str, int] = {}
        for event in self._memory.get_events():
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return counts

    def export_json(self) -> str:
        """Export full log as JSON array."""
        return json.dumps(self.get_log(), indent=2, default=str)

    def export_csv(self) -> str:
        """Export full log as CSV."""
        output = io.StringIO()
        fieldnames = [
            "timestamp", "user", "event_type", "decision",
            "policy_applied", "level_1_result", "level_2_result",
            "controls_active", "payload",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for event in self._memory.get_events():
            writer.writerow({
                "timestamp": event.timestamp,
                "user": event.user,
                "event_type": event.event_type,
                "decision": event.decision or "",
                "policy_applied": event.policy_applied or "",
                "level_1_result": json.dumps(event.level_1_result) if event.level_1_result else "",
                "level_2_result": json.dumps(event.level_2_result) if event.level_2_result else "",
                "controls_active": json.dumps(event.controls_active),
                "payload": json.dumps(event.payload),
            })
        return output.getvalue()
