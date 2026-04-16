"""
Tool call/result converters — Sprint 1 execution contract.
==========================================================
All normalization between raw execution dicts (legacy tool path) and the
canonical typed models (ToolCall, ToolResult) lives here.

Rules:
- No imports from backend.agents — avoids circular dependencies.
- Every function is pure (no I/O, no side effects).
- Converters are lossless for the fields the v2 runtime actually uses.
"""

from __future__ import annotations

import json
from typing import Any

from backend.models import ToolCall, ToolCallStatus, ToolResult


# ---------------------------------------------------------------------------
# Raw dict → ToolResult
# ---------------------------------------------------------------------------


def tool_result_from_raw_dict(
    call_id: str,
    tool_name: str,
    raw: dict[str, Any],
    *,
    duration_ms: float | None = None,
) -> ToolResult:
    """Normalize a raw tool-execution dict into a canonical ToolResult.

    The raw dict is the format historically returned by ``execute_tool`` and
    the ``_execute_tool`` wrapper.  Error indicators in that dict are mapped
    to structured ``ToolCallStatus`` values so the runtime can branch without
    string-matching.
    """
    # --- Error cases (order matters: check explicit error before success) ---

    if raw.get("error"):
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolCallStatus.EXECUTION_ERROR,
            error=str(raw["error"]),
            duration_ms=duration_ms,
        )

    if raw.get("success") is False:
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolCallStatus.EXECUTION_ERROR,
            error=str(raw.get("message") or "operation failed"),
            duration_ms=duration_ms,
        )

    if raw.get("reachable") is False:
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolCallStatus.EXECUTION_ERROR,
            error=f"unreachable: {raw.get('url', '?')}",
            duration_ms=duration_ms,
        )

    if raw.get("exists") is False:
        return ToolResult(
            call_id=call_id,
            tool_name=tool_name,
            status=ToolCallStatus.EXECUTION_ERROR,
            error="file not found",
            duration_ms=duration_ms,
        )

    # --- Success: extract meaningful content, strip internal metadata ---
    stripped = {k: v for k, v in raw.items() if k not in ("_health",)}
    content: Any = (
        stripped.get("content")
        or stripped.get("stdout")
        or stripped
    )

    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status=ToolCallStatus.SUCCESS,
        content=content,
        duration_ms=duration_ms,
    )


def tool_result_unavailable(call_id: str, tool_name: str, reason: str) -> ToolResult:
    """Return an explicit UNAVAILABLE result (tool not registered / not allowed)."""
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status=ToolCallStatus.UNAVAILABLE,
        error=reason,
    )


def tool_result_degraded(call_id: str, tool_name: str, reason: str) -> ToolResult:
    """Return an explicit DEGRADED result (fallback path was activated)."""
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status=ToolCallStatus.DEGRADED,
        error=reason,
        degraded=True,
    )


# ---------------------------------------------------------------------------
# OpenAI-format dicts ↔ canonical types
# ---------------------------------------------------------------------------


def tool_call_from_openai_dict(d: dict[str, Any]) -> ToolCall:
    """Convert an OpenAI-format tool_call dict to a canonical ToolCall.

    OpenAI format::

        {
            "id": "call_abc123",
            "type": "function",
            "function": {"name": "safe_shell", "arguments": "{\"cmd\": \"pwd\"}"},
        }
    """
    fn = d.get("function") or {}
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            args = {}
    return ToolCall(
        id=d.get("id") or "",
        name=fn.get("name") or "",
        arguments=args if isinstance(args, dict) else {},
    )


def tool_call_to_openai_dict(tc: ToolCall) -> dict[str, Any]:
    """Convert a canonical ToolCall to an OpenAI-format tool_call dict.

    Used when forwarding internal tool calls to OpenAI-compatible provider APIs.
    Arguments are serialized to a JSON string as the OpenAI API requires.
    """
    return {
        "id": tc.id,
        "type": "function",
        "function": {
            "name": tc.name,
            "arguments": json.dumps(tc.arguments),
        },
    }


def tool_result_to_tool_message(result: ToolResult) -> dict[str, Any]:
    """Convert a ToolResult to an OpenAI-format tool-role message.

    Suitable for inserting into conversation history after a tool call so
    the model can observe the outcome on the next turn.
    """
    if result.status == ToolCallStatus.SUCCESS:
        content = str(result.content) if result.content is not None else ""
    else:
        content = f"Error ({result.status.value}): {result.error or 'unknown'}"
    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "name": result.tool_name,
        "content": content,
    }


# ---------------------------------------------------------------------------
# Ollama-format ↔ canonical types
# ---------------------------------------------------------------------------


def tool_call_from_ollama_dict(d: dict[str, Any]) -> ToolCall:
    """Convert an Ollama-format tool_call dict to a canonical ToolCall.

    Ollama format (v0.3+)::

        {"function": {"name": "safe_shell", "arguments": {"cmd": "pwd"}}}

    Note: Ollama does not return a call ``id``; a placeholder is generated
    by the caller.
    """
    fn = d.get("function") or {}
    args = fn.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (json.JSONDecodeError, ValueError):
            args = {}
    return ToolCall(
        id="",  # caller must set a real ID
        name=fn.get("name") or "",
        arguments=args if isinstance(args, dict) else {},
    )


def tool_schema_to_ollama(openai_tool: dict[str, Any]) -> dict[str, Any]:
    """Convert an OpenAI-format tool schema to the Ollama tool-schema format.

    OpenAI::

        {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}

    Ollama accepts the same outer structure, so this is effectively an
    identity transform — included for clarity and testability.
    """
    return openai_tool  # Ollama v0.3+ accepts the same schema format
