"""Deterministic tests for gateway core — _sanitize_request, _resolve_provider, ToolIdSanitizer.

No network. No Ollama. Pure logic.
"""

from __future__ import annotations

from backend.gateway import _resolve_provider, _sanitize_request
from backend.gateway.adapters import ChatCompletionRequest, ChatMessage
from backend.gateway.streaming import ToolIdSanitizer

# ── _resolve_provider ────────────────────────────────────────────────


class TestResolveProvider:
    def test_ollama_prefix(self):
        assert _resolve_provider("ollama/llama3.2") == "ollama"

    def test_ollama_colon_heuristic(self):
        assert _resolve_provider("llama3.2:latest") == "ollama"

    def test_openai_gpt_prefix(self):
        assert _resolve_provider("gpt-4") == "openai"

    def test_openai_o1_prefix(self):
        assert _resolve_provider("o1-mini") == "openai"

    def test_anthropic_claude_prefix(self):
        assert _resolve_provider("claude-3-opus") == "anthropic"

    def test_unknown_defaults_to_openrouter(self):
        assert _resolve_provider("some-random-model-xyz") == "openrouter"

    def test_gpt_colon_goes_to_openai_not_ollama(self):
        # Colons normally trigger ollama, but gpt- prefix override should win
        assert _resolve_provider("gpt-4:latest") == "openai"

    def test_claude_colon_goes_to_anthropic(self):
        assert _resolve_provider("claude-3:latest") == "anthropic"


# ── _sanitize_request ────────────────────────────────────────────────


class TestSanitizeRequest:
    def test_passthrough_when_no_tool_calls(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="user", content="hello")],
        )
        sanitized = _sanitize_request(req)
        assert sanitized.messages[0].content == "hello"
        assert sanitized.model == "test"

    def test_sanitizes_tool_call_id(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[ChatMessage(role="tool", content="result", tool_call_id="call_abc123!@#")],
        )
        sanitized = _sanitize_request(req)
        tool_call_id = sanitized.messages[0].tool_call_id
        assert tool_call_id is not None
        # sanitize_tool_id strips non-alphanumeric chars
        assert "!" not in tool_call_id
        assert "@" not in tool_call_id

    def test_sanitizes_tool_calls_list(self):
        req = ChatCompletionRequest(
            model="test",
            messages=[
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[{"id": "bad!id#123", "type": "function", "function": {"name": "test"}}],
                )
            ],
        )
        sanitized = _sanitize_request(req)
        tc_id = sanitized.messages[0].tool_calls[0]["id"]
        assert "!" not in tc_id
        assert "#" not in tc_id

    def test_preserves_message_count(self):
        messages = [
            ChatMessage(role="system", content="sys"),
            ChatMessage(role="user", content="hi"),
            ChatMessage(role="assistant", content="hello"),
        ]
        req = ChatCompletionRequest(model="test", messages=messages)
        sanitized = _sanitize_request(req)
        assert len(sanitized.messages) == 3


# ── ToolIdSanitizer ──────────────────────────────────────────────────


class TestToolIdSanitizer:
    def test_sanitize_returns_stable_id(self):
        s = ToolIdSanitizer()
        safe = s.sanitize("original_123")
        # Same input returns same safe ID
        assert s.sanitize("original_123") == safe

    def test_desanitize_roundtrip(self):
        s = ToolIdSanitizer()
        safe = s.sanitize("my_canonical_id")
        assert s.desanitize(safe) == "my_canonical_id"

    def test_desanitize_unknown_passthrough(self):
        s = ToolIdSanitizer()
        assert s.desanitize("unknown_id") == "unknown_id"

    def test_different_canonical_ids_get_different_safe_ids(self):
        s = ToolIdSanitizer()
        safe1 = s.sanitize("id_a")
        safe2 = s.sanitize("id_b")
        assert safe1 != safe2

    def test_sanitize_tool_calls_list(self):
        s = ToolIdSanitizer()
        calls = [
            {"id": "call_1", "type": "function"},
            {"id": "call_2", "type": "function"},
        ]
        result = s.sanitize_tool_calls(calls)
        assert len(result) == 2
        assert result[0]["id"] != "call_1"  # Should be sanitized
        assert result[0]["type"] == "function"  # Non-id fields preserved

    def test_desanitize_messages(self):
        s = ToolIdSanitizer()
        safe = s.sanitize("original_call")
        messages = [
            {"role": "tool", "content": "result", "tool_call_id": safe},
            {"role": "user", "content": "hello"},
        ]
        result = s.desanitize_messages(messages)
        assert result[0]["tool_call_id"] == "original_call"
        assert result[1]["content"] == "hello"  # Non-tool messages untouched

    def test_safe_id_matches_api_pattern(self):
        """Safe IDs must match ^[a-zA-Z0-9_-]+$ for OpenAI/Anthropic compat."""
        import re

        s = ToolIdSanitizer()
        safe = s.sanitize("weird id with spaces and !@#$")
        assert re.match(r"^[a-zA-Z0-9_-]+$", safe)
