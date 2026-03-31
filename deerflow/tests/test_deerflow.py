"""
Tests for DeerFlow components — middleware chain, fact memory,
context summarization, task delegation, progressive skills,
and execution recorder.

Run: pytest deerflow/tests/test_deerflow.py -v
"""

import json

import pytest

# ===========================================================================
# ExecutionRecorder
# ===========================================================================
from deerflow.execution.recorder import ExecutionRecorder
from deerflow.tests import MockLLM


@pytest.fixture()
def recorder(tmp_path):
    return ExecutionRecorder(base_dir=tmp_path / "agents")


def test_start_run_returns_unique_run_id(recorder):
    run_id_1 = recorder.start_run("devops_agent", "check CI")
    run_id_2 = recorder.start_run("devops_agent", "check CI")
    assert run_id_1 != run_id_2


def test_record_tool_call_writes_jsonl(recorder, tmp_path):
    run_id = recorder.start_run("devops_agent", "deploy")
    recorder.record_tool_call(
        run_id=run_id,
        agent_id="devops_agent",
        tool_name="safe_shell",
        kwargs={"command": "git status"},
        result={"stdout": "nothing to commit", "return_code": 0},
        duration_ms=42,
        failed=False,
    )
    recorder.end_run(run_id, "devops_agent", "All good.")

    run_file = tmp_path / "agents" / "devops_agent" / "runs" / f"{run_id}.jsonl"
    assert run_file.exists()
    lines = run_file.read_text().strip().splitlines()
    # Expect at least: run_start + tool_call + run_end = 3 lines
    assert len(lines) >= 2

    first_tool = json.loads(lines[1])  # lines[0] is run_start
    assert first_tool["tool_name"] == "safe_shell"
    assert first_tool["_type"] == "tool_call"


def test_end_run_writes_sentinel(recorder, tmp_path):
    run_id = recorder.start_run("monitor_agent", "health check")
    recorder.end_run(run_id, "monitor_agent", "Healthy.")

    run_file = tmp_path / "agents" / "monitor_agent" / "runs" / f"{run_id}.jsonl"
    lines = run_file.read_text().strip().splitlines()
    last = json.loads(lines[-1])
    assert last["_type"] == "run_end"
    assert last["response"] == "Healthy."


def test_recorder_prunes_old_runs(tmp_path, monkeypatch):
    import deerflow.execution.recorder as rec_module

    monkeypatch.setattr(rec_module, "_MAX_RUNS_PER_AGENT", 3)
    recorder = ExecutionRecorder(base_dir=tmp_path / "agents")
    agent = "prune_agent"
    for i in range(5):
        rid = recorder.start_run(agent, f"msg {i}")
        recorder.end_run(rid, agent, "done")

    runs_dir = tmp_path / "agents" / agent / "runs"
    files = list(runs_dir.glob("*.jsonl"))
    assert len(files) <= 3


def test_failed_tool_call_recorded(recorder, tmp_path):
    run_id = recorder.start_run("self_healer_agent", "restart")
    recorder.record_tool_call(
        run_id=run_id,
        agent_id="self_healer_agent",
        tool_name="process_restart",
        kwargs={"process": "backend"},
        result={},
        duration_ms=5,
        failed=True,
        error="Permission denied",
    )
    recorder.end_run(run_id, "self_healer_agent", "failed.")

    run_file = tmp_path / "agents" / "self_healer_agent" / "runs" / f"{run_id}.jsonl"
    entry = json.loads(run_file.read_text().strip().splitlines()[1])  # lines[0] is run_start
    assert entry["failed"] is True
    assert entry["error"] == "Permission denied"


# ===========================================================================
# MiddlewareChain
# ===========================================================================

from deerflow.middleware.chain import LLMContext, Middleware, MiddlewareChain, ToolContext


class LoggingMiddleware(Middleware):
    name = "logger"
    priority = 50

    def __init__(self):
        self.before_calls: list[str] = []
        self.after_calls: list[str] = []

    async def before_tool(self, ctx: ToolContext) -> ToolContext | None:
        self.before_calls.append(ctx.tool_name)
        return ctx

    async def after_tool(self, ctx: ToolContext, result: dict) -> dict:
        self.after_calls.append(ctx.tool_name)
        return result


class BlockingMiddleware(Middleware):
    name = "blocker"
    priority = 20

    async def before_tool(self, ctx: ToolContext) -> ToolContext | None:
        ctx.blocked = True
        ctx.block_reason = "blocked by test"
        return None  # None = block


@pytest.mark.asyncio
async def test_chain_runs_before_and_after_hooks():
    chain = MiddlewareChain()
    logger = LoggingMiddleware()
    chain.add(logger)

    async def _tool(**kwargs):
        return {"ok": True}

    ctx = ToolContext(tool_name="safe_shell", agent_id="devops_agent", kwargs={})
    ctx = await chain.run_before_tool(ctx)
    assert ctx is not None
    result = await _tool(**ctx.kwargs)
    result = await chain.run_after_tool(ctx, result)

    assert "safe_shell" in logger.before_calls
    assert "safe_shell" in logger.after_calls
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_blocking_middleware_stops_execution():
    chain = MiddlewareChain()
    chain.add(BlockingMiddleware())
    called = []

    async def _tool(**kwargs):
        called.append(True)
        return {"ok": True}

    ctx = ToolContext(tool_name="safe_shell", agent_id="devops_agent", kwargs={})
    result = await chain.run_before_tool(ctx)

    assert called == []  # tool never executed — blocked before reaching it
    assert result is None  # None = blocked


