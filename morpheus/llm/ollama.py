"""Ollama LLM provider — calls local Ollama server."""

from __future__ import annotations

import os

import requests

from llm.provider import LLMProvider


class OllamaProvider(LLMProvider):
    """Ollama provider using the /api/generate endpoint."""

    def __init__(self) -> None:
        self._base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._model = os.environ.get("OLLAMA_MODEL", "mistral")
        self._timeout = 120

    @property
    def name(self) -> str:
        return "ollama"

    def generate(self, prompt: str, system: str | None = None) -> str:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
        }
        if system:
            payload["system"] = system

        resp = requests.post(
            f"{self._base_url}/api/generate",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "")
