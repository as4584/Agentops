"""
Ollama Provider Adapter — local HTTP bridge.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator

import httpx

from backend.config import OLLAMA_BASE_URL, OLLAMA_TIMEOUT
from backend.gateway.adapters.base import (
    BaseProviderAdapter,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ProviderError,
    StreamChunk,
    UsageInfo,
)
from backend.models.tool_converters import tool_schema_to_ollama


def _messages_to_ollama(messages: list) -> list[dict]:
    result = []
    for m in messages:
        content = m.content if isinstance(m.content, str) else json.dumps(m.content)
        entry: dict = {"role": m.role, "content": content}
        # Forward tool_calls if present (assistant turn that made tool calls)
        if m.tool_calls:
            entry["tool_calls"] = m.tool_calls
        # Forward tool_call_id for tool-role messages
        if m.tool_call_id:
            entry["tool_call_id"] = m.tool_call_id
        result.append(entry)
    return result


def _ollama_tool_calls_to_openai(
    tool_calls: list[dict],
) -> list[dict]:
    """Convert Ollama tool_calls format to OpenAI-compatible format.

    Ollama v0.3+ returns::

        [{"function": {"name": "...", "arguments": {...}}}]

    OpenAI format expected by downstream consumers::

        [{"id": "...", "type": "function", "function": {"name": "...", "arguments": "..."}}]
    """
    result = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        args = fn.get("arguments", {})
        if not isinstance(args, str):
            args = json.dumps(args)
        result.append(
            {
                "id": f"ollama-tc-{uuid.uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "arguments": args,
                },
            }
        )
    return result


class OllamaAdapter(BaseProviderAdapter):
    provider_name = "ollama"

    def __init__(self, base_url: str = OLLAMA_BASE_URL, timeout: int = OLLAMA_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def chat_complete(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload: dict = {
            "model": request.model,
            "messages": _messages_to_ollama(request.messages),
            "stream": False,
        }
        if request.max_tokens:
            payload.setdefault("options", {})["num_predict"] = request.max_tokens
        if request.temperature is not None:
            payload.setdefault("options", {})["temperature"] = request.temperature

        # PR 4: Forward tools so Ollama v0.3+ can use native function calling.
        if request.tools:
            payload["tools"] = [tool_schema_to_ollama(t) for t in request.tools]

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                resp = await client.post(f"{self._base_url}/api/chat", json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ProviderError(str(e), e.response.status_code, self.provider_name)
            except httpx.RequestError as e:
                raise ProviderError(str(e), 503, self.provider_name)

        data = resp.json()
        msg = data.get("message", {})
        usage = UsageInfo(
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            total_tokens=data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
        )

        # PR 4: Parse tool_calls from the Ollama response and normalise to OpenAI format.
        raw_tool_calls: list[dict] | None = msg.get("tool_calls") or None
        normalized_tool_calls: list[dict] | None = None
        if raw_tool_calls:
            normalized_tool_calls = _ollama_tool_calls_to_openai(raw_tool_calls)

        return ChatCompletionResponse(
            id=f"ollama-{uuid.uuid4().hex[:12]}",
            model=request.model,
            provider=self.provider_name,
            content=msg.get("content", "") or "",
            finish_reason=data.get("done_reason", "stop"),
            usage=usage,
            tool_calls=normalized_tool_calls,
            raw=data,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncIterator[StreamChunk]:  # type: ignore[override]
        payload: dict = {
            "model": request.model,
            "messages": _messages_to_ollama(request.messages),
            "stream": True,
        }
        comp_id = f"ollama-{uuid.uuid4().hex[:12]}"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                async with client.stream("POST", f"{self._base_url}/api/chat", json=payload) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        done = chunk.get("done", False)
                        delta = chunk.get("message", {}).get("content", "")
                        usage = None
                        if done:
                            usage = UsageInfo(
                                prompt_tokens=chunk.get("prompt_eval_count", 0),
                                completion_tokens=chunk.get("eval_count", 0),
                                total_tokens=chunk.get("prompt_eval_count", 0) + chunk.get("eval_count", 0),
                            )
                        yield StreamChunk(
                            id=comp_id,
                            model=request.model,
                            provider=self.provider_name,
                            delta_content=delta if not done else None,
                            finish_reason="stop" if done else None,
                            usage=usage,
                        )
            except httpx.RequestError as e:
                raise ProviderError(str(e), 503, self.provider_name)

    async def list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        return 0.0  # local — no API cost
