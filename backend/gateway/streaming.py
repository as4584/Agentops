"""
Streaming Support — SSE normalization and tool call ID sanitization.
====================================================================
Converts provider-specific stream formats to a canonical OpenAI SSE
wire format.  Tool call IDs are sanitized on outbound requests
(canonical → short safe ID) and desanitized on inbound responses.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, AsyncIterator

from backend.gateway.adapters.base import StreamChunk, UsageInfo
from backend.utils.tool_ids import sanitize_tool_id


# ---------------------------------------------------------------------------
# Tool call ID sanitization
# ---------------------------------------------------------------------------
# Some providers emit long/complex IDs; we normalize to agp_tc_{hex12}
# and maintain a per-request mapping table.

class ToolIdSanitizer:
    """Bidirectional mapping of canonical ↔ sanitized tool call IDs.
    
    All sanitized IDs match the OpenAI/Copilot pattern: ^[a-zA-Z0-9_-]{1,64}$
    This pattern is also compatible with Anthropic's API requirements.
    """

    def __init__(self) -> None:
        self._canon_to_safe: dict[str, str] = {}
        self._safe_to_canon: dict[str, str] = {}

    def sanitize(self, canonical_id: str) -> str:
        """Return a safe ID for an outbound tool call.
        
        The returned ID matches ^[a-zA-Z0-9_-]+$ pattern required by
        OpenAI, Copilot, and Anthropic APIs.
        """
        if canonical_id in self._canon_to_safe:
            return self._canon_to_safe[canonical_id]
        # Use sanitize_tool_id to ensure Anthropic compatibility
        safe = sanitize_tool_id(f"agp_tc_{uuid.uuid4().hex[:12]}")
        self._canon_to_safe[canonical_id] = safe
        self._safe_to_canon[safe] = canonical_id
        return safe

    def desanitize(self, safe_id: str) -> str:
        """Recover original ID from sanitized ID (passthrough if unknown)."""
        return self._safe_to_canon.get(safe_id, safe_id)

    def sanitize_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Sanitize IDs in an outbound tool_calls list."""
        result = []
        for tc in tool_calls:
            sanitized = dict(tc)
            sanitized["id"] = self.sanitize(tc.get("id", ""))
            result.append(sanitized)
        return result

    def desanitize_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Restore canonical tool_call_id in inbound tool role messages."""
        result = []
        for m in messages:
            msg = dict(m)
            if msg.get("role") == "tool" and "tool_call_id" in msg:
                msg["tool_call_id"] = self.desanitize(msg["tool_call_id"])
            result.append(msg)
        return result


# ---------------------------------------------------------------------------
# SSE stream normalization
# ---------------------------------------------------------------------------

async def stream_to_openai_sse(
    chunks: AsyncIterator[StreamChunk],
    sanitizer: ToolIdSanitizer | None = None,
) -> AsyncIterator[str]:
    """Convert provider StreamChunks to OpenAI-compatible SSE lines.

    Yields strings of the form "data: {json}\\n\\n" (and "data: [DONE]\\n\\n").
    """
    async for chunk in chunks:
        delta: dict[str, Any] = {}

        if chunk.delta_content is not None:
            delta["content"] = chunk.delta_content

        if chunk.delta_tool_calls:
            tc = chunk.delta_tool_calls
            if sanitizer:
                tc = sanitizer.sanitize_tool_calls(tc)
            delta["tool_calls"] = tc

        if chunk.finish_reason:
            delta["content"] = delta.get("content")  # may be None

        payload: dict[str, Any] = {
            "id": chunk.id,
            "object": "chat.completion.chunk",
            "model": chunk.model,
            "choices": [
                {
                    "index": 0,
                    "delta": delta,
                    "finish_reason": chunk.finish_reason,
                }
            ],
        }

        if chunk.usage:
            payload["usage"] = {
                "prompt_tokens": chunk.usage.prompt_tokens,
                "completion_tokens": chunk.usage.completion_tokens,
                "total_tokens": chunk.usage.total_tokens,
            }

        yield f"data: {json.dumps(payload)}\n\n"

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# Combine parallel tool calls (for providers that split across chunks)
# ---------------------------------------------------------------------------

class ToolCallAccumulator:
    """Accumulate streaming tool call deltas into complete tool calls."""

    def __init__(self) -> None:
        self._by_index: dict[int, dict[str, Any]] = {}

    def update(self, tool_call_deltas: list[dict[str, Any]]) -> None:
        for tc in tool_call_deltas:
            idx = tc.get("index", 0)
            if idx not in self._by_index:
                self._by_index[idx] = {
                    "id": "", "type": "function",
                    "function": {"name": "", "arguments": ""}
                }
            entry = self._by_index[idx]
            if tc.get("id"):
                entry["id"] = tc["id"]
            fn = tc.get("function", {})
            if fn.get("name"):
                entry["function"]["name"] += fn["name"]
            if fn.get("arguments"):
                entry["function"]["arguments"] += fn["arguments"]

    def complete(self) -> list[dict[str, Any]]:
        return [self._by_index[i] for i in sorted(self._by_index)]
