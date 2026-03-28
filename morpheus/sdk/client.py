"""HTTP client for the Morpheus FastAPI backend."""

from __future__ import annotations

import requests

from sdk.types import (
    ParseResult,
    ClarifyResult,
    DecisionResult,
    AuditEvent,
    ControlConfig,
)


class MorpheusClient:
    """Python SDK client for the Morpheus / Intent Guard API.

    Usage:
        client = MorpheusClient()  # defaults to localhost:8000
        result = client.parse("Show me revenue by region for Q1 2025")
        print(result.intent)
    """

    def __init__(self, base_url: str = "http://localhost:8000", timeout: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def parse(self, query: str, domain: str | None = None) -> ParseResult:
        """Parse a query into a structured intent."""
        payload: dict = {"query": query}
        if domain:
            payload["domain"] = domain
        resp = requests.post(
            self._url("/api/parse"),
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return ParseResult(**resp.json())

    def clarify(self, intent: dict, field: str, answer: str, domain: str | None = None) -> ClarifyResult:
        """Clarify a low-confidence field with a user answer."""
        payload = {"intent": intent, "field": field, "answer": answer}
        if domain:
            payload["domain"] = domain
        resp = requests.post(
            self._url("/api/clarify"),
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return ClarifyResult(**resp.json())

    def decide(self, intent: dict, domain: str | None = None) -> DecisionResult:
        """Select an action based on the validated intent."""
        payload = {"intent": intent}
        if domain:
            payload["domain"] = domain
        resp = requests.post(
            self._url("/api/decide"),
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return DecisionResult(**resp.json())

    def get_audit(self, last_n: int = 50) -> list[AuditEvent]:
        """Retrieve the last N audit events."""
        resp = requests.get(
            self._url("/audit"),
            params={"last_n": last_n},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return [AuditEvent(**e) for e in resp.json()]

    def get_audit_summary(self) -> dict:
        """Get event type counts."""
        resp = requests.get(
            self._url("/audit/summary"),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def export_audit(self, fmt: str = "json") -> str:
        """Export full audit log as JSON or CSV string."""
        resp = requests.get(
            self._url("/audit/export"),
            params={"format": fmt},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.text

    def list_domains(self) -> dict:
        """List all registered domains."""
        resp = requests.get(
            self._url("/api/domains"),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def register_domain(self, config: dict) -> dict:
        """Register a new domain configuration."""
        resp = requests.post(
            self._url("/api/domains/register"),
            json={"config": config},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def get_controls(self) -> ControlConfig:
        """Get current control toggle state."""
        resp = requests.get(
            self._url("/api/controls"),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return ControlConfig(**resp.json())

    def set_controls(
        self,
        input_validation: bool | None = None,
        action_validation: bool | None = None,
        coherence_check: bool | None = None,
        reason: str = "",
    ) -> ControlConfig:
        """Update control toggles."""
        payload = {"reason": reason}
        if input_validation is not None:
            payload["input_validation"] = input_validation
        if action_validation is not None:
            payload["action_validation"] = action_validation
        if coherence_check is not None:
            payload["coherence_check"] = coherence_check
        resp = requests.post(
            self._url("/api/controls"),
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return ControlConfig(**resp.json())

    def health(self) -> bool:
        """Check if the backend is healthy."""
        try:
            resp = requests.get(
                self._url("/health"),
                timeout=self._timeout,
            )
            return resp.status_code == 200
        except requests.ConnectionError:
            return False
