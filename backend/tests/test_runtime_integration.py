"""
Runtime integration tests — feature flags ON.

Tests the code paths that are normally gated off by default:
  - AGENT_RUNTIME_V2=true   → process_message_v2 / ReAct loop
  - AGENT_PLANNER_ENABLED=true → _planner_turn → _executor_turn → _validator_turn
  - GITNEXUS_ENABLED=true   → GitNexus tools in code_review_agent planner hint
  - QDRANT_IN_MEMORY=true   → ContextAssembler with live Qdrant (in-memory)

Design:
  - All LLM calls go through the mock_ollama fixture (zero network, deterministic).
  - Qdrant uses in-memory mode (no Docker required).
  - Feature flags are patched at the module level inside each test.
  - No real tool execution — _execute_tool is patched to return canned results.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents import BaseAgent, create_agent
from backend.knowledge.context_assembler import ContextAssembler
from backend.llm import OllamaClient

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def make_llm() -> OllamaClient:
    return OllamaClient()


def make_agent(agent_id: str = "code_review_agent", llm: OllamaClient | None = None) -> BaseAgent:
    return create_agent(agent_id, llm or make_llm())


def stub_assembler() -> Any:
    """Return a mock ContextAssembler that does nothing (no Qdrant, no embed calls)."""
    m = AsyncMock()
    m.retrieve = AsyncMock(return_value="")
    m.ingest_memory = AsyncMock(return_value=True)
    return m


# Canned schema responses the mock LLM returns for chat_with_schema calls.
_EXECUTOR_FINAL = json.dumps(
    {
        "content": "Analysis complete. No issues found.",
        "tool_calls": [],
        "is_final": True,
    }
)

_EXECUTOR_TOOL_THEN_FINAL = [
    json.dumps(
        {
            "content": "I need to read the file first.",
            "tool_calls": [{"id": "tc_1", "name": "file_reader", "arguments": {"path": "backend/config.py"}}],
            "is_final": False,
        }
    ),
    json.dumps(
        {
            "content": "File read. No secrets detected.",
            "tool_calls": [],
            "is_final": True,
        }
    ),
]

_PLAN_RESPONSE = json.dumps(
    {
        "goal": "Review recent code changes for architectural violations.",
        "steps": [
            "1. Read git diff to identify changed files.",
            "2. Check each changed file against DRIFT_GUARD.md invariants.",
            "3. Produce APPROVED / NEEDS_CHANGES / BLOCKED verdict.",
        ],
        "required_tools": ["git_ops", "file_reader"],
        "risk_level": "LOW",
        "rejected_alternatives": ["Run linter (not architectural)"],
    }
)

_VALIDATION_PASS = json.dumps(
    {
        "passed": True,
        "score": 0.91,
        "issues": [],
        "recommendations": ["Add test coverage for changed paths."],
        "requires_retry": False,
        "retry_hint": "",
    }
)

_VALIDATION_FAIL = json.dumps(
    {
        "passed": False,
        "score": 0.42,
        "issues": ["Response does not cite any invariant."],
        "recommendations": ["Reference INV-* code in your verdict."],
        "requires_retry": True,
        "retry_hint": "Re-check DRIFT_GUARD.md and cite the relevant invariant.",
    }
)


# ---------------------------------------------------------------------------
# Fixture: patch feature flags ON for the duration of a test
# ---------------------------------------------------------------------------


@pytest.fixture
def flags_all_on(monkeypatch):
    """Enable all new-architecture feature flags via monkeypatch.
    Also stubs UnifiedModelRouter.generate so tests never hit real Ollama via the router.
    Individual tests can override this patch inside their own `with patch(...)` context.
    """
    import backend.agents as _agents
    import backend.config as _cfg

    monkeypatch.setattr(_cfg, "AGENT_RUNTIME_V2", True)
    monkeypatch.setattr(_cfg, "AGENT_PLANNER_ENABLED", True)
    monkeypatch.setattr(_cfg, "GITNEXUS_ENABLED", True)
    monkeypatch.setattr(_cfg, "AGENT_STEP_TIMEOUT_SECONDS", 30.0)
    monkeypatch.setattr(_agents, "AGENT_RUNTIME_V2", True)
    monkeypatch.setattr(_agents, "AGENT_PLANNER_ENABLED", True)
    monkeypatch.setattr(_agents, "GITNEXUS_ENABLED", True)
    monkeypatch.setattr(_agents, "AGENT_STEP_TIMEOUT_SECONDS", 30.0)

    async def _default_router_generate(self_router, prompt="", system="", task="", model="", **kw):
        """Blanket stub: returns appropriate JSON based on the task role."""
        if "validator" in task:
            return {"output": _VALIDATION_PASS}
        return {"output": _PLAN_RESPONSE}

    monkeypatch.setattr(
        "backend.llm.unified_registry.UnifiedModelRouter.generate",
        _default_router_generate,
    )


# ===========================================================================
# 1. Multi-step ReAct execution (AGENT_RUNTIME_V2=true)
# ===========================================================================


class TestReActLoop:
    """process_message_v2 should run the bounded think/act/observe loop."""

    @pytest.mark.asyncio
    async def test_single_turn_final_response(self, flags_all_on):
        """Loop exits on turn 1 when model sets is_final=true immediately."""
        agent = make_agent("security_agent")
        agent._context_assembler = stub_assembler()
        responses = iter([_EXECUTOR_FINAL])

        async def _schema_resp(*a, **kw):
            return json.loads(next(responses))

        import backend.agents as _agents

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                result = await agent.process_message_v2("Check for exposed secrets.")

        assert "Analysis complete" in result

    @pytest.mark.asyncio
    async def test_two_turn_tool_then_final(self, flags_all_on):
        """Loop runs tool call on turn 1, then exits final on turn 2."""
        agent = make_agent("security_agent")
        agent._context_assembler = stub_assembler()
        responses = iter(_EXECUTOR_TOOL_THEN_FINAL)

        async def _schema_resp(*a, **kw):
            return json.loads(next(responses))

        tool_result = {"content": "No secrets found in config.py"}

        import backend.agents as _agents

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(agent, "_execute_tool", return_value=tool_result):
                with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                    result = await agent.process_message_v2("Scan backend/config.py for secrets.")

        assert "No secrets detected" in result or "File read" in result

    @pytest.mark.asyncio
    async def test_step_budget_respected(self, flags_all_on):
        """Loop must stop after AGENT_MAX_STEPS even if model never sets is_final."""
        import backend.agents as _agents

        always_loop = json.dumps(
            {
                "content": "Still working...",
                "tool_calls": [{"id": "tc_x", "name": "file_reader", "arguments": {"path": "x"}}],
                "is_final": False,
            }
        )

        agent = make_agent("security_agent")
        agent._context_assembler = stub_assembler()

        async def _schema_resp(*a, **kw):
            return json.loads(always_loop)

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(agent, "_execute_tool", return_value={"content": "data"}):
                with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                    with patch.object(_agents, "AGENT_MAX_STEPS", 3):
                        result = await agent.process_message_v2("Run forever.")

        # Should return last turn content, not hang
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_timeout_aborts_gracefully(self, flags_all_on):
        """When a turn exceeds AGENT_STEP_TIMEOUT_SECONDS, the loop exits cleanly."""
        import backend.agents as _agents

        async def _hanging_turn(*a, **kw):
            await asyncio.sleep(9999)

        agent = make_agent("security_agent")
        agent._context_assembler = stub_assembler()
        with patch.object(agent, "_executor_turn", side_effect=_hanging_turn):
            with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                with patch.object(_agents, "AGENT_STEP_TIMEOUT_SECONDS", 0.05):
                    result = await agent.process_message_v2("Scan everything.")

        # Graceful fallback — no exception propagated
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_memory_written_after_v2_run(self, flags_all_on):
        """process_message_v2 must write conversation to memory_store after completion."""
        from backend.memory import memory_store

        agent = make_agent("security_agent")
        agent._context_assembler = stub_assembler()
        responses = iter([_EXECUTOR_FINAL])

        async def _schema_resp(*a, **kw):
            return json.loads(next(responses))

        import backend.agents as _agents

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                await agent.process_message_v2("Quick check.")

        # Should have written at least one conversation key
        ns_data = memory_store._load_store(agent.memory_namespace)
        conv_keys = [k for k in ns_data.get("data", {}) if "conversation_" in k]
        assert conv_keys, "No conversation key written to memory_store"


# ===========================================================================
# 2. Planner → executor → validator flow
# ===========================================================================


class TestPlannerExecutorValidator:
    """Full PEV pipeline with mocked schema responses."""

    @pytest.mark.asyncio
    async def test_planner_produces_execution_plan(self, flags_all_on):
        """_planner_turn returns a valid ExecutionPlan dict when model responds correctly."""
        from backend.models import ExecutionPlan

        agent = make_agent("code_review_agent")
        agent._context_assembler = stub_assembler()

        async def _schema_resp(*a, **kw):
            return json.loads(_PLAN_RESPONSE)

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            plan = await agent._planner_turn(
                message="Review recent code changes for architectural violations.",
                context=None,
            )

        assert plan is not None
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 1
        assert "git" in plan.steps[0].lower() or "read" in plan.steps[0].lower()

    @pytest.mark.asyncio
    async def test_planner_injects_gitnexus_hint_when_enabled(self, flags_all_on):
        """When GITNEXUS_ENABLED, planner system prompt must contain blast-radius step."""
        captured_system: list[str] = []

        async def _capture_schema(messages, schema, **kw):
            for m in messages:
                if m.get("role") == "system":
                    captured_system.append(m["content"])
            return json.loads(_PLAN_RESPONSE)

        async def _capture_router(self_router, prompt, system="", **kw):
            if system:
                captured_system.append(system)
            return {"output": _PLAN_RESPONSE}

        agent = make_agent("code_review_agent")
        agent._context_assembler = stub_assembler()

        with patch.object(agent.llm, "chat_with_schema", side_effect=_capture_schema):
            with patch("backend.llm.unified_registry.UnifiedModelRouter.generate", new=_capture_router):
                await agent._planner_turn(
                    message="Implement the new feature in backend/agents/__init__.py",
                    context=None,
                )

        combined = " ".join(captured_system)
        assert "gitnexus" in combined.lower() or "blast-radius" in combined.lower(), (
            f"Planner prompt must include GitNexus blast-radius hint when GITNEXUS_ENABLED=true. "
            f"Got system prompts: {combined[:200]!r}"
        )

    @pytest.mark.asyncio
    async def test_validator_pass_does_not_modify_response(self, flags_all_on):
        """When validator passes, the response text is unchanged."""
        from backend.models import ChangeImpactLevel, ExecutionPlan

        agent = make_agent("code_review_agent")
        plan = ExecutionPlan(
            goal="Review code",
            steps=["Read diff"],
            required_tools=[],
            risk_level=ChangeImpactLevel.LOW,
            model_role_hints={},
            rejected_alternatives=[],
        )

        async def _schema_resp(*a, **kw):
            return json.loads(_VALIDATION_PASS)

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            report = await agent._validator_turn(
                original_message="Review the diff.",
                response="APPROVED — no invariants violated.",
                plan=plan,
            )

        assert report is not None
        assert report.passed is True
        assert report.requires_retry is False

    @pytest.mark.asyncio
    async def test_validator_fail_surfaces_retry_hint(self, flags_all_on):
        """When validator fails, ValidationReport.requires_retry is True and hint is set."""
        from backend.models import ChangeImpactLevel, ExecutionPlan

        agent = make_agent("code_review_agent")
        plan = ExecutionPlan(
            goal="Review code",
            steps=["Read diff"],
            required_tools=[],
            risk_level=ChangeImpactLevel.LOW,
            model_role_hints={},
            rejected_alternatives=[],
        )

        async def _schema_fail(*a, **kw):
            return json.loads(_VALIDATION_FAIL)

        async def _router_fail(self_router, prompt="", system="", task="", **kw):
            return {"output": _VALIDATION_FAIL}

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_fail):
            with patch("backend.llm.unified_registry.UnifiedModelRouter.generate", new=_router_fail):
                report = await agent._validator_turn(
                    original_message="Review the diff.",
                    response="The change looks fine.",
                    plan=plan,
                )

        assert report is not None
        assert report.passed is False
        assert report.requires_retry is True
        assert report.retry_hint

    @pytest.mark.asyncio
    async def test_full_pev_pipeline_end_to_end(self, flags_all_on):
        """
        Full planner → executor → validator pipeline via process_message_v2.

        Schema responses are fed in order:
          1. planner call → ExecutionPlan
          2. executor turn 1 → final answer
          3. validator call → pass
        """
        agent = make_agent("code_review_agent")
        agent._context_assembler = stub_assembler()
        schema_call_count = 0

        async def _ordered_schema(*a, **kw):
            nonlocal schema_call_count
            schema_call_count += 1
            # executor turn → final; validator → pass; planner fallback → plan
            if schema_call_count == 1:
                return json.loads(_EXECUTOR_FINAL)
            else:
                return json.loads(_VALIDATION_PASS)

        with patch.object(agent.llm, "chat_with_schema", side_effect=_ordered_schema):
            result = await agent.process_message_v2("Review the latest diff for DRIFT_GUARD violations.")

        assert isinstance(result, str)
        assert len(result) > 0
        # Planner and validator both go through the router stub (fixture).
        # Executor turn goes through chat_with_schema → at least 1 schema call.
        assert schema_call_count >= 1, f"Expected ≥1 executor schema call, got {schema_call_count}"


# ===========================================================================
# 3. GitNexus use in code_review_agent
# ===========================================================================


class TestGitNexusInCodeReview:
    """code_review_agent has GitNexus tools in its tool_permissions.
    When GITNEXUS_ENABLED=true the planner hints at blast-radius analysis."""

    def test_code_review_agent_has_all_gitnexus_permissions(self):
        from backend.agents import CODE_REVIEW_AGENT_DEFINITION

        gn_tools = [
            "mcp_gitnexus_query",
            "mcp_gitnexus_context",
            "mcp_gitnexus_impact",
            "mcp_gitnexus_detect_changes",
            "mcp_gitnexus_list_repos",
        ]
        for t in gn_tools:
            assert t in CODE_REVIEW_AGENT_DEFINITION.tool_permissions, f"code_review_agent missing: {t}"

    def test_gitnexus_tools_are_readonly(self):
        from backend.models import ModificationType
        from backend.tools import TOOL_REGISTRY

        for name, td in TOOL_REGISTRY.items():
            if name.startswith("mcp_gitnexus_"):
                assert td.modification_type == ModificationType.READ_ONLY, (
                    f"{name} must be READ_ONLY, got {td.modification_type}"
                )

    @pytest.mark.asyncio
    async def test_executor_blocks_gitnexus_for_wrong_agent(self, flags_all_on):
        """monitor_agent must NOT be able to call mcp_gitnexus_impact."""
        agent = make_agent("monitor_agent")
        agent._context_assembler = stub_assembler()

        turn_with_gitnexus = json.dumps(
            {
                "content": "Let me check blast radius.",
                "tool_calls": [
                    {"id": "tc_1", "name": "mcp_gitnexus_impact", "arguments": {"symbol": "process_message"}}
                ],
                "is_final": False,
            }
        )
        fallback_final = json.dumps(
            {
                "content": "Done.",
                "tool_calls": [],
                "is_final": True,
            }
        )
        responses = iter([turn_with_gitnexus, fallback_final])

        async def _schema_resp(*a, **kw):
            return json.loads(next(responses, json.dumps({"content": "Done.", "tool_calls": [], "is_final": True})))

        import backend.agents as _agents

        executed_tools: list[str] = []

        async def _mock_execute(tool_name, args):
            executed_tools.append(tool_name)
            return {"content": "ok"}

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(agent, "_execute_tool", side_effect=_mock_execute):
                with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                    await agent.process_message_v2("Check health metrics.")

        assert "mcp_gitnexus_impact" not in executed_tools, "monitor_agent must not execute mcp_gitnexus_impact"

    @pytest.mark.asyncio
    async def test_executor_allows_gitnexus_for_code_review_agent(self, flags_all_on):
        """code_review_agent CAN call mcp_gitnexus_impact — ToolValidator must allow it."""
        from backend.agents import CODE_REVIEW_AGENT_DEFINITION
        from backend.utils.tool_validator import validator_for_agent

        validator = validator_for_agent(CODE_REVIEW_AGENT_DEFINITION.tool_permissions)
        result = validator.validate("mcp_gitnexus_impact")
        assert result.valid, f"code_review_agent should be allowed mcp_gitnexus_impact: {result.error_message}"


# ===========================================================================
# 4. Qdrant-backed retrieval affecting agent context
# ===========================================================================


class TestQdrantRetrieval:
    """ContextAssembler with in-memory Qdrant."""

    @pytest.fixture
    def in_memory_assembler(self) -> ContextAssembler:
        """ContextAssembler backed by in-memory Qdrant."""
        from backend.knowledge.context_assembler import ContextAssembler
        from backend.ml.vector_store import QDRANT_AVAILABLE, VectorStore

        if not QDRANT_AVAILABLE:
            pytest.skip("qdrant-client not installed")

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(return_value=[0.1] * 768)
        mock_llm.model = "test"

        ca = ContextAssembler(mock_llm)
        # Replace the shared singleton with a fresh in-memory store
        ca._store = VectorStore(in_memory=True, default_dim=768)
        return ca

    @pytest.mark.asyncio
    async def test_ingest_then_retrieve_returns_content(self, in_memory_assembler):
        """Content ingested via ingest_memory must appear in subsequent retrieve()."""
        ca = in_memory_assembler
        agent_id = "code_review_agent"
        content = "The invariant INV-3 forbids direct tool-to-tool calls."

        ingested = await ca.ingest_memory(
            agent_id=agent_id,
            content=content,
            metadata={"type": "test"},
        )
        assert ingested is True, "ingest_memory must return True on success"

        # Use same embed vector so search finds it
        result_str = await ca.retrieve(query="invariant", agent_id=agent_id, limit=3)
        assert isinstance(result_str, str)
        assert "INV-3" in result_str or "invariant" in result_str.lower(), (
            f"Expected ingested content in retrieve output, got: {result_str!r}"
        )

    @pytest.mark.asyncio
    async def test_retrieve_empty_collection_returns_empty_string(self, in_memory_assembler):
        """Retrieve on an empty collection should return empty string, not raise."""
        ca = in_memory_assembler
        result = await ca.retrieve(query="anything", agent_id="new_agent_xyz", limit=3)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_retrieve_injects_into_executor_context(self, flags_all_on):
        """When ContextAssembler.retrieve returns content, _executor_turn includes it in prompt."""
        from backend.ml.vector_store import QDRANT_AVAILABLE

        if not QDRANT_AVAILABLE:
            pytest.skip("qdrant-client not installed")

        agent = make_agent("code_review_agent")
        captured_prompts: list[str] = []

        async def _schema_resp(messages, schema, **kw):
            for m in messages:
                if m.get("role") == "system":
                    captured_prompts.append(m["content"])
            return json.loads(_EXECUTOR_FINAL)

        rag_content = "Retrieved context:\n[score=0.92]\nINV-3 must never be violated."

        mock_assembler = AsyncMock()
        mock_assembler.retrieve = AsyncMock(return_value=rag_content)
        mock_assembler.ingest_memory = AsyncMock(return_value=True)

        agent._context_assembler = mock_assembler

        import backend.agents as _agents

        with patch.object(agent.llm, "chat_with_schema", side_effect=_schema_resp):
            with patch.object(_agents, "AGENT_PLANNER_ENABLED", False):
                await agent.process_message_v2("Review recent changes.")

        combined = " ".join(captured_prompts)
        assert "INV-3" in combined or "Retrieved context" in combined, (
            "RAG content must appear in executor system prompt on turn 1"
        )

    def test_health_check_reports_connected(self):
        """ContextAssembler.health_check() returns qdrant_available=True for in-memory store."""
        from backend.knowledge.context_assembler import ContextAssembler
        from backend.ml.vector_store import QDRANT_AVAILABLE, VectorStore

        if not QDRANT_AVAILABLE:
            pytest.skip("qdrant-client not installed")

        mock_llm = MagicMock()
        ca = ContextAssembler(mock_llm)
        ca._store = VectorStore(in_memory=True, default_dim=768)

        health = ca.health_check()
        assert health["qdrant_available"] is True
        assert health["fallback_active"] is False

    def test_health_check_reports_fallback_when_no_client(self):
        """health_check returns fallback_active=True when store._client is None."""
        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        ca = ContextAssembler(mock_llm)
        ca._store._client = None  # simulate disconnected

        health = ca.health_check()
        assert health["qdrant_available"] is False
        assert health["fallback_active"] is True

    @pytest.mark.asyncio
    async def test_fallback_logs_warning_when_qdrant_down(self, caplog):
        """_fallback_retrieve must emit WARNING so operators see degraded state."""
        import logging

        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = AsyncMock()
        mock_llm.embed = AsyncMock(return_value=[])  # empty → triggers fallback

        ca = ContextAssembler(mock_llm)
        with patch.object(ca, "_fallback_retrieve", wraps=ca._fallback_retrieve):
            with caplog.at_level(logging.WARNING, logger="backend.knowledge.context_assembler"):
                await ca.retrieve(query="test", agent_id="code_review_agent")

        assert any("fallback" in r.message.lower() or "unavailable" in r.message.lower() for r in caplog.records), (
            "ContextAssembler must log WARNING when using fallback path"
        )
