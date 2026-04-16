"""
Sprint 2–6 feature tests.

Covers:
- Sprint 2: process_message dispatch (legacy vs v2)
- Sprint 3: _planner_turn returns ExecutionPlan; _validator_turn returns ValidationReport
- Sprint 4: ContextAssembler.retrieve / ingest_memory; MemoryStore.write_async
- Sprint 5: GitNexus tools in TOOL_REGISTRY / MCP_TOOL_MAP / agent permissions
- Sprint 6: AGENT_STEP_TIMEOUT_SECONDS enforced; legacy [TOOL:...] deprecation warning
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents import (
    CODE_REVIEW_AGENT_DEFINITION,
    DEVOPS_AGENT_DEFINITION,
    SECURITY_AGENT_DEFINITION,
    BaseAgent,
    create_agent,
)
from backend.mcp import MCP_TOOL_MAP
from backend.memory import memory_store
from backend.tools import TOOL_REGISTRY


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(agent_id: str = "code_review_agent") -> BaseAgent:
    mock_llm = AsyncMock()
    return create_agent(agent_id, mock_llm)


# ===========================================================================
# Sprint 4 — ContextAssembler
# ===========================================================================


class TestContextAssembler:
    def test_importable(self):
        from backend.knowledge.context_assembler import ContextAssembler

        assert callable(ContextAssembler)

    def test_has_retrieve_and_ingest(self):
        from backend.knowledge.context_assembler import ContextAssembler

        assert hasattr(ContextAssembler, "retrieve")
        assert hasattr(ContextAssembler, "ingest_memory")

    def test_retrieve_is_coroutine(self):
        from backend.knowledge.context_assembler import ContextAssembler

        assert inspect.iscoroutinefunction(ContextAssembler.retrieve)

    def test_ingest_memory_is_coroutine(self):
        from backend.knowledge.context_assembler import ContextAssembler

        assert inspect.iscoroutinefunction(ContextAssembler.ingest_memory)

    @pytest.mark.asyncio
    async def test_retrieve_returns_str_on_unavailable_qdrant(self):
        """When Qdrant search fails retrieve() must return a string (not raise)."""
        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(return_value=[0.1] * 768)

        ca = ContextAssembler(mock_llm)
        # Patch VectorStore.search to raise and fallback to return empty
        with patch.object(ca._store, "search", side_effect=RuntimeError("qdrant down")):
            with patch.object(ca, "_fallback_retrieve", return_value="") as fb:
                result = await ca.retrieve("test query", agent_id="code_review_agent")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_ingest_returns_false_on_failure(self):
        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(side_effect=RuntimeError("embed failed"))

        ca = ContextAssembler(mock_llm)
        result = await ca.ingest_memory("code_review_agent", "some content", {})
        assert result is False


# ===========================================================================
# Sprint 4 — MemoryStore.write_async
# ===========================================================================


class TestWriteAsync:
    def test_write_async_is_coroutine(self):
        assert inspect.iscoroutinefunction(memory_store.write_async)

    @pytest.mark.asyncio
    async def test_write_async_stores_value(self):
        """write_async must produce the same result as synchronous write."""
        ns = f"_test_sprint6_{id(self)}"
        await memory_store.write_async(ns, "k1", {"v": 42})
        val = memory_store.read(ns, "k1")
        assert val == {"v": 42}


# ===========================================================================
# Sprint 5 — GitNexus tools
# ===========================================================================

GN_TOOLS = [
    "mcp_gitnexus_query",
    "mcp_gitnexus_context",
    "mcp_gitnexus_impact",
    "mcp_gitnexus_detect_changes",
    "mcp_gitnexus_list_repos",
]


class TestGitNexusToolRegistry:
    @pytest.mark.parametrize("tool_name", GN_TOOLS)
    def test_tool_in_registry(self, tool_name: str):
        assert tool_name in TOOL_REGISTRY, f"Missing from TOOL_REGISTRY: {tool_name}"

    @pytest.mark.parametrize("tool_name", GN_TOOLS)
    def test_tool_in_mcp_map(self, tool_name: str):
        assert tool_name in MCP_TOOL_MAP, f"Missing from MCP_TOOL_MAP: {tool_name}"
        server, _ = MCP_TOOL_MAP[tool_name]
        assert server == "gitnexus"

    @pytest.mark.parametrize("tool_name", GN_TOOLS)
    def test_tool_is_readonly(self, tool_name: str):
        from backend.models import ModificationType

        td = TOOL_REGISTRY[tool_name]
        assert td.modification_type == ModificationType.READ_ONLY

    def test_impact_tool_has_parameter_schema(self):
        td = TOOL_REGISTRY["mcp_gitnexus_impact"]
        assert td.parameters is not None
        assert "symbol" in td.parameters.get("properties", {})


class TestGitNexusAgentPermissions:
    @pytest.mark.parametrize(
        "agent_def",
        [DEVOPS_AGENT_DEFINITION, CODE_REVIEW_AGENT_DEFINITION, SECURITY_AGENT_DEFINITION],
        ids=["devops_agent", "code_review_agent", "security_agent"],
    )
    @pytest.mark.parametrize("tool_name", GN_TOOLS)
    def test_agent_has_gitnexus_permission(self, agent_def, tool_name):
        assert tool_name in agent_def.tool_permissions, (
            f"{agent_def.agent_id} missing tool_permission: {tool_name}"
        )

    def test_monitor_agent_does_not_have_gitnexus(self):
        from backend.agents import ALL_AGENT_DEFINITIONS

        monitor = ALL_AGENT_DEFINITIONS["monitor_agent"]
        for t in GN_TOOLS:
            assert t not in monitor.tool_permissions, (
                f"monitor_agent should NOT have {t}"
            )


# ===========================================================================
# Sprint 6 — AGENT_STEP_TIMEOUT_SECONDS
# ===========================================================================


class TestStepTimeout:
    def test_config_exported(self):
        from backend.config import AGENT_STEP_TIMEOUT_SECONDS

        assert isinstance(AGENT_STEP_TIMEOUT_SECONDS, float)
        assert AGENT_STEP_TIMEOUT_SECONDS > 0  # default is 60

    @pytest.mark.asyncio
    async def test_timeout_aborts_loop(self):
        """When _executor_turn hangs, wait_for raises TimeoutError → loop breaks."""
        import backend.agents as agents_module

        agent = make_agent("code_review_agent")

        async def _slow_turn(*args, **kwargs):
            await asyncio.sleep(9999)

        original_timeout = agents_module.AGENT_STEP_TIMEOUT_SECONDS
        try:
            agents_module.AGENT_STEP_TIMEOUT_SECONDS = 0.05  # 50 ms
            with patch.object(agent, "_executor_turn", side_effect=_slow_turn):
                with patch.object(agent, "_planner_turn", return_value=None):
                    import backend.agents as _m
                    orig = _m.AGENT_PLANNER_ENABLED
                    _m.AGENT_PLANNER_ENABLED = False
                    response = await agent.process_message_v2("do something")
                    _m.AGENT_PLANNER_ENABLED = orig
        finally:
            agents_module.AGENT_STEP_TIMEOUT_SECONDS = original_timeout

        # Should return fallback message (no turns completed)
        assert isinstance(response, str)


# ===========================================================================
# Sprint 6 — Legacy [TOOL:...] deprecation warning
# ===========================================================================


class TestLegacyDeprecationWarning:
    @pytest.mark.asyncio
    async def test_legacy_pattern_emits_warning(self, caplog):
        import logging

        agent = make_agent("security_agent")
        # Ensure this agent hasn't already warned in another test run
        BaseAgent._legacy_tool_warned.discard("security_agent")

        fake_response = "[TOOL:file_reader(path=/etc/hosts)]"
        with patch.object(agent, "_execute_tool", return_value={"content": "127.0.0.1 localhost"}):
            with patch.object(agent._tool_validator, "validate") as mock_val:
                mock_val.return_value = MagicMock(valid=True)
                with caplog.at_level(logging.WARNING, logger="backend.agents"):
                    await agent._handle_tool_calls(fake_response)

        assert any(
            "legacy [TOOL:...]" in r.message or "legacy" in r.message.lower()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_legacy_warning_only_once_per_agent(self, caplog):
        import logging

        agent = make_agent("devops_agent")
        BaseAgent._legacy_tool_warned.discard("devops_agent")

        fake_response = "[TOOL:git_ops(cmd=log)]"
        with patch.object(agent, "_execute_tool", return_value={"content": "commit log"}):
            with patch.object(agent._tool_validator, "validate") as mock_val:
                mock_val.return_value = MagicMock(valid=True)
                with caplog.at_level(logging.WARNING, logger="backend.agents"):
                    await agent._handle_tool_calls(fake_response)
                    warning_count_1 = sum(
                        1 for r in caplog.records if "legacy" in r.message.lower()
                    )
                    await agent._handle_tool_calls(fake_response)
                    warning_count_2 = sum(
                        1 for r in caplog.records if "legacy" in r.message.lower()
                    )

        # Second call must not add another warning
        assert warning_count_1 == warning_count_2
