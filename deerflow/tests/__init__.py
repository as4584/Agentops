"""
Tests for DeerFlow components — middleware chain, fact memory,
context summarization, task delegation, progressive skills.
"""

import asyncio
import json
import time

import pytest

# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------


class MockLLM:
    """Simulates OllamaClient for testing."""

    def __init__(self, response: str = "ok") -> None:
        self._response = response
        self.calls: list[dict] = []

    async def generate(self, prompt, system="", temperature=0.7, max_tokens=2048):
        self.calls.append({"prompt": prompt, "system": system})
        return self._response

    async def chat(self, messages, temperature=0.7, max_tokens=2048):
        self.calls.append({"messages": messages})
        return self._response

    async def embed(self, text):
        return [0.1] * 64


class MockMemoryStore:
    """Simulates MemoryStore with in-memory dict."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, object]] = {}

    def read(self, namespace, key, default=None):
        return self._data.get(namespace, {}).get(key, default)

    def read_all(self, namespace):
        return dict(self._data.get(namespace, {}))

    def write(self, namespace, key, value):
        self._data.setdefault(namespace, {})[key] = value

    def delete(self, namespace, key):
        ns = self._data.get(namespace, {})
        if key in ns:
            del ns[key]
            return True
        return False

    def list_namespaces(self):
        return list(self._data.keys())


class MockSkillRegistry:
    """Simulates SkillRegistry."""

    def build_prompt(self, skill_ids, agent_id):
        if not skill_ids:
            return ""
        return f"## Skills: {', '.join(skill_ids)}"


class MockOrchestrator:
    """Simulates AgentOrchestrator."""

    def __init__(self) -> None:
        self._agents = ["devops_agent", "security_agent", "code_review_agent"]

    def get_available_agents(self):
        return self._agents

    async def process_message(self, agent_id, message, context=None):
        return {
            "agent_id": agent_id,
            "response": f"[{agent_id}] processed: {message[:50]}",
            "drift_status": "GREEN",
            "error": None,
        }


# ---------------------------------------------------------------------------
# Tests — Middleware Chain
# ---------------------------------------------------------------------------


class TestMiddlewareChain:
    def test_add_and_stack_order(self):
        from deerflow.middleware.chain import (
            LoggingMiddleware,
            Middleware,
            MiddlewareChain,
            RateLimitMiddleware,
        )

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())      # priority 20
        chain.add(RateLimitMiddleware())    # priority 15

        # Should be sorted by priority
        assert chain.stack == ["rate_limit", "logging"]

    def test_remove(self):
        from deerflow.middleware.chain import (
            LoggingMiddleware,
            MiddlewareChain,
            RateLimitMiddleware,
        )

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())
        chain.add(RateLimitMiddleware())
        assert chain.remove("logging") is True
        assert chain.stack == ["rate_limit"]
        assert chain.remove("nonexistent") is False

    @pytest.mark.asyncio
    async def test_before_tool_passthrough(self):
        from deerflow.middleware.chain import (
            LoggingMiddleware,
            MiddlewareChain,
            ToolContext,
        )

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())

        ctx = ToolContext(tool_name="file_reader", agent_id="test", kwargs={})
        result = await chain.run_before_tool(ctx)
        assert result is not None
        assert result.tool_name == "file_reader"

    @pytest.mark.asyncio
    async def test_before_tool_blocking(self):
        from deerflow.middleware.chain import (
            Middleware,
            MiddlewareChain,
            ToolContext,
        )

        class BlockAll(Middleware):
            name = "blocker"
            priority = 1

            async def before_tool(self, ctx):
                ctx.blocked = True
                ctx.block_reason = "testing"
                return None

        chain = MiddlewareChain()
        chain.add(BlockAll())

        ctx = ToolContext(tool_name="safe_shell", agent_id="test", kwargs={})
        result = await chain.run_before_tool(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limiter(self):
        from deerflow.middleware.chain import (
            MiddlewareChain,
            RateLimitMiddleware,
            ToolContext,
        )

        chain = MiddlewareChain()
        chain.add(RateLimitMiddleware(max_calls_per_minute=3))

        for i in range(3):
            ctx = ToolContext(tool_name="test", agent_id="a1", kwargs={})
            assert await chain.run_before_tool(ctx) is not None

        # 4th call should be blocked
        ctx = ToolContext(tool_name="test", agent_id="a1", kwargs={})
        assert await chain.run_before_tool(ctx) is None

    @pytest.mark.asyncio
    async def test_llm_hooks(self):
        from deerflow.middleware.chain import (
            LLMContext,
            LoggingMiddleware,
            MiddlewareChain,
        )

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())

        msgs = [{"role": "user", "content": "hello"}]
        meta = LLMContext(agent_id="test")

        result = await chain.run_before_llm(msgs, meta)
        assert result == msgs

        resp = await chain.run_after_llm("world", meta)
        assert resp == "world"


# ---------------------------------------------------------------------------
# Tests — Fact Memory
# ---------------------------------------------------------------------------


class TestFactMemory:
    @pytest.mark.asyncio
    async def test_extract_and_retrieve(self):
        from deerflow.memory.facts import FactMemory

        llm = MockLLM(
            response=json.dumps([
                {"content": "User prefers Python", "category": "preference", "confidence": 0.9},
                {"content": "Deploys on Fridays", "category": "behavior", "confidence": 0.7},
            ])
        )
        mem = MockMemoryStore()
        fm = FactMemory(llm, mem)

        facts = await fm.extract(
            "devops_agent",
            [{"role": "user", "content": "I prefer Python and deploy on Fridays"}],
        )
        assert len(facts) == 2
        assert facts[0].content == "User prefers Python"

        # Retrieve
        all_facts = fm.get_all_facts("devops_agent")
        assert len(all_facts) == 2

    @pytest.mark.asyncio
    async def test_deduplication(self):
        from deerflow.memory.facts import FactMemory

        llm = MockLLM(
            response=json.dumps([
                {"content": "User prefers Python", "category": "preference", "confidence": 0.9},
            ])
        )
        mem = MockMemoryStore()
        fm = FactMemory(llm, mem)

        await fm.extract("a1", [{"role": "user", "content": "test"}])
        await fm.extract("a1", [{"role": "user", "content": "test again"}])

        assert len(fm.get_all_facts("a1")) == 1  # deduplicated

    def test_build_prompt_section(self):
        from deerflow.memory.facts import Fact, FactCategory, FactMemory

        mem = MockMemoryStore()
        mem.write("a1", "deerflow_facts", [
            Fact("User likes tests", FactCategory.PREFERENCE, 0.95, "a1").to_dict(),
        ])
        fm = FactMemory(MockLLM(), mem)

        section = fm.build_prompt_section("a1")
        assert "User likes tests" in section
        assert "preference" in section

    @pytest.mark.asyncio
    async def test_llm_error_graceful(self):
        from deerflow.memory.facts import FactMemory

        class FailLLM:
            async def generate(self, **kwargs):
                raise ConnectionError("offline")

        fm = FactMemory(FailLLM(), MockMemoryStore())
        facts = await fm.extract("a1", [{"role": "user", "content": "test"}])
        assert facts == []


# ---------------------------------------------------------------------------
# Tests — Context Summarization
# ---------------------------------------------------------------------------


class TestSummarization:
    @pytest.mark.asyncio
    async def test_no_compression_under_limit(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        mw = SummarizationMiddleware(MockLLM(), max_history=10, keep_recent=3)
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        meta = LLMContext(agent_id="test")
        result = await mw.before_llm(msgs, meta)
        assert len(result) == 3  # unchanged

    @pytest.mark.asyncio
    async def test_compression_over_limit(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MockLLM(response="Summary of old messages.")
        mw = SummarizationMiddleware(llm, max_history=5, keep_recent=2)

        msgs = [{"role": "system", "content": "sys"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"msg {i}"})
            msgs.append({"role": "assistant", "content": f"reply {i}"})

        meta = LLMContext(agent_id="test")
        result = await mw.before_llm(msgs, meta)

        # Should have: system + recap + last 2 non-system messages
        assert any("[CONTEXT RECAP]" in m.get("content", "") for m in result)
        assert len(result) < len(msgs)


# ---------------------------------------------------------------------------
# Tests — Task Delegation
# ---------------------------------------------------------------------------


class TestTaskDelegation:
    @pytest.mark.asyncio
    async def test_parallel_delegation(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = MockOrchestrator()
        delegator = TaskDelegator(orch)

        result = await delegator.delegate(
            parent_agent="gsd_agent",
            subtasks=[
                SubTask(agent_id="security_agent", instruction="Scan for secrets"),
                SubTask(agent_id="devops_agent", instruction="Check CI status"),
            ],
            synthesize=False,
        )

        assert len(result.outcomes) == 2
        assert all(o.success for o in result.outcomes)
        assert result.outcomes[0].agent_id == "security_agent"

    @pytest.mark.asyncio
    async def test_unknown_agent(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        delegator = TaskDelegator(MockOrchestrator())
        result = await delegator.delegate(
            parent_agent="gsd",
            subtasks=[
                SubTask(agent_id="nonexistent_agent", instruction="do thing"),
            ],
            synthesize=False,
        )

        assert len(result.outcomes) == 1
        assert not result.outcomes[0].success
        assert result.outcomes[0].error is not None
        assert "not registered" in result.outcomes[0].error

    @pytest.mark.asyncio
    async def test_sequential_delegation(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        delegator = TaskDelegator(MockOrchestrator())
        result = await delegator.delegate(
            parent_agent="gsd",
            subtasks=[
                SubTask(agent_id="devops_agent", instruction="step 1"),
                SubTask(agent_id="devops_agent", instruction="step 2"),
            ],
            parallel=False,
            synthesize=False,
        )

        assert len(result.outcomes) == 2
        assert all(o.success for o in result.outcomes)


# ---------------------------------------------------------------------------
# Tests — Progressive Skill Loader
# ---------------------------------------------------------------------------


class TestProgressiveSkills:
    def test_intent_classification(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        loader = ProgressiveSkillLoader(MockSkillRegistry())
        matches = loader.classify_intent("Set up CI/CD pipeline for staging")
        assert len(matches) >= 1
        assert matches[0].skill_id == "release_engineering"

    def test_no_match(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        loader = ProgressiveSkillLoader(MockSkillRegistry())
        matches = loader.classify_intent("What is the weather today?")
        assert len(matches) == 0

    def test_max_skills_limit(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        loader = ProgressiveSkillLoader(MockSkillRegistry())
        # This message should match multiple patterns
        matches = loader.classify_intent(
            "Deploy frontend React CI/CD pipeline with state machine"
        )
        assert len(matches) <= 3  # default max

    def test_build_prompt(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        loader = ProgressiveSkillLoader(MockSkillRegistry())
        section = loader.select_and_build(
            message="How to set up CI/CD?",
            agent_id="devops_agent",
        )
        assert "release_engineering" in section

    @pytest.mark.asyncio
    async def test_middleware_injection(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.skills.progressive import ProgressiveSkillLoader

        loader = ProgressiveSkillLoader(MockSkillRegistry())
        mw = loader.as_middleware()

        msgs = [
            {"role": "system", "content": "Base system prompt"},
            {"role": "user", "content": "Help me with CI/CD deployment"},
        ]
        meta = LLMContext(agent_id="devops_agent")

        result = await mw.before_llm(msgs, meta)

        # Skill section should be appended to the system message
        sys_msg = next(m for m in result if m["role"] == "system")
        assert "release_engineering" in sys_msg["content"]


# ---------------------------------------------------------------------------
# Tests — Full Chain Setup
# ---------------------------------------------------------------------------


class TestSetup:
    def test_create_chain(self):
        from deerflow.setup import create_deerflow_chain

        chain = create_deerflow_chain(
            llm_client=MockLLM(),
            memory_store=MockMemoryStore(),
            skill_registry=MockSkillRegistry(),
            orchestrator=MockOrchestrator(),
        )

        assert len(chain.stack) == 7
        assert chain.stack[0] == "tool_health"        # priority 8
        assert chain.stack[1] == "drift_guard"        # priority 10
        assert chain.stack[2] == "rate_limit"         # priority 15
        assert chain.stack[3] == "logging"            # priority 20
        assert chain.stack[4] == "fact_memory"        # priority 40
        assert chain.stack[5] == "progressive_skills" # priority 45
        assert chain.stack[6] == "summarization"      # priority 50

        assert hasattr(chain, "fact_memory")
        assert hasattr(chain, "skill_loader")
        assert hasattr(chain, "health_monitor")
        assert hasattr(chain, "delegator")


# ---------------------------------------------------------------------------
# Tests — Tool Health Monitor
# ---------------------------------------------------------------------------


class TestToolHealthMonitor:
    def test_record_call_and_stats(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        monitor.record_call("safe_shell")
        monitor.record_call("safe_shell")

        stats = monitor.get_stats("safe_shell")
        assert stats.total_calls == 2
        assert stats.total_failures == 0
        assert stats.failure_rate == 0.0

    def test_record_failure(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        monitor.record_call("file_reader")
        monitor.record_failure("file_reader", "cs_agent", "file not found", {"path": "/missing"})

        stats = monitor.get_stats("file_reader")
        assert stats.total_failures == 1
        assert stats.last_error == "file not found"
        assert stats.failure_rate == 1.0

    def test_is_chronic_detection(self):
        from deerflow.tools.health import ToolHealthMonitor, _CHRONIC_THRESHOLD

        monitor = ToolHealthMonitor(MockMemoryStore())
        # Record enough failures to trigger chronic detection
        for _ in range(_CHRONIC_THRESHOLD):
            monitor.record_call("health_check")
            monitor.record_failure("health_check", "monitor_agent", "unreachable")

        stats = monitor.get_stats("health_check")
        assert stats.is_chronic is True

    def test_health_report_empty(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        assert monitor.build_health_report() == ""

    def test_health_report_with_failures(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        monitor.record_call("webhook_send")
        monitor.record_call("webhook_send")
        monitor.record_failure("webhook_send", "comms_agent", "connection refused")

        report = monitor.build_health_report()
        assert "webhook_send" in report
        assert "Tool Health Report" in report


# ---------------------------------------------------------------------------
# Tests — detect_tool_failure
# ---------------------------------------------------------------------------


class TestDetectToolFailure:
    def test_success_no_error(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"content": "file contents", "exists": True})
        assert ok is False

    def test_explicit_error_key(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"error": "permission denied"})
        assert ok is True
        assert msg is not None
        assert "permission denied" in msg

    def test_success_false(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"success": False, "message": "write failed"})
        assert ok is True
        assert msg is not None
        assert "write failed" in msg

    def test_reachable_false(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"reachable": False, "url": "http://localhost:9999"})
        assert ok is True
        assert msg is not None
        assert "unreachable" in msg

    def test_file_not_found(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"exists": False, "content": ""})
        assert ok is True
        assert msg is not None
        assert "not found" in msg

    def test_nonzero_exit_code(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"return_code": 127, "stdout": "", "stderr": "command not found"})
        assert ok is True
        assert msg is not None
        assert "127" in msg

    def test_zero_exit_code_is_ok(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, _ = detect_tool_failure({"return_code": 0, "stdout": "done", "stderr": ""})
        assert ok is False

    def test_non_dict_result(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, _ = detect_tool_failure("some string")
        assert ok is False


# ---------------------------------------------------------------------------
# Tests — ToolRepairEngine
# ---------------------------------------------------------------------------


class TestToolRepairEngine:
    @pytest.mark.asyncio
    async def test_suggest_repair_valid_json(self):
        from deerflow.tools.repair import ToolRepairEngine, RepairSuggestion
        from deerflow.tools.health import ToolHealthMonitor
        import json

        repair_json = json.dumps({
            "strategy": "mutate",
            "suggested_kwargs": {"command": "docker info"},
            "rationale": "Try docker info instead",
            "confidence": 0.85,
        })
        llm = MockLLM(response=repair_json)
        monitor = ToolHealthMonitor(MockMemoryStore())
        engine = ToolRepairEngine(llm, monitor)

        suggestion = await engine.suggest_repair(
            "safe_shell", "devops_agent", "exit code 1", {"command": "docker ps"}
        )
        assert suggestion.strategy == "mutate"
        assert suggestion.confidence == 0.85

    @pytest.mark.asyncio
    async def test_chronic_tool_escalates_immediately(self):
        from deerflow.tools.repair import ToolRepairEngine
        from deerflow.tools.health import ToolHealthMonitor, _CHRONIC_THRESHOLD

        monitor = ToolHealthMonitor(MockMemoryStore())
        for _ in range(_CHRONIC_THRESHOLD):
            monitor.record_failure("broken_tool", "agent", "always fails")

        engine = ToolRepairEngine(MockLLM(), monitor)
        suggestion = await engine.suggest_repair(
            "broken_tool", "agent", "failed again", {}
        )
        assert suggestion.strategy == "escalate"

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_to_skip(self):
        from deerflow.tools.repair import ToolRepairEngine
        from deerflow.tools.health import ToolHealthMonitor

        class BrokenLLM:
            async def generate(self, *a, **kw):
                raise RuntimeError("LLM offline")

        monitor = ToolHealthMonitor(MockMemoryStore())
        engine = ToolRepairEngine(BrokenLLM(), monitor)
        suggestion = await engine.suggest_repair("safe_shell", "agent", "err", {})
        assert suggestion.strategy == "skip"


# ---------------------------------------------------------------------------
# Tests — ToolHealthMiddleware
# ---------------------------------------------------------------------------


class TestToolHealthMiddleware:
    @pytest.mark.asyncio
    async def test_records_successful_call(self):
        from deerflow.tools.middleware import ToolHealthMiddleware, detect_tool_failure
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.middleware.chain import ToolContext

        monitor = ToolHealthMonitor(MockMemoryStore())
        mw = ToolHealthMiddleware(monitor)

        ctx = ToolContext(tool_name="file_reader", agent_id="cs_agent", kwargs={})
        ctx = await mw.before_tool(ctx)

        result = {"content": "hello", "exists": True}
        result = await mw.after_tool(ctx, result)

        assert result["_health"]["status"] == "ok"
        stats = monitor.get_stats("file_reader")
        assert stats.total_calls == 1
        assert stats.total_failures == 0

    @pytest.mark.asyncio
    async def test_records_failure_and_annotates(self):
        from deerflow.tools.middleware import ToolHealthMiddleware
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.middleware.chain import ToolContext

        monitor = ToolHealthMonitor(MockMemoryStore())
        mw = ToolHealthMiddleware(monitor)

        ctx = ToolContext(tool_name="health_check", agent_id="monitor_agent", kwargs={})
        await mw.before_tool(ctx)

        result = {"reachable": False, "url": "http://localhost:9999"}
        result = await mw.after_tool(ctx, result)

        assert result["_health"]["status"] == "failed"
        assert result["_health"]["error"] == "unreachable: http://localhost:9999"
        stats = monitor.get_stats("health_check")
        assert stats.total_failures == 1


# ---------------------------------------------------------------------------
# Tests — ToolHealthMonitor fallback_rate
# ---------------------------------------------------------------------------


class TestFallbackRateMetric:
    def test_record_and_retrieve_skill_stats(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        monitor.record_skill_selected("newsletter_weekly_tips")
        monitor.record_skill_selected("newsletter_weekly_tips")
        monitor.record_skill_applied("newsletter_weekly_tips")

        stats = monitor.get_skill_fallback_stats()
        assert "newsletter_weekly_tips" in stats
        s = stats["newsletter_weekly_tips"]
        assert s["selected_count"] == 2
        assert s["applied_count"] == 1
        assert s["fallback_rate"] == 0.5

    def test_zero_fallback_when_always_applied(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        monitor.record_skill_selected("my_skill")
        monitor.record_skill_applied("my_skill")

        stats = monitor.get_skill_fallback_stats()
        assert stats["my_skill"]["fallback_rate"] == 0.0

    def test_fallback_rate_in_health_report(self):
        from deerflow.tools.health import ToolHealthMonitor

        monitor = ToolHealthMonitor(MockMemoryStore())
        # 5 selected, 1 applied = 80% fallback — should appear in report
        for _ in range(5):
            monitor.record_skill_selected("stale_skill")
        monitor.record_skill_applied("stale_skill")

        report = monitor.build_health_report()
        assert "stale_skill" in report
        assert "fallback" in report.lower()


# ---------------------------------------------------------------------------
# Tests — ToolRepairEngine anti-loop guard
# ---------------------------------------------------------------------------


class TestAntiLoopGuard:
    @pytest.mark.asyncio
    async def test_second_attempt_escalates(self):
        """Same (tool, error) pair should escalate on the second call."""
        from deerflow.tools.repair import ToolRepairEngine, RepairSuggestion
        from deerflow.tools.health import ToolHealthMonitor
        import json

        repair_json = json.dumps({
            "strategy": "retry",
            "suggested_kwargs": {},
            "rationale": "transient",
            "confidence": 0.8,
        })
        llm = MockLLM(response=repair_json)
        monitor = ToolHealthMonitor(MockMemoryStore())
        engine = ToolRepairEngine(llm, monitor)

        s1 = await engine.suggest_repair("safe_shell", "agent", "exit code 1", {})
        assert s1.strategy == "retry"  # first attempt: normal repair

        s2 = await engine.suggest_repair("safe_shell", "agent", "exit code 1", {})
        assert s2.strategy == "escalate"  # second: anti-loop kicks in

    @pytest.mark.asyncio
    async def test_different_errors_not_blocked(self):
        """Different error fingerprints should not be treated as a loop."""
        from deerflow.tools.repair import ToolRepairEngine
        from deerflow.tools.health import ToolHealthMonitor
        import json

        llm = MockLLM(response=json.dumps({
            "strategy": "retry", "suggested_kwargs": {}, "rationale": "ok", "confidence": 0.8
        }))
        monitor = ToolHealthMonitor(MockMemoryStore())
        engine = ToolRepairEngine(llm, monitor)

        s1 = await engine.suggest_repair("safe_shell", "agent", "exit code 1", {})
        s2 = await engine.suggest_repair("safe_shell", "agent", "permission denied", {})
        assert s1.strategy == "retry"
        assert s2.strategy == "retry"  # different error, not blocked


# ---------------------------------------------------------------------------
# Tests — ExecutionRecorder
# ---------------------------------------------------------------------------


class TestExecutionRecorder:
    def test_start_and_end_run(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run(agent_id="devops_agent", message="check CI")
        assert run_id
        assert run_id in recorder._open_runs

        record = recorder.end_run(run_id=run_id, agent_id="devops_agent", response="done")
        assert record is not None
        assert record.ended_at is not None
        assert run_id not in recorder._open_runs

    def test_record_tool_call_appended(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run(agent_id="monitor_agent", message="ping")
        recorder.record_tool_call(
            run_id=run_id,
            agent_id="monitor_agent",
            tool_name="health_check",
            kwargs={"url": "http://localhost:8000"},
            result={"reachable": True},
            duration_ms=18.0,
        )
        recorder.end_run(run_id=run_id, agent_id="monitor_agent")

        entries = recorder.load_run("monitor_agent", run_id)
        tool_entries = [e for e in entries if e["_type"] == "tool_call"]
        assert len(tool_entries) == 1
        assert tool_entries[0]["tool_name"] == "health_check"

    def test_prunes_old_runs(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder, _MAX_RUNS_PER_AGENT

        recorder = ExecutionRecorder(base_dir=tmp_path)
        # Create MAX + 2 runs to force pruning
        for _ in range(_MAX_RUNS_PER_AGENT + 2):
            rid = recorder.start_run("agent", "msg")
            recorder.end_run(rid, "agent")

        remaining = recorder.list_runs("agent")
        assert len(remaining) <= _MAX_RUNS_PER_AGENT

    def test_end_run_unknown_returns_none(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        result = recorder.end_run("nonexistent-id", "some_agent")
        assert result is None


# ---------------------------------------------------------------------------
# Tests — ExecutionAnalyzer
# ---------------------------------------------------------------------------


class TestExecutionAnalyzer:
    @pytest.mark.asyncio
    async def test_analyze_run_no_tool_calls_returns_none(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder
        from deerflow.execution.analyzer import ExecutionAnalyzer
        from deerflow.tools.health import ToolHealthMonitor

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run("devops_agent", "hello")
        recorder.end_run(run_id, "devops_agent")

        monitor = ToolHealthMonitor(MockMemoryStore())
        analyzer = ExecutionAnalyzer(MockLLM(), monitor)
        result = await analyzer.analyze_run(run_id, "devops_agent", recorder)
        assert result is None  # no tool calls to analyze

    @pytest.mark.asyncio
    async def test_analyze_run_parses_judgments(self, tmp_path):
        import json
        from deerflow.execution.recorder import ExecutionRecorder
        from deerflow.execution.analyzer import ExecutionAnalyzer
        from deerflow.tools.health import ToolHealthMonitor

        analysis_json = json.dumps({
            "tool_judgments": [
                {
                    "tool_name": "safe_shell",
                    "status": "degraded",
                    "issue": "intermittent exit code 1",
                    "suggested_fix": "check docker daemon",
                }
            ],
            "skill_judgments": [],
            "escalate": False,
            "escalation_reason": None,
        })
        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run("devops_agent", "run docker ps")
        recorder.record_tool_call(
            run_id=run_id, agent_id="devops_agent",
            tool_name="safe_shell", kwargs={"command": "docker ps"},
            result={"return_code": 1}, failed=True, error="exit code 1",
        )
        recorder.end_run(run_id, "devops_agent")

        monitor = ToolHealthMonitor(MockMemoryStore())
        analyzer = ExecutionAnalyzer(MockLLM(response=analysis_json), monitor)
        judgment = await analyzer.analyze_run(run_id, "devops_agent", recorder)

        assert judgment is not None
        assert len(judgment.tool_judgments) == 1
        assert judgment.tool_judgments[0]["tool_name"] == "safe_shell"
        # Analyzer should have fed the degradation back into monitor
        stats = monitor.get_stats("safe_shell")
        assert stats.total_failures == 1

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty_judgment(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder
        from deerflow.execution.analyzer import ExecutionAnalyzer
        from deerflow.tools.health import ToolHealthMonitor

        class BrokenLLM:
            async def generate(self, *a, **kw):
                raise RuntimeError("offline")

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run("agent", "msg")
        recorder.record_tool_call(
            run_id=run_id, agent_id="agent",
            tool_name="health_check", kwargs={}, result={"reachable": False},
            failed=True, error="unreachable",
        )
        recorder.end_run(run_id, "agent")

        analyzer = ExecutionAnalyzer(BrokenLLM(), ToolHealthMonitor(MockMemoryStore()))
        judgment = await analyzer.analyze_run(run_id, "agent", recorder)
        # Should return an empty (not None) judgment — non-fatal
        assert judgment is not None
        assert judgment.tool_judgments == []
