"""Deterministic tests for deerflow — FactMemoryMiddleware, setup, and pure-logic components.

No Ollama calls. All LLM interactions mocked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from deerflow.memory.middleware import FactMemoryMiddleware
from deerflow.middleware.chain import LLMContext

# ── FactMemoryMiddleware ─────────────────────────────────────────────


class TestFactMemoryMiddleware:
    def _make_middleware(self, facts_text: str = ""):
        fm = MagicMock()
        fm.build_prompt_section.return_value = facts_text
        fm.extract = AsyncMock()
        return FactMemoryMiddleware(fm, inject_limit=5)

    @pytest.mark.asyncio
    async def test_before_llm_injects_facts_into_system_message(self):
        mw = self._make_middleware("Known: user prefers Python")
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        meta = LLMContext(agent_id="soul_core")
        result = await mw.before_llm(messages, meta)
        assert "Known: user prefers Python" in result[0]["content"]

    @pytest.mark.asyncio
    async def test_before_llm_no_injection_when_empty(self):
        mw = self._make_middleware("")
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        meta = LLMContext(agent_id="devops_agent")
        result = await mw.before_llm(messages, meta)
        assert result[0]["content"] == "You are helpful."

    @pytest.mark.asyncio
    async def test_before_llm_stashes_messages_for_after(self):
        mw = self._make_middleware("")
        messages = [{"role": "user", "content": "Hi"}]
        meta = LLMContext(agent_id="test_agent")
        await mw.before_llm(messages, meta)
        assert "test_agent" in mw._pending

    @pytest.mark.asyncio
    async def test_after_llm_extracts_facts(self):
        mw = self._make_middleware("")
        messages = [{"role": "user", "content": "I like Rust"}]
        meta = LLMContext(agent_id="test_agent")
        await mw.before_llm(messages, meta)
        result = await mw.after_llm("Great, Rust is fast!", meta)
        assert result == "Great, Rust is fast!"
        mw._fm.extract.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_after_llm_handles_extraction_error(self):
        mw = self._make_middleware("")
        mw._fm.extract = AsyncMock(side_effect=RuntimeError("extraction failed"))
        messages = [{"role": "user", "content": "test"}]
        meta = LLMContext(agent_id="test_agent")
        await mw.before_llm(messages, meta)
        # Should not raise — error is caught and logged
        result = await mw.after_llm("response", meta)
        assert result == "response"

    @pytest.mark.asyncio
    async def test_after_llm_pops_pending(self):
        mw = self._make_middleware("")
        messages = [{"role": "user", "content": "test"}]
        meta = LLMContext(agent_id="agent_a")
        await mw.before_llm(messages, meta)
        assert "agent_a" in mw._pending
        await mw.after_llm("done", meta)
        assert "agent_a" not in mw._pending


# ── create_deerflow_chain ────────────────────────────────────────────


class TestCreateDeerflowChain:
    def test_creates_chain_with_all_middlewares(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
        )
        # Should have 7 middlewares (health, drift, rate, logging, fact, skill, summarization)
        assert len(chain._middlewares) == 7

    def test_attaches_fact_memory(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
        )
        assert hasattr(chain, "fact_memory")

    def test_attaches_skill_loader(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
        )
        assert hasattr(chain, "skill_loader")

    def test_attaches_health_monitor(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
        )
        assert hasattr(chain, "health_monitor")

    def test_no_repair_engine_by_default(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
        )
        assert not hasattr(chain, "repair_engine")

    def test_auto_repair_attaches_repair_engine(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
            enable_auto_repair=True,
        )
        assert hasattr(chain, "repair_engine")

    def test_delegator_attached_with_orchestrator(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
            orchestrator=MagicMock(),
        )
        assert hasattr(chain, "delegator")

    def test_no_delegator_without_orchestrator(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MagicMock(),
            memory_store=MagicMock(),
            skill_registry=MagicMock(),
            orchestrator=None,
        )
        assert not hasattr(chain, "delegator")
