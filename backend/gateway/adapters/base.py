"""
BaseProviderAdapter — Interface for all provider adapters.
==========================================================
Each provider implements:
  - chat_complete()  — full response
  - chat_stream()    — async generator of SSE chunks
  - list_models()    — available model IDs
  - health_check()   — ping
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator


@dataclass
class ChatMessage:
    role: str          # system | user | assistant | tool
    content: str | list[dict[str, Any]]  # str or multipart
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class ChatCompletionRequest:
    model: str
    messages: list[ChatMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None
    extra: dict[str, Any] | None = None  # provider-specific passthrough


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletionResponse:
    id: str
    model: str
    provider: str
    content: str
    finish_reason: str
    usage: UsageInfo
    tool_calls: list[dict[str, Any]] | None = None
    raw: dict[str, Any] | None = None  # original provider response


@dataclass
class StreamChunk:
    id: str
    model: str
    provider: str
    delta_content: str | None
    delta_tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
    usage: UsageInfo | None = None  # only in final chunk


class ProviderError(Exception):
    """Raised when a provider returns an error."""

    def __init__(self, message: str, status_code: int = 500, provider: str = "unknown") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider


class BaseProviderAdapter(ABC):
    """Abstract base class for all provider adapters."""

    provider_name: str = "base"

    @abstractmethod
    async def chat_complete(
        self, request: ChatCompletionRequest
    ) -> ChatCompletionResponse:
        """Return a full (non-streaming) chat completion."""
        ...

    @abstractmethod
    async def chat_stream(
        self, request: ChatCompletionRequest
    ) -> AsyncIterator[StreamChunk]:
        """Yield SSE-compatible stream chunks."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return list of available model IDs."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable."""
        ...

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Return estimated USD cost. Override in subclass for accuracy."""
        return 0.0
