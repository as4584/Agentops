"""
Gateway Adapters — provider registry and adapter factory.
"""

from __future__ import annotations

from backend.gateway.adapters.base import (
    BaseProviderAdapter,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    StreamChunk,
    UsageInfo,
    ProviderError,
)

__all__ = [
    "BaseProviderAdapter",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "StreamChunk",
    "UsageInfo",
    "ProviderError",
    "get_adapter",
    "list_adapters",
]


def get_adapter(provider: str) -> BaseProviderAdapter:
    """Return an adapter instance for *provider*."""
    from backend.gateway.adapters.ollama import OllamaAdapter
    from backend.gateway.adapters.openrouter import OpenRouterAdapter
    from backend.gateway.adapters.openai import OpenAIAdapter
    from backend.gateway.adapters.anthropic import AnthropicAdapter

    registry: dict[str, type[BaseProviderAdapter]] = {
        "ollama": OllamaAdapter,
        "openrouter": OpenRouterAdapter,
        "openai": OpenAIAdapter,
        "anthropic": AnthropicAdapter,
    }
    cls = registry.get(provider.lower())
    if cls is None:
        raise ValueError(f"Unknown provider: {provider!r}. Available: {list(registry)}")
    return cls()


def list_adapters() -> list[str]:
    return ["ollama", "openrouter", "openai", "anthropic"]
