"""Anthropic Claude LLM provider."""

from __future__ import annotations

import os

from llm.provider import LLMProvider


class AnthropicProvider(LLMProvider):
    """Anthropic provider using the anthropic Python SDK."""

    def __init__(self) -> None:
        self._api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not self._api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is required "
                "when MORPHEUS_LLM_PROVIDER=anthropic"
            )
        self._model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._max_tokens = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "1024"))

        import anthropic
        self._client = anthropic.Anthropic(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "anthropic"

    def generate(self, prompt: str, system: str | None = None) -> str:
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        message = self._client.messages.create(**kwargs)
        return message.content[0].text