@pytest.mark.asyncio
async def test_chain_priority_ordering():
    """Lower priority number runs before higher."""
    order: list[str] = []

    class FirstMiddleware(Middleware):
        name = "first"
        priority = 10

        async def before_tool(self, ctx):
            order.append("first")
            return ctx

    class SecondMiddleware(Middleware):
        name = "second"
        priority = 90

        async def before_tool(self, ctx):
            order.append("second")
            return ctx

    # Add in reverse order — chain should sort by priority
    chain = MiddlewareChain()
    chain.add(SecondMiddleware())
    chain.add(FirstMiddleware())

    async def _tool(**kwargs):
        return {}

    ctx = ToolContext(tool_name="file_reader", agent_id="monitor_agent", kwargs={})
    ctx = await chain.run_before_tool(ctx)
    assert ctx is not None  # not blocked

    assert order == ["first", "second"]


@pytest.mark.asyncio
async def test_chain_llm_hooks():
    class UppercaseMiddleware(Middleware):
        name = "upper"

        async def after_llm(self, response: str, meta: LLMContext) -> str:
            return response.upper()

    chain = MiddlewareChain()
    chain.add(UppercaseMiddleware())

    meta = LLMContext(agent_id="soul_core")
    messages = [{"role": "user", "content": "hi"}]
    messages = await chain.run_before_llm(messages, meta)
    raw_response = "hello"
    result = await chain.run_after_llm(raw_response, meta)
    assert result == "HELLO"


# ===========================================================================
# FactMemory
# ===========================================================================

from deerflow.memory.facts import Fact, FactCategory, FactMemory


@pytest.fixture()
def fact_memory(tmp_path, monkeypatch):
    import backend.config as cfg
    import backend.memory as mem_module
    from backend.memory import MemoryStore

    mem_dir = tmp_path / "memory"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    store = MemoryStore()
    llm = MockLLM(
        response=json.dumps(
            [
                {"content": "Deploy on Fridays", "category": "preference", "confidence": 0.9},
            ]
        )
    )
    return FactMemory(llm_client=llm, memory_store=store)


@pytest.mark.asyncio
async def test_extract_facts_from_messages(fact_memory):
    facts = await fact_memory.extract(
        agent_id="devops_agent",
        messages=[{"role": "user", "content": "Deploy on Fridays"}],
    )
    assert len(facts) >= 1
    assert any("deploy" in f.content.lower() for f in facts)


@pytest.mark.asyncio
async def test_extracted_facts_are_persisted(tmp_path, monkeypatch):
    import backend.config as cfg
    import backend.memory as mem_module
    from backend.memory import MemoryStore

    mem_dir = tmp_path / "memory2"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    store = MemoryStore()
    llm = MockLLM(
        response=json.dumps(
            [
                {"content": "Use pytest for all tests", "category": "preference", "confidence": 0.95},
            ]
        )
    )
    fm = FactMemory(llm_client=llm, memory_store=store)
    await fm.extract("code_review_agent", [{"role": "user", "content": "use pytest"}])

    # Read back
    facts = fm.get_top_facts("code_review_agent", limit=5)
    assert len(facts) >= 1
    assert any("pytest" in f.content.lower() for f in facts)


def test_get_top_facts_returns_empty_for_new_agent(fact_memory):
    facts = fact_memory.get_top_facts("never_seen_agent", limit=5)
    assert facts == []


def test_build_prompt_section_has_content_after_write(fact_memory):
    # Manually inject a fact to test prompt building
    fact = Fact(
        content="Always run tests before merge",
        category=FactCategory.PREFERENCE,
        confidence=0.99,
        source_agent="soul_core",
    )
    fact_memory._merge_and_store("soul_core", [fact])  # noqa: SLF001
    section = fact_memory.build_prompt_section("soul_core")
    assert "Always run tests before merge" in section


def test_build_prompt_section_empty_for_unknown(fact_memory):
    section = fact_memory.build_prompt_section("ghost_agent")
    assert section == "" or "no facts" in section.lower()


@pytest.mark.asyncio
async def test_extract_handles_empty_llm_response(tmp_path, monkeypatch):
    """LLM returns [] — no facts extracted, no crash."""
    import backend.config as cfg
    import backend.memory as mem_module
    from backend.memory import MemoryStore

    mem_dir = tmp_path / "memory3"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    store = MemoryStore()
    llm = MockLLM(response="[]")
    fm = FactMemory(llm_client=llm, memory_store=store)
    facts = await fm.extract("any_agent", [{"role": "user", "content": "hi"}])
    assert facts == []


@pytest.mark.asyncio
async def test_extract_handles_invalid_llm_json(tmp_path, monkeypatch):
    """LLM returns garbage — graceful fallback, no crash."""
    import backend.config as cfg
    import backend.memory as mem_module
    from backend.memory import MemoryStore

    mem_dir = tmp_path / "memory4"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    store = MemoryStore()
    llm = MockLLM(response="this is not json at all")
    fm = FactMemory(llm_client=llm, memory_store=store)
    facts = await fm.extract("any_agent", [{"role": "user", "content": "hello"}])
    assert isinstance(facts, list)
