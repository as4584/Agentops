"""
Gateway Routes — OpenAI-compatible /v1/* endpoints.
====================================================
POST /v1/chat/completions    — Chat completion (streaming + non-streaming)
POST /v1/completions         — Legacy text completion
GET  /v1/models              — List models available to this key
GET  /v1/health              — Gateway health
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from backend.config_gateway import (
    GATEWAY_MAX_MESSAGES,
    GATEWAY_MAX_PROMPT_LENGTH,
    GATEWAY_MAX_RESPONSE_TOKENS,
)
from backend.gateway import get_gateway_router
from backend.gateway.acl import get_acl
from backend.gateway.adapters import ChatCompletionRequest, ChatMessage, ProviderError
from backend.gateway.health import check_prompt_safety, get_health_monitor
from backend.gateway.middleware import GatewayContext, require_gateway_auth
from backend.gateway.ratelimit import get_rate_limiter
from backend.gateway.streaming import ToolIdSanitizer, stream_to_openai_sse
from backend.gateway.usage import get_usage_tracker
from backend.llm.unified_registry import UNIFIED_MODEL_REGISTRY
from backend.utils.tool_ids import sanitize_tool_id

router = APIRouter(prefix="/v1", tags=["Gateway"])


# ---------------------------------------------------------------------------
# Request / Response Pydantic Models
# ---------------------------------------------------------------------------


class MessageInput(BaseModel):
    role: str
    content: str | list[dict[str, Any]]
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"system", "user", "assistant", "tool"}
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}")
        return v


class ChatCompletionInput(BaseModel):
    model: str
    messages: list[MessageInput] = Field(..., min_length=1)
    max_tokens: int | None = Field(None, ge=1, le=GATEWAY_MAX_RESPONSE_TOKENS)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    stream: bool = False
    tools: list[dict[str, Any]] | None = None
    tool_choice: str | dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list[MessageInput]) -> list[MessageInput]:
        if len(v) > GATEWAY_MAX_MESSAGES:
            raise ValueError(f"Too many messages (max {GATEWAY_MAX_MESSAGES})")
        return v


class LegacyCompletionInput(BaseModel):
    model: str
    prompt: str = Field(..., max_length=GATEWAY_MAX_PROMPT_LENGTH)
    max_tokens: int | None = Field(None, ge=1, le=GATEWAY_MAX_RESPONSE_TOKENS)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    stream: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate_content_length(messages: list[MessageInput]) -> None:
    total = sum(len(m.content) if isinstance(m.content, str) else len(json.dumps(m.content)) for m in messages)
    if total > GATEWAY_MAX_PROMPT_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Total prompt length {total} exceeds limit {GATEWAY_MAX_PROMPT_LENGTH}",
        )


def _check_model_access(ctx: GatewayContext, model_id: str) -> None:
    acl = get_acl()
    if not acl.is_allowed(ctx.key_id, model_id):
        raise HTTPException(
            status_code=403,
            detail=f"Model {model_id!r} is not accessible with this API key",
        )


def _check_quota(ctx: GatewayContext) -> None:
    tracker = get_usage_tracker()
    ok, reason = tracker.check_quota(ctx.key_id, ctx.quota_daily_usd, ctx.quota_monthly_usd)
    if not ok:
        raise HTTPException(status_code=429, detail=f"Quota exceeded: {reason}")


def _sanitize_tool_calls_at_boundary(
    tool_calls: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Sanitize tool call IDs at the API boundary before they reach any adapter."""
    if not tool_calls:
        return tool_calls
    sanitized = []
    for tc in tool_calls:
        tc_copy = dict(tc)
        if "id" in tc_copy:
            tc_copy["id"] = sanitize_tool_id(tc_copy["id"])
        sanitized.append(tc_copy)
    return sanitized


def _to_chat_request(body: ChatCompletionInput) -> ChatCompletionRequest:
    return ChatCompletionRequest(
        model=body.model,
        messages=[
            ChatMessage(
                role=m.role,
                content=m.content,
                name=m.name,
                tool_call_id=sanitize_tool_id(m.tool_call_id) if m.tool_call_id else m.tool_call_id,
                tool_calls=_sanitize_tool_calls_at_boundary(m.tool_calls),
            )
            for m in body.messages
        ],
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        stream=body.stream,
        tools=body.tools,
        tool_choice=body.tool_choice,
    )


