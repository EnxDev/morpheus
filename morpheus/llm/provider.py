"""LLM provider abstraction.

Supports OpenAI, Anthropic Claude, and Ollama (local).
Configured via MORPHEUS_LLM_PROVIDER environment variable.

Auto-detection: if no provider is explicitly set, Morpheus picks the first
available remote provider based on which API key is present:
  1. OPENAI_API_KEY set    → openai
  2. ANTHROPIC_API_KEY set → anthropic
  3. fallback              → ollama (local, no key needed)
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def generate(self, prompt: str, system: str | None = None) -> str:
        """Send a prompt and return raw text response."""
        ...


def _detect_provider() -> str:
    """Auto-detect provider from available API keys.

    Priority: openai > anthropic > ollama (fallback).
    """
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "ollama"


def get_provider() -> LLMProvider:
    """Create an LLM provider.

    Resolution order:
      1. MORPHEUS_LLM_PROVIDER env var (explicit choice)
      2. LLM_PROVIDER env var (alias)
      3. Auto-detect from available API keys
    """
    provider_name = os.environ.get(
        "MORPHEUS_LLM_PROVIDER",
        os.environ.get("LLM_PROVIDER"),
    )

    if provider_name is None:
        provider_name = _detect_provider()

    provider_name = provider_name.lower()

    if provider_name == "anthropic":
        from llm.anthropic import AnthropicProvider
        return AnthropicProvider()
    elif provider_name == "ollama":
        from llm.ollama import OllamaProvider
        return OllamaProvider()
    else:
        from llm.openai import OpenAIProvider
        return OpenAIProvider()


# Module-level singleton — lazily initialized
_provider: LLMProvider | None = None


def get_default_provider() -> LLMProvider:
    """Get or create the default provider singleton."""
    global _provider
    if _provider is None:
        _provider = get_provider()
    return _provider


def reset_provider() -> None:
    """Reset the cached provider (useful for testing or reconfiguration)."""
    global _provider
    _provider = None
