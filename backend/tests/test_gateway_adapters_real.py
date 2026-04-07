"""
Tests for backend.gateway.adapters — get_adapter factory and list_adapters.

Covers:
- All 4 known providers return the correct adapter type
- Case-insensitive provider lookup
- Unknown provider raises ValueError with informative message
- list_adapters() returns exactly the 4 supported names
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# get_adapter — happy paths
# ---------------------------------------------------------------------------


def test_get_adapter_returns_ollama() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.ollama import OllamaAdapter

    adapter = get_adapter("ollama")
    assert isinstance(adapter, OllamaAdapter)


def test_get_adapter_returns_openrouter() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.openrouter import OpenRouterAdapter

    adapter = get_adapter("openrouter")
    assert isinstance(adapter, OpenRouterAdapter)


def test_get_adapter_returns_openai() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.openai import OpenAIAdapter

    adapter = get_adapter("openai")
    assert isinstance(adapter, OpenAIAdapter)


def test_get_adapter_returns_anthropic() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.anthropic import AnthropicAdapter

    adapter = get_adapter("anthropic")
    assert isinstance(adapter, AnthropicAdapter)


# ---------------------------------------------------------------------------
# get_adapter — case-insensitive normalisation
# ---------------------------------------------------------------------------


def test_get_adapter_uppercase_ollama() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.ollama import OllamaAdapter

    assert isinstance(get_adapter("OLLAMA"), OllamaAdapter)


def test_get_adapter_mixed_case_openai() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.openai import OpenAIAdapter

    assert isinstance(get_adapter("OpenAI"), OpenAIAdapter)


def test_get_adapter_mixed_case_openrouter() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.openrouter import OpenRouterAdapter

    assert isinstance(get_adapter("OpenRouter"), OpenRouterAdapter)


def test_get_adapter_mixed_case_anthropic() -> None:
    from backend.gateway.adapters import get_adapter
    from backend.gateway.adapters.anthropic import AnthropicAdapter

    assert isinstance(get_adapter("Anthropic"), AnthropicAdapter)


# ---------------------------------------------------------------------------
# get_adapter — unknown provider raises ValueError
# ---------------------------------------------------------------------------


def test_get_adapter_unknown_provider_raises() -> None:
    from backend.gateway.adapters import get_adapter

    with pytest.raises(ValueError, match="Unknown provider"):
        get_adapter("groq")


def test_get_adapter_empty_string_raises() -> None:
    from backend.gateway.adapters import get_adapter

    with pytest.raises(ValueError, match="Unknown provider"):
        get_adapter("")


def test_get_adapter_error_message_names_provider() -> None:
    """The ValueError message must include the bad provider name."""
    from backend.gateway.adapters import get_adapter

    with pytest.raises(ValueError, match="'cohere'"):
        get_adapter("cohere")


def test_get_adapter_error_message_lists_available() -> None:
    """The ValueError message must mention available providers."""
    from backend.gateway.adapters import get_adapter

    with pytest.raises(ValueError, match="Available"):
        get_adapter("fake-provider")


# ---------------------------------------------------------------------------
# list_adapters
# ---------------------------------------------------------------------------


def test_list_adapters_returns_all_four() -> None:
    from backend.gateway.adapters import list_adapters

    names = list_adapters()
    assert set(names) == {"ollama", "openrouter", "openai", "anthropic"}


def test_list_adapters_returns_list() -> None:
    from backend.gateway.adapters import list_adapters

    assert isinstance(list_adapters(), list)


def test_list_adapters_each_name_is_valid_for_get_adapter() -> None:
    """Every name returned by list_adapters() must be accepted by get_adapter()."""
    from backend.gateway.adapters import get_adapter, list_adapters
    from backend.gateway.adapters.base import BaseProviderAdapter

    for name in list_adapters():
        adapter = get_adapter(name)
        assert isinstance(adapter, BaseProviderAdapter), f"{name!r} did not return BaseProviderAdapter"
