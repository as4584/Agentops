"""
Gateway Core — GatewayRouter wrapping provider adapters.
=========================================================
Central dispatch point:
  1. Resolve model → provider
  2. Route to appropriate adapter
  3. Apply tool ID sanitization
  4. Record usage + audit
"""

from __future__ import annotations

import logging
import time
from typing import Any, AsyncIterator

from backend.gateway.adapters import (
    BaseProviderAdapter, ChatCompletionRequest, ChatCompletionResponse,
    ChatMessage, StreamChunk, UsageInfo, ProviderError, get_adapter,
)
from backend.gateway.audit import get_audit_logger, RequestTimer
from backend.gateway.health import get_circuit, select_provider_with_fallback
from backend.gateway.streaming import ToolIdSanitizer
from backend.gateway.usage import get_usage_tracker
from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY
from backend.utils.tool_ids import sanitize_tool_id

logger = logging.getLogger("gateway.router")


def _sanitize_request(request: ChatCompletionRequest) -> ChatCompletionRequest:
    """Centralized tool ID sanitization applied before dispatching to any adapter.
    
    This is a defense-in-depth measure — individual adapters also sanitize,
    but this ensures no unsanitized IDs ever reach any provider regardless
    of adapter implementation.
    """
    sanitized_messages = []
    for m in request.messages:
        new_tool_call_id = m.tool_call_id
        if new_tool_call_id:
            new_tool_call_id = sanitize_tool_id(new_tool_call_id)
        new_tool_calls = m.tool_calls
        if new_tool_calls:
            new_tool_calls = [
                {**tc, "id": sanitize_tool_id(tc["id"])} if "id" in tc else tc
                for tc in new_tool_calls
            ]
        sanitized_messages.append(
            ChatMessage(
                role=m.role,
                content=m.content,
                name=m.name,
                tool_call_id=new_tool_call_id,
                tool_calls=new_tool_calls,
            )
        )
    return ChatCompletionRequest(
        model=request.model,
        messages=sanitized_messages,
        max_tokens=request.max_tokens,
        temperature=request.temperature,
        stream=request.stream,
        tools=request.tools,
        tool_choice=request.tool_choice,
        extra=request.extra,
    )


def _resolve_provider(model_id: str) -> str:
    """Determine the provider for *model_id* from the model registry."""
    spec = UNIFIED_MODEL_REGISTRY.get(model_id)
    if spec:
        return spec.provider.value

    # Heuristic fallbacks based on model ID prefix
    lower = model_id.lower()
    if lower.startswith("ollama/") or ":" in lower and not lower.startswith("gpt") and not lower.startswith("claude"):
        return "ollama"
    if lower.startswith(("gpt-", "o1-", "o3-", "text-davinci")):
        return "openai"
    if lower.startswith("claude"):
        return "anthropic"
    # Default: route through OpenRouter for unknown cloud models
    return "openrouter"


class GatewayRouter:
    """Routes completion requests to the correct provider adapter."""

    def __init__(self) -> None:
        self._sanitizers: dict[str, ToolIdSanitizer] = {}  # per key_id

    def _get_sanitizer(self, key_id: str) -> ToolIdSanitizer:
        if key_id not in self._sanitizers:
            self._sanitizers[key_id] = ToolIdSanitizer()
        return self._sanitizers[key_id]

    async def complete(
        self,
        request: ChatCompletionRequest,
        key_id: str = "anon",
    ) -> ChatCompletionResponse:
        """Non-streaming completion with audit + usage recording."""
        provider = _resolve_provider(request.model)
        provider = await select_provider_with_fallback(provider)

        circuit = get_circuit(provider)
        if circuit.is_open():
            raise ProviderError(f"Provider {provider} circuit is open (unavailable)", 503, provider)

        adapter = get_adapter(provider)
        audit = get_audit_logger()
        tracker = get_usage_tracker()

        # Sanitize all tool IDs before dispatching to any adapter
        request = _sanitize_request(request)

        with RequestTimer() as timer:
            try:
                response = await adapter.chat_complete(request)
                circuit.record_success()
            except ProviderError as e:
                circuit.record_failure()
                cost = 0.0
                audit.log_request(
                    key_id=key_id, model=request.model, provider=provider,
                    latency_ms=timer.elapsed_ms, status=e.status_code, error=str(e),
                )
                raise

        cost = adapter.estimate_cost(
            request.model, response.usage.prompt_tokens, response.usage.completion_tokens
        )

        audit.log_request(
            key_id=key_id, model=request.model, provider=provider,
            tokens_in=response.usage.prompt_tokens,
            tokens_out=response.usage.completion_tokens,
            cost_usd=cost, latency_ms=timer.elapsed_ms, status=200,
        )
        tracker.record(
            key_id=key_id, model=request.model, provider=provider,
            tokens_in=response.usage.prompt_tokens,
            tokens_out=response.usage.completion_tokens,
            cost_usd=cost,
        )

        return response

    async def stream(
        self,
        request: ChatCompletionRequest,
        key_id: str = "anon",
    ) -> AsyncIterator[StreamChunk]:
        """Streaming completion with audit + usage recording."""
        provider = _resolve_provider(request.model)
        provider = await select_provider_with_fallback(provider)

        circuit = get_circuit(provider)
        if circuit.is_open():
            raise ProviderError(f"Provider {provider} circuit is open (unavailable)", 503, provider)

        adapter = get_adapter(provider)
        audit = get_audit_logger()
        tracker = get_usage_tracker()

        # Sanitize all tool IDs before dispatching to any adapter
        request = _sanitize_request(request)

        tokens_in = 0
        tokens_out = 0
        start = time.perf_counter()
        error_str = ""

        try:
            async for chunk in adapter.chat_stream(request):
                if chunk.usage:
                    tokens_in = chunk.usage.prompt_tokens
                    tokens_out = chunk.usage.completion_tokens
                yield chunk
            circuit.record_success()
        except ProviderError as e:
            circuit.record_failure()
            error_str = str(e)
            raise
        finally:
            latency_ms = int((time.perf_counter() - start) * 1000)
            cost = adapter.estimate_cost(request.model, tokens_in, tokens_out)
            audit.log_request(
                key_id=key_id, model=request.model, provider=provider,
                tokens_in=tokens_in, tokens_out=tokens_out,
                cost_usd=cost, latency_ms=latency_ms,
                status=200 if not error_str else 500,
                stream=True, error=error_str,
            )
            if tokens_in or tokens_out:
                tracker.record(
                    key_id=key_id, model=request.model, provider=provider,
                    tokens_in=tokens_in, tokens_out=tokens_out, cost_usd=cost,
                    error=bool(error_str),
                )


# Module singleton
_router: GatewayRouter | None = None


def get_gateway_router() -> GatewayRouter:
    global _router
    if _router is None:
        _router = GatewayRouter()
    return _router
