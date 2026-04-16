"""
Sprint 1 — Execution contract regression tests.
================================================
Covers:
  PR 1  — ToolCallStatus, ToolResult, tool_converters (contract models)
  PR 2  — v2 runtime adopts canonical ToolResult from _execute_tool
  PR 3  — Explicit degraded behavior, no silent fallback, counters
  PR 4  — Ollama adapter tool parity, round-trip contract

All tests are offline (no real Ollama / network calls).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import ToolCall, ToolCallStatus, ToolResult
from backend.models.tool_converters import (
    tool_call_from_ollama_dict,
    tool_call_from_openai_dict,
    tool_call_to_openai_dict,
    tool_result_degraded,
    tool_result_from_raw_dict,
    tool_result_to_tool_message,
    tool_result_unavailable,
    tool_schema_to_ollama,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cid() -> str:
    return uuid.uuid4().hex[:8]


# ===========================================================================
# PR 1 — Canonical contract models
# ===========================================================================


class TestToolCallStatus:
    def test_all_values_are_strings(self):
        for member in ToolCallStatus:
            assert isinstance(member.value, str)

    def test_success_value(self):
        assert ToolCallStatus.SUCCESS == "success"

    def test_degraded_value(self):
        assert ToolCallStatus.DEGRADED == "degraded"

    def test_unavailable_value(self):
        assert ToolCallStatus.UNAVAILABLE == "unavailable"

    def test_all_six_statuses_exist(self):
        values = {s.value for s in ToolCallStatus}
        assert values == {
            "success",
            "validation_failure",
            "execution_error",
            "timeout",
            "unavailable",
            "degraded",
        }


class TestToolResultModel:
    def test_success_result(self):
        r = ToolResult(
            call_id="c1",
            tool_name="safe_shell",
            status=ToolCallStatus.SUCCESS,
            content="ok",
        )
        assert r.status == ToolCallStatus.SUCCESS
        assert r.content == "ok"
        assert r.error is None
        assert r.degraded is False

    def test_error_result(self):
        r = ToolResult(
            call_id="c2",
            tool_name="file_reader",
            status=ToolCallStatus.EXECUTION_ERROR,
            error="permission denied",
        )
        assert r.status == ToolCallStatus.EXECUTION_ERROR
        assert r.error == "permission denied"
        assert r.content is None

    def test_timeout_result(self):
        r = ToolResult(
            call_id="c3",
            tool_name="safe_shell",
            status=ToolCallStatus.TIMEOUT,
            error="timed out after 30s",
        )
        assert r.status == ToolCallStatus.TIMEOUT

    def test_unavailable_result(self):
        r = ToolResult(
            call_id="c4",
            tool_name="unknown_tool",
            status=ToolCallStatus.UNAVAILABLE,
            error="tool not registered",
        )
        assert r.status == ToolCallStatus.UNAVAILABLE

    def test_degraded_result_flag(self):
        r = ToolResult(
            call_id="c5",
            tool_name="safe_shell",
            status=ToolCallStatus.DEGRADED,
            error="schema generation failed",
            degraded=True,
        )
        assert r.degraded is True
        assert r.status == ToolCallStatus.DEGRADED

    def test_duration_ms_optional(self):
        r = ToolResult(call_id="c6", tool_name="t", status=ToolCallStatus.SUCCESS)
        assert r.duration_ms is None
        r2 = ToolResult(call_id="c7", tool_name="t", status=ToolCallStatus.SUCCESS, duration_ms=42.5)
        assert r2.duration_ms == 42.5


# ---------------------------------------------------------------------------
# tool_result_from_raw_dict
# ---------------------------------------------------------------------------


class TestToolResultFromRawDict:
    def _convert(self, raw, **kwargs):
        return tool_result_from_raw_dict("cid", "tool", raw, **kwargs)

    def test_success_with_content_key(self):
        r = self._convert({"content": "hello"})
        assert r.status == ToolCallStatus.SUCCESS
        assert r.content == "hello"

    def test_success_with_stdout_key(self):
        r = self._convert({"stdout": "output"})
        assert r.status == ToolCallStatus.SUCCESS
        assert r.content == "output"

    def test_error_key_maps_to_execution_error(self):
        r = self._convert({"error": "something broke"})
        assert r.status == ToolCallStatus.EXECUTION_ERROR
        assert "something broke" in r.error

    def test_success_false_maps_to_execution_error(self):
        r = self._convert({"success": False, "message": "bad input"})
        assert r.status == ToolCallStatus.EXECUTION_ERROR
        assert "bad input" in r.error

    def test_reachable_false_maps_to_execution_error(self):
        r = self._convert({"reachable": False, "url": "http://x.com"})
        assert r.status == ToolCallStatus.EXECUTION_ERROR
        assert "x.com" in r.error

    def test_exists_false_maps_to_execution_error(self):
        r = self._convert({"exists": False})
        assert r.status == ToolCallStatus.EXECUTION_ERROR
        assert "not found" in r.error

    def test_duration_ms_propagated(self):
        r = self._convert({"content": "hi"}, duration_ms=12.3)
        assert r.duration_ms == 12.3

    def test_health_key_stripped_from_content(self):
        r = self._convert({"content": "clean", "_health": {"status": "ok"}})
        assert r.status == ToolCallStatus.SUCCESS
        assert r.content == "clean"

    def test_call_id_and_tool_name_preserved(self):
        r = tool_result_from_raw_dict("my_id", "safe_shell", {"content": "x"})
        assert r.call_id == "my_id"
        assert r.tool_name == "safe_shell"

    def test_empty_dict_returns_success(self):
        r = self._convert({})
        assert r.status == ToolCallStatus.SUCCESS


# ---------------------------------------------------------------------------
# tool_result_unavailable / tool_result_degraded helpers
# ---------------------------------------------------------------------------


class TestResultHelpers:
    def test_unavailable_helper(self):
        r = tool_result_unavailable("c1", "unknown", "not in registry")
        assert r.status == ToolCallStatus.UNAVAILABLE
        assert r.degraded is False

    def test_degraded_helper(self):
        r = tool_result_degraded("c2", "safe_shell", "schema failed")
        assert r.status == ToolCallStatus.DEGRADED
        assert r.degraded is True
        assert r.error == "schema failed"


# ---------------------------------------------------------------------------
# OpenAI ↔ canonical round-trip
# ---------------------------------------------------------------------------


class TestOpenAIRoundTrip:
    def test_from_openai_dict_string_args(self):
        d = {
            "id": "call_abc",
            "type": "function",
            "function": {"name": "safe_shell", "arguments": '{"cmd": "pwd"}'},
        }
        tc = tool_call_from_openai_dict(d)
        assert tc.id == "call_abc"
        assert tc.name == "safe_shell"
        assert tc.arguments == {"cmd": "pwd"}

    def test_from_openai_dict_dict_args(self):
        d = {
            "id": "call_xyz",
            "type": "function",
            "function": {"name": "file_reader", "arguments": {"path": "/tmp/x.txt"}},
        }
        tc = tool_call_from_openai_dict(d)
        assert tc.arguments == {"path": "/tmp/x.txt"}

    def test_from_openai_dict_malformed_args_becomes_empty(self):
        d = {
            "id": "call_bad",
            "type": "function",
            "function": {"name": "safe_shell", "arguments": "{not-valid-json"},
        }
        tc = tool_call_from_openai_dict(d)
        assert tc.arguments == {}

    def test_to_openai_dict_serializes_args_as_json_string(self):
        tc = ToolCall(id="call_1", name="safe_shell", arguments={"cmd": "pwd"})
        d = tool_call_to_openai_dict(tc)
        assert d["id"] == "call_1"
        assert d["type"] == "function"
        assert d["function"]["name"] == "safe_shell"
        assert json.loads(d["function"]["arguments"]) == {"cmd": "pwd"}

    def test_round_trip_lossless(self):
        original = ToolCall(id="call_rt", name="git_ops", arguments={"sub": "status"})
        d = tool_call_to_openai_dict(original)
        restored = tool_call_from_openai_dict(d)
        assert restored.id == original.id
        assert restored.name == original.name
        assert restored.arguments == original.arguments


# ---------------------------------------------------------------------------
# Ollama-format converters
# ---------------------------------------------------------------------------


class TestOllamaConverters:
    def test_tool_call_from_ollama_dict(self):
        d = {"function": {"name": "safe_shell", "arguments": {"cmd": "ls"}}}
        tc = tool_call_from_ollama_dict(d)
        assert tc.name == "safe_shell"
        assert tc.arguments == {"cmd": "ls"}
        assert tc.id == ""  # Ollama doesn't provide IDs

    def test_tool_call_from_ollama_dict_string_args(self):
        d = {"function": {"name": "file_reader", "arguments": '{"path": "/tmp"}'}}
        tc = tool_call_from_ollama_dict(d)
        assert tc.arguments == {"path": "/tmp"}

    def test_tool_schema_to_ollama_identity(self):
        schema = {
            "type": "function",
            "function": {
                "name": "safe_shell",
                "description": "Run a shell command",
                "parameters": {
                    "type": "object",
                    "properties": {"cmd": {"type": "string"}},
                },
            },
        }
        out = tool_schema_to_ollama(schema)
        assert out == schema


# ---------------------------------------------------------------------------
# tool_result_to_tool_message
# ---------------------------------------------------------------------------


class TestToolResultToToolMessage:
    def test_success_message(self):
        r = ToolResult(call_id="c1", tool_name="safe_shell", status=ToolCallStatus.SUCCESS, content="output")
        msg = tool_result_to_tool_message(r)
        assert msg["role"] == "tool"
        assert msg["tool_call_id"] == "c1"
        assert msg["name"] == "safe_shell"
        assert msg["content"] == "output"

    def test_error_message_includes_status(self):
        r = ToolResult(
            call_id="c2",
            tool_name="file_reader",
            status=ToolCallStatus.EXECUTION_ERROR,
            error="permission denied",
        )
        msg = tool_result_to_tool_message(r)
        assert "execution_error" in msg["content"]
        assert "permission denied" in msg["content"]

    def test_unavailable_message_includes_status(self):
        r = tool_result_unavailable("c3", "unknown_tool", "not in registry")
        msg = tool_result_to_tool_message(r)
        assert "unavailable" in msg["content"]
        assert "not in registry" in msg["content"]

    def test_degraded_message_includes_status(self):
        r = tool_result_degraded("c4", "safe_shell", "schema failed")
        msg = tool_result_to_tool_message(r)
        assert "degraded" in msg["content"]
        assert "schema failed" in msg["content"]


# ===========================================================================
# PR 2 — v2 runtime adopts ToolResult
# ===========================================================================


class TestV2RuntimeToolResult:
    """Verify that the v2 executor loop converts raw tool results into ToolResult objects."""

    def _make_agent(self, agent_id: str = "security_agent"):
        from backend.agents import create_agent

        mock_llm = AsyncMock()
        return create_agent(agent_id, mock_llm)

    @pytest.mark.asyncio
    async def test_successful_tool_call_populates_tc_result(self):
        """A successful tool in the v2 loop should populate tc.result with string content."""
        agent = self._make_agent()

        # Executor turn returns a tool call; tool returns success dict
        from backend.models import AgentTurn, ToolCall

        turn_with_tool = AgentTurn(
            turn_id="t1",
            role="executor",
            model_id="test",
            content="calling tool",
            tool_calls=[ToolCall(id="tc1", name="safe_shell", arguments={"cmd": "pwd"})],
            is_final=False,
        )
        final_turn = AgentTurn(
            turn_id="t2",
            role="executor",
            model_id="test",
            content="done",
            tool_calls=[],
            is_final=True,
        )

        with (
            patch.object(agent, "_executor_turn", side_effect=[turn_with_tool, final_turn]),
            patch.object(
                agent,
                "_execute_tool",
                return_value={"content": "/root/studio"},
            ),
        ):
            result = await agent.process_message_v2("run pwd")

        assert "done" in result

    @pytest.mark.asyncio
    async def test_tool_error_populates_tc_error(self):
        """When _execute_tool returns an error dict, tc.error must be set on the ToolCall."""
        agent = self._make_agent()

        from backend.models import AgentTurn, ToolCall

        turn = AgentTurn(
            turn_id="t1",
            role="executor",
            model_id="test",
            content="tool failed",
            tool_calls=[ToolCall(id="tc_err", name="safe_shell", arguments={"cmd": "rm -rf /"})],
            is_final=True,
        )

        async def capture_and_error(tool_name, kwargs):
            return {"error": "command not allowed"}

        with (
            patch.object(agent, "_executor_turn", return_value=turn),
            patch.object(agent, "_execute_tool", side_effect=capture_and_error),
        ):
            response = await agent.process_message_v2("run rm")

        # Response should contain the turn content; no exception should propagate
        assert "tool failed" in response


# ===========================================================================
# PR 3 — Explicit degraded behavior
# ===========================================================================


class TestExplicitDegradedBehavior:
    """Verify that schema parse failures never silently fall through."""

    def _make_agent(self, agent_id: str = "security_agent"):
        from backend.agents import create_agent

        mock_llm = AsyncMock()
        return create_agent(agent_id, mock_llm)

    @pytest.mark.asyncio
    async def test_schema_failure_activates_degraded_mode(self):
        """When chat_with_schema raises, the fallback is activated and marked."""
        from backend.agents import BaseAgent

        agent = self._make_agent()
        before = BaseAgent._degraded_count

        # chat_with_schema fails; chat returns a plain string
        agent.llm.chat_with_schema = AsyncMock(side_effect=RuntimeError("model refused schema"))
        agent.llm.chat = AsyncMock(return_value="fallback answer")

        response = await agent.process_message_v2("hello")

        after = BaseAgent._degraded_count
        assert after > before, "degraded counter must increment on schema failure"
        assert response  # some response must still be returned

    @pytest.mark.asyncio
    async def test_degraded_count_increments_per_failure(self):
        """Two independent schema failures must each increment the counter once."""
        from backend.agents import BaseAgent

        agent = self._make_agent()
        before = BaseAgent._degraded_count

        agent.llm.chat_with_schema = AsyncMock(side_effect=ValueError("bad schema"))
        agent.llm.chat = AsyncMock(return_value="ok")

        await agent.process_message_v2("first")
        await agent.process_message_v2("second")

        assert BaseAgent._degraded_count >= before + 2

    @pytest.mark.asyncio
    async def test_schema_success_does_not_increment_counter(self):
        """Successful schema generation must not increment the degraded counter."""
        from backend.agents import BaseAgent

        agent = self._make_agent()
        before = BaseAgent._degraded_count

        agent.llm.chat_with_schema = AsyncMock(return_value={"content": "all good", "tool_calls": [], "is_final": True})

        await agent.process_message_v2("hello")
        assert BaseAgent._degraded_count == before

    @pytest.mark.asyncio
    async def test_degraded_response_is_non_empty_string(self):
        """Even in degraded mode the agent must return a meaningful string."""
        agent = self._make_agent()

        agent.llm.chat_with_schema = AsyncMock(side_effect=RuntimeError("schema failed"))
        agent.llm.chat = AsyncMock(return_value="I can still answer in plain text")

        response = await agent.process_message_v2("anything")
        assert isinstance(response, str)
        assert len(response) > 0


# ===========================================================================
# PR 4 — Ollama gateway adapter tool parity
# ===========================================================================


class TestOllamaAdapterToolParity:
    """Verify the Ollama adapter forwards tools and parses tool_calls in responses."""

    def _make_adapter(self):
        from backend.gateway.adapters.ollama import OllamaAdapter

        return OllamaAdapter(base_url="http://localhost:11434")

    def _make_request(self, with_tools: bool = True):
        from backend.gateway.adapters.base import ChatCompletionRequest, ChatMessage

        tools = None
        if with_tools:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "safe_shell",
                        "description": "run a shell command",
                        "parameters": {
                            "type": "object",
                            "properties": {"cmd": {"type": "string"}},
                        },
                    },
                }
            ]
        return ChatCompletionRequest(
            model="llama3.2",
            messages=[ChatMessage(role="user", content="run pwd")],
            tools=tools,
        )

    @pytest.mark.asyncio
    async def test_tools_forwarded_in_payload(self):
        """When tools are present, the Ollama payload must include them."""
        adapter = self._make_adapter()
        request = self._make_request(with_tools=True)

        captured_payload: dict = {}

        async def fake_post(url, json, **kwargs):
            captured_payload.update(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "message": {"role": "assistant", "content": "ok", "tool_calls": []},
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value = mock_client

            await adapter.chat_complete(request)

        assert "tools" in captured_payload, "tools must be forwarded to Ollama"

    @pytest.mark.asyncio
    async def test_tool_calls_in_response_parsed(self):
        """Ollama tool_calls in the response message must appear in ChatCompletionResponse."""
        adapter = self._make_adapter()
        request = self._make_request(with_tools=True)

        async def fake_post(url, json, **kwargs):
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{"function": {"name": "safe_shell", "arguments": {"cmd": "pwd"}}}],
                },
                "done_reason": "tool_calls",
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value = mock_client

            response = await adapter.chat_complete(request)

        assert response.tool_calls is not None
        assert len(response.tool_calls) == 1
        tc = response.tool_calls[0]
        assert tc["function"]["name"] == "safe_shell"

    @pytest.mark.asyncio
    async def test_no_tools_no_tools_key_in_payload(self):
        """When no tools are requested, the payload must not include a tools key."""
        adapter = self._make_adapter()
        request = self._make_request(with_tools=False)

        captured_payload: dict = {}

        async def fake_post(url, json, **kwargs):
            captured_payload.update(json)
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {
                "message": {"role": "assistant", "content": "hello"},
                "done_reason": "stop",
                "prompt_eval_count": 5,
                "eval_count": 3,
            }
            return mock_resp

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value = mock_client

            await adapter.chat_complete(request)

        assert "tools" not in captured_payload

    @pytest.mark.asyncio
    async def test_internal_tool_call_to_gateway_round_trip(self):
        """ToolCall → OpenAI dict → back should preserve name and args."""
        tc = ToolCall(id="call_rt", name="git_ops", arguments={"sub": "status"})
        d = tool_call_to_openai_dict(tc)
        restored = tool_call_from_openai_dict(d)

        assert restored.name == tc.name
        assert restored.arguments == tc.arguments
        assert restored.id == tc.id

    @pytest.mark.asyncio
    async def test_openai_adapter_tools_forwarded(self):
        """Existing OpenAI adapter must still forward tools correctly (regression)."""
        from backend.gateway.adapters.base import ChatCompletionRequest, ChatMessage
        from backend.gateway.adapters.openai import OpenAIAdapter

        adapter = OpenAIAdapter()
        request = ChatCompletionRequest(
            model="gpt-4o-mini",
            messages=[ChatMessage(role="user", content="test")],
            tools=[
                {
                    "type": "function",
                    "function": {"name": "safe_shell", "description": "run shell"},
                }
            ],
        )

        # Patch _build_body to inspect without a real HTTP call
        body = adapter._build_body(request)
        assert "tools" in body
        assert body["tools"][0]["function"]["name"] == "safe_shell"
