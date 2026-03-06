"""
Anthropic Provider Adapter — direct Anthropic Messages API.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import httpx

from backend.gateway.adapters.base import (
    BaseProviderAdapter, ChatCompletionRequest, ChatCompletionResponse,
    StreamChunk, UsageInfo, ProviderError,
)
from backend.gateway.secrets import get_provider_key
from backend.utils.tool_ids import sanitize_tool_id

_BASE_URL = "https://api.anthropic.com/v1"
_API_VERSION = "2023-06-01"

_MODEL_COSTS: dict[str, tuple[float, float]] = {
    "claude-opus-4-5": (15.00, 75.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-3-5": (0.80, 4.00),
    "claude-3-opus-20240229": (15.00, 75.00),
    "claude-3-sonnet-20240229": (3.00, 15.00),
    "claude-3-haiku-20240307": (0.25, 1.25),
}


def _sanitize_content_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize tool_use / tool_result IDs inside a pre-existing content list."""
    result: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict):
            result.append(block)
            continue
        btype = block.get("type")
        if btype == "tool_use" and "id" in block:
            sanitized = dict(block)
            sanitized["id"] = sanitize_tool_id(block["id"])
            result.append(sanitized)
        elif btype == "tool_result" and "tool_use_id" in block:
            sanitized = dict(block)
            sanitized["tool_use_id"] = sanitize_tool_id(block["tool_use_id"])
            result.append(sanitized)
        else:
            result.append(block)
    return result


def _convert_messages(
    messages: list,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Split system prompt out; convert role=tool to expected format."""
    system: str | None = None
    converted = []
    for m in messages:
        if m.role == "system":
            system = m.content if isinstance(m.content, str) else json.dumps(m.content)
            continue
        if m.role == "tool":
            # Always sanitize — even empty/None IDs get a deterministic fallback
            tool_use_id = sanitize_tool_id(m.tool_call_id or "")
            converted.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                }],
            })
            continue
        content = m.content
        if isinstance(content, list):
            # Sanitize any tool_use / tool_result IDs embedded in the list
            msg_content = _sanitize_content_blocks(content)
        elif content is None:
            # Assistant messages with only tool_calls may have None content
            msg_content = []
        else:
            msg_content = [{"type": "text", "text": content}]
        msg: dict[str, Any] = {"role": m.role, "content": msg_content}
        if m.tool_calls:
            # Sanitize tool_use IDs to match Anthropic's ^[a-zA-Z0-9_-]+$ pattern
            tc_blocks = [
                {"type": "tool_use", "id": sanitize_tool_id(tc["id"]), "name": tc["function"]["name"],
                 "input": json.loads(tc["function"].get("arguments", "{}"))}
                for tc in m.tool_calls
            ]
            msg["content"] = (msg_content or []) + tc_blocks
        elif not msg_content:
            # Anthropic requires at least one content block per message
            msg["content"] = [{"type": "text", "text": ""}]
        converted.append(msg)
    return system, converted


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI tool schema to Anthropic format."""
    result = []
    for t in tools:
        if t.get("type") == "function":
            fn = t["function"]
            result.append({
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {}),
            })
    return result


class AnthropicAdapter(BaseProviderAdapter):
    provider_name = "anthropic"

    def __init__(self) -> None:
        secret = get_provider_key("anthropic")
        self._api_key = secret.get_secret_value() if secret else ""

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        }

    def _build_body(self, request: ChatCompletionRequest, stream: bool = False) -> dict[str, Any]:
        system, messages = _convert_messages(request.messages)
        body: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            "max_tokens": request.max_tokens or 4096,
            "stream": stream,
        }
        if system:
            body["system"] = system
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.tools:
            body["tools"] = _convert_tools(request.tools)
        return body

    async def chat_complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        if not self._api_key:
            raise ProviderError("Anthropic API key not configured", 503, self.provider_name)
        body = self._build_body(request)
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                resp = await client.post(f"{_BASE_URL}/messages", headers=self._headers(), json=body)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ProviderError(str(e), e.response.status_code, self.provider_name)
            except httpx.RequestError as e:
                raise ProviderError(str(e), 503, self.provider_name)

        data = resp.json()
        text_content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_content += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block.get("input", {})),
                    }
                })
        usage_data = data.get("usage", {})
        return ChatCompletionResponse(
            id=data.get("id", f"anthro-{uuid.uuid4().hex[:12]}"),
            model=data.get("model", request.model),
            provider=self.provider_name,
            content=text_content,
            finish_reason=data.get("stop_reason", "end_turn"),
            usage=UsageInfo(
                prompt_tokens=usage_data.get("input_tokens", 0),
                completion_tokens=usage_data.get("output_tokens", 0),
                total_tokens=usage_data.get("input_tokens", 0) + usage_data.get("output_tokens", 0),
            ),
            tool_calls=tool_calls or None,
            raw=data,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncIterator[StreamChunk]:
        if not self._api_key:
            raise ProviderError("Anthropic API key not configured", 503, self.provider_name)
        body = self._build_body(request, stream=True)
        comp_id = f"anthro-{uuid.uuid4().hex[:12]}"
        async with httpx.AsyncClient(timeout=120) as client:
            try:
                async with client.stream(
                    "POST", f"{_BASE_URL}/messages", headers=self._headers(), json=body
                ) as resp:
                    resp.raise_for_status()
                    tokens_in = 0
                    tokens_out = 0
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        try:
                            ev = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        ev_type = ev.get("type")
                        if ev_type == "content_block_delta":
                            delta = ev.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield StreamChunk(
                                    id=comp_id, model=request.model, provider=self.provider_name,
                                    delta_content=delta.get("text", ""),
                                )
                        elif ev_type == "message_delta":
                            usage = ev.get("usage", {})
                            tokens_out = usage.get("output_tokens", tokens_out)
                        elif ev_type == "message_start":
                            usage = ev.get("message", {}).get("usage", {})
                            tokens_in = usage.get("input_tokens", 0)
                        elif ev_type == "message_stop":
                            yield StreamChunk(
                                id=comp_id, model=request.model, provider=self.provider_name,
                                delta_content=None, finish_reason="end_turn",
                                usage=UsageInfo(
                                    prompt_tokens=tokens_in,
                                    completion_tokens=tokens_out,
                                    total_tokens=tokens_in + tokens_out,
                                ),
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
                resp = await client.get(
                    f"{_BASE_URL}/models",
                    headers=self._headers(),
                )
                return resp.status_code in (200, 404)  # 404 = auth ok, endpoint missing
        except Exception:
            return False

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        costs = _MODEL_COSTS.get(model)
        if not costs:
            return 0.0
        return (tokens_in * costs[0] + tokens_out * costs[1]) / 1_000_000
