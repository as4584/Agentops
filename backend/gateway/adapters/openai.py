"""
OpenAI Provider Adapter — direct OpenAI API.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.gateway.adapters.base import (
    BaseProviderAdapter,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderError,
    StreamChunk,
    UsageInfo,
)
from backend.gateway.secrets import get_provider_key
from backend.utils.tool_ids import sanitize_tool_id

_BASE_URL = "https://api.openai.com/v1"

_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4-turbo": (10.00, 30.00),
    "o1-preview": (15.00, 60.00),
    "o1-mini": (3.00, 12.00),
    "o3-mini": (1.10, 4.40),
}


def _sanitize_tool_calls_list(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deep-sanitize tool call IDs in an OpenAI-format tool_calls list."""
    sanitized = []
    for tc in tool_calls:
        tc_copy = dict(tc)
        if "id" in tc_copy:
            tc_copy["id"] = sanitize_tool_id(tc_copy["id"])
        sanitized.append(tc_copy)
    return sanitized


def _messages_to_openai(messages: list) -> list[dict[str, Any]]:
    result = []
    for m in messages:
        msg: dict[str, Any] = {"role": m.role, "content": m.content}
        if m.name:
            msg["name"] = m.name
        if m.tool_call_id:
            msg["tool_call_id"] = sanitize_tool_id(m.tool_call_id)
        if m.tool_calls:
            msg["tool_calls"] = _sanitize_tool_calls_list(m.tool_calls)
        result.append(msg)
    return result


class OpenAIAdapter(BaseProviderAdapter):
    provider_name = "openai"

    def __init__(self) -> None:
        secret = get_provider_key("openai")
        self._api_key = secret.get_secret_value() if secret else ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _build_body(self, request: ChatCompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": _messages_to_openai(request.messages),
        }
        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = request.tools
        if request.tool_choice:
            body["tool_choice"] = request.tool_choice
        return body

    async def chat_complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if not self._api_key:
            raise ProviderError("OpenAI API key not configured", 503, self.provider_name)
        body = self._build_body(request)
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                resp = await client.post(f"{_BASE_URL}/chat/completions", headers=self._headers(), json=body)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ProviderError(str(e), e.response.status_code, self.provider_name)
            except httpx.RequestError as e:
                raise ProviderError(str(e), 503, self.provider_name)

        data = resp.json()
        choice = data["choices"][0]
        usage_data = data.get("usage", {})
        msg = choice["message"]
        return ChatCompletionResponse(
            id=data.get("id", f"openai-{uuid.uuid4().hex[:12]}"),
            model=data.get("model", request.model),
            provider=self.provider_name,
            content=msg.get("content", "") or "",
            finish_reason=choice.get("finish_reason", "stop"),
            usage=UsageInfo(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            ),
            tool_calls=msg.get("tool_calls"),
            raw=data,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncIterator[StreamChunk]:  # type: ignore[override]
        if not self._api_key:
            raise ProviderError("OpenAI API key not configured", 503, self.provider_name)
        body = self._build_body(request)
        body["stream"] = True
        body["stream_options"] = {"include_usage": True}
        comp_id = f"openai-{uuid.uuid4().hex[:12]}"
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                async with client.stream(
                    "POST", f"{_BASE_URL}/chat/completions", headers=self._headers(), json=body
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload.strip() == "[DONE]":
                            break
                        try:
                            chunk_data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choice = chunk_data["choices"][0] if chunk_data.get("choices") else {}
                        delta = choice.get("delta", {})
                        usage_data = chunk_data.get("usage")
                        usage = None
                        if usage_data:
                            usage = UsageInfo(
                                prompt_tokens=usage_data.get("prompt_tokens", 0),
                                completion_tokens=usage_data.get("completion_tokens", 0),
                                total_tokens=usage_data.get("total_tokens", 0),
                            )
                        yield StreamChunk(
                            id=chunk_data.get("id", comp_id),
                            model=request.model,
                            provider=self.provider_name,
                            delta_content=delta.get("content"),
                            delta_tool_calls=delta.get("tool_calls"),
                            finish_reason=choice.get("finish_reason"),
                            usage=usage,
                        )
            except httpx.RequestError as e:
                raise ProviderError(str(e), 503, self.provider_name)

    async def list_models(self) -> list[str]:
        return list(_MODEL_COSTS.keys())

    async def health_check(self) -> bool:
        if not self._api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{_BASE_URL}/models", headers=self._headers())
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        costs = _MODEL_COSTS.get(model)
        if not costs:
            return 0.0
        return (tokens_in * costs[0] + tokens_out * costs[1]) / 1_000_000
