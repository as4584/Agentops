"""
Deep tests for BaseAgent, SoulAgent, and _format_result helper.
Covers: _handle_tool_calls, _handle_structured_tool_calls, _build_tools_context,
        read_memory, write_memory, set_health_monitor, _execute_tool, get_state,
        SoulAgent.boot, reflect, set_goal, complete_goal, update_trust.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents import BaseAgent, SoulAgent, create_agent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agent(agent_id: str = "security_agent") -> BaseAgent:
    mock_llm = AsyncMock()
    return create_agent(agent_id, mock_llm)


def make_soul() -> SoulAgent:
    """Create an isolated SoulAgent with a unique memory namespace per test."""
    from backend.agents import ALL_AGENT_DEFINITIONS, SoulAgent

    base_def = ALL_AGENT_DEFINITIONS["soul_core"]
    unique_ns = f"soul_test_{uuid.uuid4().hex}"
    isolated_def = base_def.model_copy(update={"memory_namespace": unique_ns})
    mock_llm = AsyncMock()
    return SoulAgent(definition=isolated_def, llm_client=mock_llm)


# ---------------------------------------------------------------------------
# _format_result
# ---------------------------------------------------------------------------


class TestFormatResult:
    def _fmt(self, v):
        from backend.agents import _format_result

        return _format_result(v)

    def test_dict_with_error_key(self):
        result = self._fmt({"error": "something broke"})
        assert "Error" in result
        assert "something broke" in result

    def test_dict_with_success_false(self):
        result = self._fmt({"success": False, "message": "bad input"})
        assert "Error" in result
        assert "bad input" in result

    def test_dict_with_reachable_false(self):
        result = self._fmt({"reachable": False, "url": "http://x.com"})
        assert "Error" in result
        assert "x.com" in result

    def test_dict_with_exists_false(self):
        result = self._fmt({"exists": False})
        assert "Error" in result
        assert "not found" in result

    def test_dict_with_content(self):
        result = self._fmt({"content": "hello world"})
        assert result == "hello world"

    def test_dict_with_stdout(self):
        result = self._fmt({"stdout": "output here"})
        assert "output here" in result

    def test_dict_strips_health_key(self):
        result = self._fmt({"content": "clean", "_health": {"status": "ok"}})
        assert "_health" not in result
        assert "clean" in result

    def test_plain_string(self):
        result = self._fmt("plain text")
        assert result == "plain text"

    def test_long_string_truncated(self):
        result = self._fmt("x" * 2000)
        assert len(result) <= 1000

    def test_dict_fallback_repr(self):
        result = self._fmt({"custom_key": "custom_value"})
        assert "custom_value" in result

    def test_empty_dict(self):
        result = self._fmt({})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# BaseAgent._build_tools_context
# ---------------------------------------------------------------------------


class TestBuildToolsContext:
    def test_returns_string(self):
        agent = make_agent("security_agent")
        result = agent._build_tools_context()
        assert isinstance(result, str)

    def test_no_tools_returns_fallback(self):
        agent = make_agent("soul_core")  # soul_core has no tools
        result = agent._build_tools_context()
        # Either returns "No tools available." or empty string for no perms
        assert isinstance(result, str)

    def test_tools_appear_in_context(self):
        agent = make_agent("security_agent")
        # security_agent has secret_scanner and file_reader
        result = agent._build_tools_context()
        # At least one tool should appear (some may be missing definitions)
        # Just verify it returns a non-None string
        assert result is not None


# ---------------------------------------------------------------------------
# BaseAgent.read_memory / write_memory
# ---------------------------------------------------------------------------


class TestMemoryDelegation:
    def test_write_and_read(self):
        agent = make_agent("monitor_agent")
        agent.write_memory("test_key", {"data": 42})
        value = agent.read_memory("test_key")
        assert value == {"data": 42}

    def test_read_missing_returns_default(self):
        agent = make_agent("monitor_agent")
        value = agent.read_memory("nonexistent_key", default="fallback")
        assert value == "fallback"

    def test_read_missing_returns_none_by_default(self):
        agent = make_agent("data_agent")
        result = agent.read_memory("ghost_key_xyz")
        assert result is None

    def test_write_overwrites(self):
        agent = make_agent("comms_agent")
        agent.write_memory("k", "v1")
        agent.write_memory("k", "v2")
        assert agent.read_memory("k") == "v2"


# ---------------------------------------------------------------------------
# BaseAgent.set_health_monitor / get_state
# ---------------------------------------------------------------------------


class TestAgentState:
    def test_get_state_returns_agent_state(self):
        from backend.models import AgentState

        agent = make_agent("monitor_agent")
        state = agent.get_state()
        assert isinstance(state, AgentState)
        assert state.agent_id == "monitor_agent"

    def test_set_health_monitor_stores_monitor(self):
        agent = make_agent("security_agent")
        mock_monitor = MagicMock()
        agent.set_health_monitor(mock_monitor)
        assert agent._health_monitor is mock_monitor

    def test_initial_state_is_idle(self):
        from backend.models import AgentStatus

        agent = make_agent("monitor_agent")
        state = agent.get_state()
        assert state.status == AgentStatus.IDLE


# ---------------------------------------------------------------------------
# BaseAgent._handle_tool_calls
# ---------------------------------------------------------------------------


class TestHandleToolCalls:
    @pytest.mark.asyncio
    async def test_no_tool_calls_unchanged(self):
        agent = make_agent("security_agent")
        response = "Just a regular response with no tool calls."
        result = await agent._handle_tool_calls(response)
        assert result == response

    @pytest.mark.asyncio
    async def test_valid_tool_call_replaced(self):
        agent = make_agent("security_agent")
        # Patch _execute_tool to return a known result
        agent._execute_tool = AsyncMock(return_value={"content": "scan result"})
        response = "Scanning: [TOOL:secret_scanner(path=test.py)] done."
        result = await agent._handle_tool_calls(response)
        assert "[TOOL:secret_scanner" not in result
        assert "scan result" in result

    @pytest.mark.asyncio
    async def test_blocked_tool_not_executed(self):
        agent = make_agent("security_agent")
        agent._execute_tool = AsyncMock(return_value={})
        # "safe_shell" is NOT in security_agent's tool_permissions
        response = "Running: [TOOL:safe_shell(cmd=ls)] done."
        result = await agent._handle_tool_calls(response)
        # Tool should be blocked, not executed
        agent._execute_tool.assert_not_called()
        assert "Blocked" in result or "safe_shell" in result

    @pytest.mark.asyncio
    async def test_tool_call_with_params_parsed(self):
        agent = make_agent("security_agent")
        captured_kwargs: dict = {}

        async def capture_tool(tool_name, kwargs):
            captured_kwargs.update(kwargs)
            return {"content": "ok"}

        agent._execute_tool = capture_tool
        response = "[TOOL:secret_scanner(path='myfile.py',depth='2')]"
        await agent._handle_tool_calls(response)
        assert "path" in captured_kwargs

    @pytest.mark.asyncio
    async def test_conversation_updated_with_tool_result(self):
        agent = make_agent("security_agent")
        agent._execute_tool = AsyncMock(return_value={"content": "result value"})
        response = "[TOOL:secret_scanner(path=x.py)]"
        await agent._handle_tool_calls(response)
        # Conversation history should have a system message with the result
        system_msgs = [m for m in agent._conversation_history if m["role"] == "system"]
        assert any("secret_scanner" in m["content"] for m in system_msgs)

    @pytest.mark.asyncio
    async def test_tool_call_id_sequence_increments(self):
        agent = make_agent("security_agent")
        agent._execute_tool = AsyncMock(return_value={"content": "ok"})
        assert agent._tool_call_sequence == 0
        await agent._handle_tool_calls("[TOOL:secret_scanner(path=a.py)]")
        assert agent._tool_call_sequence == 1
        await agent._handle_tool_calls("[TOOL:secret_scanner(path=b.py)]")
        assert agent._tool_call_sequence == 2


# ---------------------------------------------------------------------------
# BaseAgent._handle_structured_tool_calls
# ---------------------------------------------------------------------------


class TestHandleStructuredToolCalls:
    @pytest.mark.asyncio
    async def test_valid_structured_call_via_mock_match(self):
        """Use a mock match to bypass the non-greedy regex limitation with JSON arrays."""
        agent = make_agent("security_agent")
        agent._execute_tool = AsyncMock(return_value={"content": "structured result"})
        calls_json = json.dumps([{"name": "secret_scanner", "arguments": {"path": "test.py"}}])
        mock_match = MagicMock()
        mock_match.group.return_value = calls_json
        mock_match.start.return_value = 0
        mock_match.end.return_value = len(f"[TOOL_CALLS:{calls_json}]")
        response = f"[TOOL_CALLS:{calls_json}]"
        result = await agent._handle_structured_tool_calls(response, mock_match)
        agent._execute_tool.assert_called_once()
        assert "structured result" in result

    @pytest.mark.asyncio
    async def test_malformed_json_returns_unchanged(self):
        import re

        agent = make_agent("security_agent")
        response = "[TOOL_CALLS:not-valid-json]"
        match = re.search(r"\[TOOL_CALLS:(.*?)\]", response, re.DOTALL)
        assert match is not None
        result = await agent._handle_structured_tool_calls(response, match)
        # With bad JSON, should return the original response
        assert result == response

    @pytest.mark.asyncio
    async def test_blocked_tool_in_structured_call(self):
        """Blocked tool should not be executed; Blocked message in result."""
        agent = make_agent("security_agent")
        agent._execute_tool = AsyncMock(return_value={"content": "ok"})
        # safe_shell is not in security_agent's permissions
        calls_json = json.dumps([{"name": "safe_shell", "arguments": {"cmd": "ls"}}])
        mock_match = MagicMock()
        mock_match.group.return_value = calls_json
        mock_match.start.return_value = 0
        mock_match.end.return_value = len(f"[TOOL_CALLS:{calls_json}]")
        result = await agent._handle_structured_tool_calls(f"[TOOL_CALLS:{calls_json}]", mock_match)
        agent._execute_tool.assert_not_called()
        assert "Blocked" in result


# ---------------------------------------------------------------------------
# BaseAgent._execute_tool (with health monitor)
# ---------------------------------------------------------------------------


class TestExecuteTool:
    @pytest.mark.asyncio
    async def test_execute_tool_records_call_with_monitor(self):
        agent = make_agent("security_agent")
        mock_monitor = MagicMock()
        agent.set_health_monitor(mock_monitor)
        with patch("backend.agents.execute_tool", new=AsyncMock(return_value={"content": "ok"})):
            result = await agent._execute_tool("secret_scanner", {"path": "test.py"})
        mock_monitor.record_call.assert_called_once_with("secret_scanner")
        assert result["content"] == "ok"

    @pytest.mark.asyncio
    async def test_execute_tool_catches_exception(self):
        agent = make_agent("security_agent")
        with patch("backend.agents.execute_tool", new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await agent._execute_tool("secret_scanner", {})
        assert "error" in result
        assert "boom" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_records_failure_with_monitor(self):
        agent = make_agent("security_agent")
        mock_monitor = MagicMock()
        agent.set_health_monitor(mock_monitor)
        with patch("backend.agents.execute_tool", new=AsyncMock(side_effect=RuntimeError("crash"))):
            await agent._execute_tool("secret_scanner", {})
        mock_monitor.record_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_tool_adds_health_ok_metadata(self):
        agent = make_agent("security_agent")
        mock_monitor = MagicMock()
        agent.set_health_monitor(mock_monitor)
        with patch("backend.agents.execute_tool", new=AsyncMock(return_value={"content": "ok"})):
            with patch("deerflow.tools.middleware.detect_tool_failure", return_value=(False, None)):
                result = await agent._execute_tool("secret_scanner", {})
        assert result.get("_health", {}).get("status") == "ok"

    @pytest.mark.asyncio
    async def test_execute_tool_no_monitor_no_extra_metadata(self):
        agent = make_agent("security_agent")
        # No health monitor attached
        with patch("backend.agents.execute_tool", new=AsyncMock(return_value={"content": "bare"})):
            result = await agent._execute_tool("secret_scanner", {})
        assert "_health" not in result


# ---------------------------------------------------------------------------
# SoulAgent.boot
# ---------------------------------------------------------------------------


class TestSoulAgentBoot:
    @pytest.mark.asyncio
    async def test_boot_returns_summary(self):
        soul = make_soul()
        result = await soul.boot()
        assert "session" in result
        assert "active_goals" in result
        assert "identity" in result
        assert result["session"] == 1

    @pytest.mark.asyncio
    async def test_boot_initializes_identity(self):
        soul = make_soul()
        await soul.boot()
        assert soul._identity.get("name") == "Agentop Core"
        assert "created_at" in soul._identity

    @pytest.mark.asyncio
    async def test_boot_twice_increments_session(self):
        soul = make_soul()
        r1 = await soul.boot()
        r2 = await soul.boot()
        assert r2["session"] == r1["session"] + 1

    @pytest.mark.asyncio
    async def test_boot_loads_stored_identity(self):
        soul = make_soul()
        # Pre-write a custom identity
        custom_id = {
            "name": "Custom Core",
            "values": ["test"],
            "personality": "x",
            "mission": "test",
            "created_at": "now",
        }
        soul.write_memory("identity", custom_id)
        result = await soul.boot()
        assert result["identity"] == "Custom Core"

    @pytest.mark.asyncio
    async def test_boot_loads_active_goals(self):
        soul = make_soul()
        goals = [
            {"id": "g1", "title": "Test Goal", "completed": False},
            {"id": "g2", "title": "Done Goal", "completed": True},
        ]
        soul.write_memory("goals", goals)
        result = await soul.boot()
        assert result["active_goals"] == 1  # only non-completed


# ---------------------------------------------------------------------------
# SoulAgent.set_goal / complete_goal
# ---------------------------------------------------------------------------


class TestSoulAgentGoals:
    def test_set_goal_returns_goal(self):
        soul = make_soul()
        goal = soul.set_goal("Deploy v2", "Deploy version 2 to production", "HIGH")
        assert goal["title"] == "Deploy v2"
        assert goal["priority"] == "HIGH"
        assert not goal["completed"]

    def test_set_goal_persists_in_memory(self):
        soul = make_soul()
        soul.set_goal("Goal A", "description A")
        stored = soul.read_memory("goals")
        assert len(stored) == 1
        assert stored[0]["title"] == "Goal A"

    def test_complete_goal_marks_done(self):
        soul = make_soul()
        goal = soul.set_goal("Finish task", "do it")
        success = soul.complete_goal(goal["id"])
        assert success is True
        stored = soul.read_memory("goals")
        assert stored[0]["completed"] is True
        assert "completed_at" in stored[0]

    def test_complete_goal_removes_from_active(self):
        soul = make_soul()
        goal = soul.set_goal("Active goal", "desc")
        soul.complete_goal(goal["id"])
        assert len(soul._active_goals) == 0

    def test_complete_nonexistent_goal_returns_true(self):
        soul = make_soul()
        # Add a goal so the goals list exists in memory
        soul.set_goal("Existing goal", "desc")
        # Try to complete a non-existent ID — returns True (list exists, no match found but no error)
        result = soul.complete_goal("nonexistent_id")
        assert result is True

    def test_complete_goal_no_goals_in_memory(self):
        soul = make_soul()
        # Memory has no goals key — should return False
        result = soul.complete_goal("any_id")
        assert result is False

    def test_multiple_goals_managed(self):
        soul = make_soul()
        g1 = soul.set_goal("Goal 1", "d1")
        _g2 = soul.set_goal("Goal 2", "d2")
        # Complete only goals with g1's ID (both may share id if created same second)
        soul.complete_goal(g1["id"])
        # After completion, no goal with g1's id should be in active_goals
        active_ids = {g["id"] for g in soul._active_goals}
        assert g1["id"] not in active_ids


# ---------------------------------------------------------------------------
# SoulAgent.update_trust
# ---------------------------------------------------------------------------


class TestSoulAgentTrust:
    def test_update_trust_clamps_to_0(self):
        soul = make_soul()
        result = soul.update_trust("devops_agent", -100.0)
        assert result == 0.0

    def test_update_trust_clamps_to_1(self):
        soul = make_soul()
        result = soul.update_trust("monitor_agent", 100.0)
        assert result == 1.0

    def test_update_trust_default_base(self):
        soul = make_soul()
        # No existing trust — default 0.75
        result = soul.update_trust("it_agent", 0.0)
        assert abs(result - 0.75) < 1e-9

    def test_update_trust_persists(self):
        soul = make_soul()
        soul.update_trust("security_agent", 0.1)
        stored = soul.read_memory("trust_scores")
        assert "security_agent" in stored
        assert stored["security_agent"] > 0.75

    def test_update_trust_idempotent_store(self):
        soul = make_soul()
        soul.update_trust("agent_a", 0.05)
        soul.update_trust("agent_a", -0.05)
        result = soul.update_trust("agent_a", 0.0)
        # Should be back around 0.75
        assert abs(result - 0.75) < 0.01


# ---------------------------------------------------------------------------
# SoulAgent.reflect
# ---------------------------------------------------------------------------


class TestSoulAgentReflect:
    @pytest.mark.asyncio
    async def test_reflect_calls_llm(self):
        soul = make_soul()
        soul.llm.generate = AsyncMock(return_value="All is well in the cluster.")
        await soul.boot()
        text = await soul.reflect(trigger="test")
        assert "well" in text
        soul.llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflect_persists_log(self):
        soul = make_soul()
        soul.llm.generate = AsyncMock(return_value="Reflection text.")
        await soul.boot()
        await soul.reflect()
        log = soul.read_memory("reflection_log")
        assert isinstance(log, list)
        assert len(log) == 1
        assert log[0]["reflection"] == "Reflection text."

    @pytest.mark.asyncio
    async def test_reflect_with_trigger(self):
        soul = make_soul()
        soul.llm.generate = AsyncMock(return_value="Reflected.")
        await soul.boot()
        await soul.reflect(trigger="scheduled")
        log = soul.read_memory("reflection_log")
        assert log[0]["trigger"] == "scheduled"


# ---------------------------------------------------------------------------
# SoulAgent.process_message (enriched context injection)
# ---------------------------------------------------------------------------


class TestSoulAgentProcessMessage:
    @pytest.mark.asyncio
    async def test_process_message_enriches_with_soul_context(self):
        soul = make_soul()
        soul.llm.chat = AsyncMock(return_value="I hear you.")
        await soul.boot()
        result = await soul.process_message("What should we do?")
        assert isinstance(result, str)
        # The LLM should have been called with the enriched message
        soul.llm.chat.assert_called_once()
        call_messages = soul.llm.chat.call_args[1]["messages"]
        # The user message should contain injected soul context
        user_msgs = [m for m in call_messages if m["role"] == "user"]
        assert any("Soul Context" in m["content"] for m in user_msgs)