def _response_to_openai(resp: Any, model: str) -> dict[str, Any]:
    return {
        "id": resp.id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": resp.content,
                    "tool_calls": resp.tool_calls,
                },
                "finish_reason": resp.finish_reason,
                "logprobs": None,
            }
        ],
        "usage": {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        },
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionInput,
    request: Request,
    ctx: GatewayContext = Depends(require_gateway_auth),
) -> Any:
    # Access control
    _check_model_access(ctx, body.model)
    _check_quota(ctx)

    # Request validation
    _validate_content_length(body.messages)

    # Content safety on user messages
    for msg in body.messages:
        if msg.role == "user" and isinstance(msg.content, str):
            safe, reason = check_prompt_safety(msg.content)
            if not safe:
                raise HTTPException(status_code=400, detail=f"Content safety: {reason}")

    # TPM pre-check (rough estimate: 1 word ≈ 1.33 tokens)
    est_tokens = sum(len(str(m.content).split()) * 4 // 3 for m in body.messages)
    limiter = get_rate_limiter()
    tpm_ok, _ = limiter.check_tpm(ctx.key_id, est_tokens, ctx.quota_tpm)
    if not tpm_ok:
        raise HTTPException(status_code=429, detail="Token-per-minute quota exceeded")

    chat_req = _to_chat_request(body)
    gateway = get_gateway_router()

    if body.stream:
        sanitizer = ToolIdSanitizer()

        async def _sse_gen():
            try:
                async for sse_line in stream_to_openai_sse(gateway.stream(chat_req, key_id=ctx.key_id), sanitizer):
                    yield sse_line
            except ProviderError as e:
                error_payload = json.dumps(
                    {"error": {"message": str(e), "type": "provider_error", "code": e.status_code}}
                )
                yield f"data: {error_payload}\n\n"

        return StreamingResponse(
            _sse_gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    try:
        response = await gateway.complete(chat_req, key_id=ctx.key_id)
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    return JSONResponse(_response_to_openai(response, body.model))


@router.post("/completions")
async def legacy_completions(
    body: LegacyCompletionInput,
    ctx: GatewayContext = Depends(require_gateway_auth),
) -> Any:
    """Legacy /v1/completions — internally routed as chat completion."""
    _check_model_access(ctx, body.model)
    _check_quota(ctx)

    safe, reason = check_prompt_safety(body.prompt)
    if not safe:
        raise HTTPException(status_code=400, detail=f"Content safety: {reason}")

    chat_req = ChatCompletionRequest(
        model=body.model,
        messages=[ChatMessage(role="user", content=body.prompt)],
        max_tokens=body.max_tokens,
        temperature=body.temperature,
        stream=False,
    )
    gateway = get_gateway_router()
    try:
        response = await gateway.complete(chat_req, key_id=ctx.key_id)
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))

    return JSONResponse(
        {
            "id": response.id,
            "object": "text_completion",
            "created": int(time.time()),
            "model": body.model,
            "choices": [
                {
                    "text": response.content,
                    "index": 0,
                    "logprobs": None,
                    "finish_reason": response.finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            },
        }
    )


@router.get("/models")
async def list_models(
    ctx: GatewayContext = Depends(require_gateway_auth),
) -> Any:
    """List models available to this API key."""
    acl = get_acl()
    all_model_ids = list(UNIFIED_MODEL_REGISTRY.keys())
    allowed = acl.filter_allowed_models(ctx.key_id, all_model_ids)
    data = []
    for mid in allowed:
        spec = UNIFIED_MODEL_REGISTRY.get(mid)
        data.append(
            {
                "id": mid,
                "object": "model",
                "created": 0,
                "owned_by": spec.provider.value if spec else "unknown",
                "context_window": spec.context_window if spec else None,
                "supports_tools": spec.supports_tools if spec else False,
            }
        )
    return JSONResponse({"object": "list", "data": data})


@router.get("/health")
async def gateway_health() -> Any:
    monitor = get_health_monitor()
    status = monitor.get_status()
    return JSONResponse({"status": "ok", "gateway": "agentop", **status})
