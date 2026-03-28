"""OpenAI LLM provider."""

from __future__ import annotations

import os

from llm.provider import LLMProvider


class OpenAIProvider(LLMProvider):
    """OpenAI provider using the openai Python SDK."""

    def __init__(self) -> None:
        self._api_key = os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable is required "
                "when MORPHEUS_LLM_PROVIDER=openai"
            )
        self._model = os.environ.get("OPENAI_MODEL", "gpt-4o")

        import openai
        self._client = openai.OpenAI(api_key=self._api_key)

    @property
    def name(self) -> str:
        return "openai"

    def generate(self, prompt: str, system: str | None = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
        )
        return response.choices[0].message.content or ""
