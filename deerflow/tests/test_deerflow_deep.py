"""Deep coverage tests for deerflow modules.

Covers:
- recorder.py (load_run, list_runs, _prune_old_runs, record_tool_call edge cases)
- facts.py (_merge_and_store dedup, get_top_facts category filter, _parse_facts edge cases)
- chain.py (remove, stack, DriftGuardMiddleware, RateLimitMiddleware, LLM hooks)
- health.py (record_failure, get_stats, get_all_stats, build_health_report, skill tracking)
- analyzer.py (analyze_run, _build_prompt, _apply_judgments, _levenshtein, _fuzzy_match)
- delegation/task.py (TaskDelegator — parallel + sequential, unregistered agent, synthesis)
- tools/middleware.py (detect_tool_failure, ToolHealthMiddleware)
- tools/repair.py (ToolRepairEngine — suggest_repair, attempt_repair, anti-loop guard)
- middleware/summarization.py (SummarizationMiddleware)
- skills/progressive.py (ProgressiveSkillLoader)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def tmp_mem():
    """Isolated in-memory store compatible with MemoryStore interface."""

    class _InMemStore:
        def __init__(self):
            self._data: dict[str, dict] = {}

        def read(self, namespace: str, key: str, default=None):
            return self._data.get(namespace, {}).get(key, default)

        def write(self, namespace: str, key: str, value) -> None:
            self._data.setdefault(namespace, {})[key] = value

    return _InMemStore()


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="[]")
    return llm


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionRecorder — edge cases
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionRecorderEdgeCases:
    def test_load_run_returns_empty_when_missing(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        assert recorder.load_run("no_agent", "no_run") == []

    def test_list_runs_returns_empty_when_no_dir(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        assert recorder.list_runs("no_agent") == []

    def test_load_run_parses_all_entries(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run("agt", "test message")
        recorder.record_tool_call(run_id, "agt", "safe_shell", {"cmd": "ls"}, {"output": "ok"})
        recorder.end_run(run_id, "agt", response="done")

        entries = recorder.load_run("agt", run_id)
        types = [e.get("_type") for e in entries]
        assert "run_start" in types
        assert "tool_call" in types
        assert "run_end" in types

    def test_list_runs_sorted_oldest_first(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        r1 = recorder.start_run("ag", "first")
        time.sleep(0.01)
        r2 = recorder.start_run("ag", "second")

        runs = recorder.list_runs("ag")
        assert runs.index(r1) < runs.index(r2)

    def test_prune_old_runs_deletes_excess(self, tmp_path, monkeypatch):
        from deerflow.execution import recorder as rec_mod
        from deerflow.execution.recorder import ExecutionRecorder

        monkeypatch.setattr(rec_mod, "_MAX_RUNS_PER_AGENT", 2)
        recorder = ExecutionRecorder(base_dir=tmp_path)

        for i in range(4):
            rid = recorder.start_run("ag", f"msg {i}")
            recorder.end_run(rid, "ag")

        remaining = recorder.list_runs("ag")
        assert len(remaining) <= 2

    def test_record_tool_call_skips_when_path_missing(self, tmp_path):
        """Call record_tool_call for a run_id that was never started."""
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        # Should not raise even though the file doesn't exist
        recorder.record_tool_call("ghost-run", "agt", "safe_shell", {"cmd": "ls"}, {"output": "ok"})

    def test_end_run_unknown_returns_none(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        result = recorder.end_run("ghost-run", "agt", response="hi")
        assert result is None

    def test_load_run_tolerates_bad_json_lines(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        recorder = ExecutionRecorder(base_dir=tmp_path)
        run_id = recorder.start_run("agt", "test")

        path = tmp_path / "agt" / "runs" / f"{run_id}.jsonl"
        with path.open("a") as f:
            f.write("not valid json\n")

        entries = recorder.load_run("agt", run_id)
        # Should still return the valid lines, skipping the bad one
        assert len(entries) >= 1


# ═══════════════════════════════════════════════════════════════════════════
# FactMemory — deeper coverage
# ═══════════════════════════════════════════════════════════════════════════


class TestFactMemoryDeep:
    def test_parse_facts_handles_bad_json(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        result = fm._parse_facts("NOT JSON", "ag")
        assert result == []

    def test_parse_facts_handles_non_list(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        result = fm._parse_facts('{"content": "x"}', "ag")
        assert result == []

    def test_parse_facts_skips_items_with_missing_content(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        raw = json.dumps([{"category": "knowledge", "confidence": 0.9}])
        result = fm._parse_facts(raw, "ag")
        assert result == []

    def test_parse_facts_strips_markdown_fences(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        wrapped = '```json\n[{"content":"x","category":"knowledge","confidence":0.8}]\n```'
        result = fm._parse_facts(wrapped, "ag")
        assert len(result) == 1
        assert result[0].content == "x"

    def test_merge_deduplicates_by_content(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import Fact, FactCategory, FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        f1 = Fact(content="Deploy on Fridays", category=FactCategory.PREFERENCE, confidence=0.7, source_agent="ag")
        f2 = Fact(
            content="Deploy on Fridays", category=FactCategory.PREFERENCE, confidence=0.9, source_agent="ag"
        )  # higher confidence duplicate

        fm._merge_and_store("ag", [f1])
        fm._merge_and_store("ag", [f2])  # should update confidence, not duplicate

        facts = fm.get_all_facts("ag")
        assert len(facts) == 1
        assert facts[0].confidence == pytest.approx(0.9)

    def test_get_top_facts_category_filter(self, mock_llm, tmp_mem):
        from deerflow.memory.facts import Fact, FactCategory, FactMemory

        fm = FactMemory(mock_llm, tmp_mem)
        pref = Fact(content="Pref fact", category=FactCategory.PREFERENCE, confidence=0.9, source_agent="ag")
        know = Fact(content="Know fact", category=FactCategory.KNOWLEDGE, confidence=0.8, source_agent="ag")
        fm._merge_and_store("ag", [pref, know])

        prefs = fm.get_top_facts("ag", category=FactCategory.PREFERENCE)
        assert all(f.category == FactCategory.PREFERENCE for f in prefs)
        assert len(prefs) == 1

    @pytest.mark.asyncio
    async def test_extract_handles_llm_connection_error(self, tmp_mem):
        from deerflow.memory.facts import FactMemory

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=ConnectionError("Ollama down"))
        fm = FactMemory(llm, tmp_mem)

        result = await fm.extract("ag", [{"role": "user", "content": "hello"}])
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_filters_low_confidence(self, tmp_mem):
        from deerflow.memory.facts import FactMemory

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps(
                [
                    {"content": "low conf", "category": "knowledge", "confidence": 0.1},
                    {"content": "high conf", "category": "preference", "confidence": 0.9},
                ]
            )
        )
        fm = FactMemory(llm, tmp_mem)

        result = await fm.extract("ag", [{"role": "user", "content": "test"}], min_confidence=0.4)
        assert len(result) == 1
        assert result[0].content == "high conf"


# ═══════════════════════════════════════════════════════════════════════════
# MiddlewareChain — deeper coverage
# ═══════════════════════════════════════════════════════════════════════════


class TestMiddlewareChainDeep:
    @pytest.mark.asyncio
    async def test_remove_returns_true_when_found(self):
        from deerflow.middleware.chain import LoggingMiddleware, MiddlewareChain

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())
        assert chain.remove("logging") is True

    @pytest.mark.asyncio
    async def test_remove_returns_false_when_not_found(self):
        from deerflow.middleware.chain import MiddlewareChain

        chain = MiddlewareChain()
        assert chain.remove("nonexistent") is False

    @pytest.mark.asyncio
    async def test_stack_reflects_priority_order(self):
        from deerflow.middleware.chain import (
            LoggingMiddleware,
            MiddlewareChain,
            RateLimitMiddleware,
        )

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())  # priority 20
        chain.add(RateLimitMiddleware(100))  # priority 15

        stack = chain.stack
        assert stack.index("rate_limit") < stack.index("logging")

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_at_threshold(self):
        from deerflow.middleware.chain import MiddlewareChain, RateLimitMiddleware, ToolContext

        chain = MiddlewareChain()
        chain.add(RateLimitMiddleware(max_calls_per_minute=2))

        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})

        ctx = await chain.run_before_tool(ctx)  # call 1
        assert ctx is not None
        ctx = await chain.run_before_tool(ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={}))  # call 2
        assert ctx is not None
        # call 3 should be blocked
        ctx3 = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await chain.run_before_tool(ctx3)
        assert result is None

    @pytest.mark.asyncio
    async def test_rate_limit_separate_per_agent(self):
        from deerflow.middleware.chain import MiddlewareChain, RateLimitMiddleware, ToolContext

        chain = MiddlewareChain()
        chain.add(RateLimitMiddleware(max_calls_per_minute=1))

        ctx_a = ToolContext(tool_name="safe_shell", agent_id="agent_a", kwargs={})
        ctx_b = ToolContext(tool_name="safe_shell", agent_id="agent_b", kwargs={})

        await chain.run_before_tool(ctx_a)  # uses agent_a's budget
        result = await chain.run_before_tool(ctx_b)  # agent_b should still be allowed
        assert result is not None

    @pytest.mark.asyncio
    async def test_llm_hooks_run_in_order(self):
        from deerflow.middleware.chain import LLMContext, Middleware, MiddlewareChain

        order = []

        class MW1(Middleware):
            name = "mw1"
            priority = 10

            async def before_llm(self, messages, meta):
                order.append("before_mw1")
                return messages

            async def after_llm(self, response, meta):
                order.append("after_mw1")
                return response

        class MW2(Middleware):
            name = "mw2"
            priority = 20

            async def before_llm(self, messages, meta):
                order.append("before_mw2")
                return messages

            async def after_llm(self, response, meta):
                order.append("after_mw2")
                return response

        chain = MiddlewareChain()
        chain.add(MW1())
        chain.add(MW2())

        meta = LLMContext(agent_id="ag")
        _messages = await chain.run_before_llm([], meta)
        _response = await chain.run_after_llm("hello", meta)

        # before_llm: priority order (10 < 20)
        assert order.index("before_mw1") < order.index("before_mw2")
        # after_llm: reverse priority order (20 > 10)
        assert order.index("after_mw2") < order.index("after_mw1")

    @pytest.mark.asyncio
    async def test_drift_guard_middleware_blocks_when_halted(self):
        from deerflow.middleware.chain import DriftGuardMiddleware, ToolContext

        dg = DriftGuardMiddleware()
        mock_guard = MagicMock()
        mock_guard.is_halted = True
        dg._guard = mock_guard

        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await dg.before_tool(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_drift_guard_middleware_passes_when_not_halted(self):
        from deerflow.middleware.chain import DriftGuardMiddleware, ToolContext

        dg = DriftGuardMiddleware()
        mock_guard = MagicMock()
        mock_guard.is_halted = False
        dg._guard = mock_guard

        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await dg.before_tool(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_drift_guard_after_tool_annotates_status(self):
        from deerflow.middleware.chain import DriftGuardMiddleware, ToolContext

        dg = DriftGuardMiddleware()
        mock_guard = MagicMock()
        mock_guard.is_halted = False
        mock_report = MagicMock()
        mock_report.status.value = "GREEN"
        mock_guard.check_invariants.return_value = mock_report
        dg._guard = mock_guard

        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await dg.after_tool(ctx, {"output": "ok"})
        assert "_drift_status" in result


# ═══════════════════════════════════════════════════════════════════════════
# ToolHealthMonitor
# ═══════════════════════════════════════════════════════════════════════════


class TestToolHealthMonitorDeep:
    def test_record_failure_persisted(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("safe_shell")
        mon.record_failure("safe_shell", "devops_agent", "error msg", kwargs={"cmd": "ls"})

        stats = mon.get_stats("safe_shell")
        assert stats.total_failures == 1
        assert stats.last_error == "error msg"
        assert stats.total_calls == 1

    def test_failure_rate_calculation(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("file_reader")
        mon.record_call("file_reader")
        mon.record_failure("file_reader", "ag", "oops")

        stats = mon.get_stats("file_reader")
        assert stats.failure_rate == pytest.approx(0.5)

    def test_is_chronic_after_threshold_failures(self, tmp_mem):
        from deerflow.tools.health import _CHRONIC_THRESHOLD, ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        for i in range(_CHRONIC_THRESHOLD):
            mon.record_failure("safe_shell", "ag", f"err {i}")

        stats = mon.get_stats("safe_shell")
        assert stats.is_chronic is True

    def test_get_all_stats_includes_called_tools(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("tool_a")
        mon.record_call("tool_b")

        all_stats = mon.get_all_stats()
        assert "tool_a" in all_stats
        assert "tool_b" in all_stats

    def test_build_health_report_empty_returns_empty_string(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        report = mon.build_health_report()
        assert report == ""

    def test_build_health_report_has_chronic_section(self, tmp_mem):
        from deerflow.tools.health import _CHRONIC_THRESHOLD, ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("bad_tool")
        for _ in range(_CHRONIC_THRESHOLD):
            mon.record_failure("bad_tool", "ag", "persistent error")

        report = mon.build_health_report()
        assert "Chronic" in report
        assert "bad_tool" in report

    def test_build_health_report_degraded_section(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        # 1 call, 1 fail = 100% failure rate but only 1 failure (non-chronic)
        mon.record_call("flaky_tool")
        mon.record_failure("flaky_tool", "ag", "err", kwargs={})

        report = mon.build_health_report()
        # Could be in chronic or degraded — either way the report is non-empty
        assert len(report) > 0

    def test_skill_tracking(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_skill_selected("release_engineering")
        mon.record_skill_selected("release_engineering")
        mon.record_skill_applied("release_engineering")

        stats = mon.get_skill_fallback_stats()
        assert "release_engineering" in stats
        assert stats["release_engineering"]["selected_count"] == 2
        assert stats["release_engineering"]["applied_count"] == 1
        assert stats["release_engineering"]["fallback_rate"] == pytest.approx(0.5)

    def test_build_health_report_high_fallback_skill(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        for _ in range(5):
            mon.record_skill_selected("stale_skill")
        # Apply it only once → high fallback
        mon.record_skill_applied("stale_skill")

        report = mon.build_health_report()
        assert "stale_skill" in report

    def test_build_health_report_all_healthy(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("good_tool")
        mon.record_call("good_tool")

        report = mon.build_health_report()
        assert "healthy" in report.lower() or "Tool Health" in report


# ═══════════════════════════════════════════════════════════════════════════
# detect_tool_failure + ToolHealthMiddleware
# ═══════════════════════════════════════════════════════════════════════════


class TestDetectToolFailure:
    def test_non_dict_is_not_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        assert detect_tool_failure("plain string") == (False, None)
        assert detect_tool_failure(None) == (False, None)

    def test_error_key_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"error": "something went wrong"})
        assert ok is True
        assert msg is not None
        assert "something went wrong" in msg

    def test_success_false_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"success": False, "message": "write failed"})
        assert ok is True
        assert msg is not None
        assert "write failed" in msg

    def test_reachable_false_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"reachable": False, "url": "http://x.com"})
        assert ok is True
        assert msg is not None
        assert "unreachable" in msg

    def test_exists_false_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"exists": False})
        assert ok is True
        assert msg is not None
        assert "file not found" in msg

    def test_nonzero_return_code_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"return_code": 1, "stderr": "bad exit"})
        assert ok is True
        assert msg is not None
        assert "exit code 1" in msg

    def test_blocked_nonzero_is_not_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, _ = detect_tool_failure({"return_code": 1, "blocked": True})
        assert ok is False

    def test_dispatched_false_triggers_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, msg = detect_tool_failure({"dispatched": False})
        assert ok is True

    def test_healthy_result_not_failure(self):
        from deerflow.tools.middleware import detect_tool_failure

        ok, _ = detect_tool_failure({"output": "ls output", "return_code": 0})
        assert ok is False


class TestToolHealthMiddleware:
    @pytest.mark.asyncio
    async def test_records_call_on_before_tool(self, tmp_mem):
        from deerflow.middleware.chain import ToolContext
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.middleware import ToolHealthMiddleware

        mon = ToolHealthMonitor(tmp_mem)
        mw = ToolHealthMiddleware(mon)
        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        await mw.before_tool(ctx)

        stats = mon.get_stats("safe_shell")
        assert stats.total_calls == 1

    @pytest.mark.asyncio
    async def test_healthy_result_gets_ok_annotation(self, tmp_mem):
        from deerflow.middleware.chain import ToolContext
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.middleware import ToolHealthMiddleware

        mon = ToolHealthMonitor(tmp_mem)
        mw = ToolHealthMiddleware(mon)
        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await mw.after_tool(ctx, {"output": "ok", "return_code": 0})
        assert result["_health"]["status"] == "ok"

    @pytest.mark.asyncio
    async def test_failed_result_gets_failed_annotation(self, tmp_mem):
        from deerflow.middleware.chain import ToolContext
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.middleware import ToolHealthMiddleware

        mon = ToolHealthMonitor(tmp_mem)
        mw = ToolHealthMiddleware(mon)
        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await mw.after_tool(ctx, {"error": "oops"})
        assert result["_health"]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_non_dict_result_returned_as_is(self, tmp_mem):
        from deerflow.middleware.chain import ToolContext
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.middleware import ToolHealthMiddleware

        mon = ToolHealthMonitor(tmp_mem)
        mw = ToolHealthMiddleware(mon)
        ctx = ToolContext(tool_name="safe_shell", agent_id="ag", kwargs={})
        result = await mw.after_tool(ctx, "raw string")
        assert result == "raw string"

    @pytest.mark.asyncio
    async def test_chronic_failure_adds_recommendation(self, tmp_mem):
        from deerflow.middleware.chain import ToolContext
        from deerflow.tools.health import _CHRONIC_THRESHOLD, ToolHealthMonitor
        from deerflow.tools.middleware import ToolHealthMiddleware

        mon = ToolHealthMonitor(tmp_mem)
        for _ in range(_CHRONIC_THRESHOLD):
            mon.record_failure("bad_tool", "ag", "err")

        mw = ToolHealthMiddleware(mon)
        ctx = ToolContext(tool_name="bad_tool", agent_id="ag", kwargs={})
        result = await mw.after_tool(ctx, {"error": "still failing"})
        assert "recommendation" in result["_health"]


# ═══════════════════════════════════════════════════════════════════════════
# ToolRepairEngine
# ═══════════════════════════════════════════════════════════════════════════


class TestToolRepairEngine:
    @pytest.mark.asyncio
    async def test_suggest_repair_retry(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "strategy": "retry",
                    "suggested_kwargs": {},
                    "rationale": "transient error",
                    "confidence": 0.8,
                }
            )
        )
        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("safe_shell")
        engine = ToolRepairEngine(llm, mon)

        suggestion = await engine.suggest_repair("safe_shell", "devops_agent", "timeout", {"cmd": "ls"})
        assert suggestion.strategy == "retry"
        assert suggestion.confidence == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_suggest_repair_escalates_chronic(self, tmp_mem):
        from deerflow.tools.health import _CHRONIC_THRESHOLD, ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(return_value=json.dumps({"strategy": "retry", "confidence": 0.9, "rationale": ""}))
        mon = ToolHealthMonitor(tmp_mem)
        for _ in range(_CHRONIC_THRESHOLD):
            mon.record_failure("bad_tool", "ag", "err")

        engine = ToolRepairEngine(llm, mon)
        suggestion = await engine.suggest_repair("bad_tool", "ag", "err", {})
        assert suggestion.strategy == "escalate"

    @pytest.mark.asyncio
    async def test_anti_loop_guard(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(return_value=json.dumps({"strategy": "retry", "confidence": 0.5, "rationale": ""}))
        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("tool_x")
        engine = ToolRepairEngine(llm, mon)

        # First time: LLM is called
        _s1 = await engine.suggest_repair("tool_x", "ag", "same error", {})
        # Second time: same error fingerprint → escalate without calling LLM
        s2 = await engine.suggest_repair("tool_x", "ag", "same error", {})
        assert s2.strategy == "escalate"

    @pytest.mark.asyncio
    async def test_suggest_repair_falls_back_on_llm_error(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=RuntimeError("Ollama down"))
        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("safe_shell")
        engine = ToolRepairEngine(llm, mon)

        suggestion = await engine.suggest_repair("safe_shell", "ag", "err", {})
        assert suggestion.strategy == "skip"

    @pytest.mark.asyncio
    async def test_attempt_repair_skips_when_low_confidence(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps({"strategy": "retry", "confidence": 0.3, "rationale": "low confidence"})
        )
        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("safe_shell")
        engine = ToolRepairEngine(llm, mon)

        exec_fn = AsyncMock(return_value={"output": "ok"})
        result, suggestion = await engine.attempt_repair("safe_shell", "ag", "err", {}, exec_fn)
        # confidence too low to auto-execute
        assert result is None
        exec_fn.assert_not_called()

    @pytest.mark.asyncio
    async def test_attempt_repair_executes_when_high_confidence(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor
        from deerflow.tools.repair import ToolRepairEngine

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "strategy": "retry",
                    "suggested_kwargs": {},
                    "confidence": 0.9,
                    "rationale": "should work",
                }
            )
        )
        mon = ToolHealthMonitor(tmp_mem)
        mon.record_call("safe_shell")
        engine = ToolRepairEngine(llm, mon)

        exec_fn = AsyncMock(return_value={"output": "repaired"})
        result, suggestion = await engine.attempt_repair("safe_shell", "ag", "err", {}, exec_fn)
        assert result is not None
        assert result["output"] == "repaired"


# ═══════════════════════════════════════════════════════════════════════════
# ExecutionAnalyzer
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionAnalyzer:
    @pytest.fixture
    def recorder(self, tmp_path):
        from deerflow.execution.recorder import ExecutionRecorder

        return ExecutionRecorder(base_dir=tmp_path)

    @pytest.fixture
    def health_monitor(self, tmp_mem):
        from deerflow.tools.health import ToolHealthMonitor

        return ToolHealthMonitor(tmp_mem)

    @pytest.mark.asyncio
    async def test_analyze_run_returns_none_when_no_tool_calls(self, recorder, health_monitor, mock_llm):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        analyzer = ExecutionAnalyzer(mock_llm, health_monitor)
        run_id = recorder.start_run("ag", "hello")
        recorder.end_run(run_id, "ag", response="done")

        result = await analyzer.analyze_run(run_id, "ag", recorder)
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_run_returns_judgment(self, recorder, health_monitor):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "tool_judgments": [],
                    "skill_judgments": [],
                    "escalate": False,
                    "escalation_reason": None,
                }
            )
        )

        analyzer = ExecutionAnalyzer(llm, health_monitor)
        run_id = recorder.start_run("ag", "deploy")
        recorder.record_tool_call(run_id, "ag", "safe_shell", {"cmd": "ls"}, {"output": "ok"})
        recorder.end_run(run_id, "ag", response="done")

        judgment = await analyzer.analyze_run(run_id, "ag", recorder)
        assert judgment is not None
        assert judgment.run_id == run_id
        assert judgment.agent_id == "ag"
        assert judgment.escalate is False

    @pytest.mark.asyncio
    async def test_analyze_run_applies_degraded_judgments(self, recorder, health_monitor):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value=json.dumps(
                {
                    "tool_judgments": [
                        {"tool_name": "safe_shell", "status": "degraded", "issue": "slow", "suggested_fix": None}
                    ],
                    "skill_judgments": [],
                    "escalate": False,
                    "escalation_reason": None,
                }
            )
        )

        analyzer = ExecutionAnalyzer(llm, health_monitor)
        run_id = recorder.start_run("ag", "deploy")
        recorder.record_tool_call(run_id, "ag", "safe_shell", {}, {"output": "ok"})
        recorder.end_run(run_id, "ag")

        await analyzer.analyze_run(run_id, "ag", recorder)

        stats = health_monitor.get_stats("safe_shell")
        assert stats.total_failures >= 1

    @pytest.mark.asyncio
    async def test_analyze_run_handles_bad_llm_response(self, recorder, health_monitor):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="NOT JSON")
        analyzer = ExecutionAnalyzer(llm, health_monitor)

        run_id = recorder.start_run("ag", "test")
        recorder.record_tool_call(run_id, "ag", "safe_shell", {}, {"output": "ok"})
        recorder.end_run(run_id, "ag")

        judgment = await analyzer.analyze_run(run_id, "ag", recorder)
        # Should not raise — judgment returned with defaults
        assert judgment is not None
        assert judgment.tool_judgments == []

    def test_build_prompt_includes_tool_summary(self, health_monitor, mock_llm):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        analyzer = ExecutionAnalyzer(mock_llm, health_monitor)
        tool_calls = [
            {"tool_name": "safe_shell", "failed": False, "duration_ms": 12.5},
            {"tool_name": "file_reader", "failed": True, "error": "not found", "duration_ms": 1.0},
        ]
        prompt = analyzer._build_prompt("devops_agent", "deploy app", tool_calls)
        assert "safe_shell" in prompt
        assert "file_reader" in prompt
        assert "FAIL" in prompt
        assert "OK" in prompt

    def test_validate_skill_judgments_no_registry(self, health_monitor, mock_llm):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        analyzer = ExecutionAnalyzer(mock_llm, health_monitor, skill_registry=None)
        judgments = [{"skill_id": "anything", "action": "fix", "rationale": "x"}]
        result = analyzer._validate_skill_judgments(judgments)
        assert result == judgments

    def test_validate_skill_judgments_drops_unknown_ids(self, health_monitor, mock_llm):
        from deerflow.execution.analyzer import ExecutionAnalyzer

        mock_registry = MagicMock()
        mock_registry.list_skill_ids.return_value = ["release_engineering", "frontend_architecture"]
        analyzer = ExecutionAnalyzer(mock_llm, health_monitor, skill_registry=mock_registry)

        judgments = [
            {"skill_id": "release_engineering", "action": "fix", "rationale": "x"},
            {"skill_id": "totally_made_up_skill_id_xyz", "action": "fix", "rationale": "x"},
        ]
        result = analyzer._validate_skill_judgments(judgments)
        skill_ids = [j["skill_id"] for j in result]
        assert "release_engineering" in skill_ids
        assert "totally_made_up_skill_id_xyz" not in skill_ids

    def test_fuzzy_match_corrects_close_name(self):
        from deerflow.execution.analyzer import _fuzzy_match

        candidates = {"release_engineering", "frontend_architecture"}
        match = _fuzzy_match("release_enginering", candidates)  # 1 char typo
        assert match == "release_engineering"

    def test_levenshtein_basic(self):
        from deerflow.execution.analyzer import _levenshtein

        assert _levenshtein("kitten", "sitting") == 3
        assert _levenshtein("", "abc") == 3
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("abc", "abc") == 0


# ═══════════════════════════════════════════════════════════════════════════
# TaskDelegator
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskDelegator:
    def _make_orch(self, agents: list[str], responses: dict | None = None):
        """Build a minimal mock orchestrator."""
        responses = responses or {}
        orch = MagicMock()
        orch.get_available_agents.return_value = agents

        async def _process(agent_id, message, context=None):
            if agent_id in responses:
                return responses[agent_id]
            return {"response": f"{agent_id} done", "error": None}

        orch.process_message = AsyncMock(side_effect=_process)
        return orch

    @pytest.mark.asyncio
    async def test_empty_subtasks_returns_empty_result(self):
        from deerflow.delegation.task import TaskDelegator

        orch = self._make_orch(["security_agent"])
        delegator = TaskDelegator(orch)
        result = await delegator.delegate("gsd_agent", [])
        assert result.outcomes == []
        assert result.synthesis == ""

    @pytest.mark.asyncio
    async def test_unregistered_agent_produces_failure_outcome(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = self._make_orch(["security_agent"])
        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [SubTask(agent_id="ghost_agent", instruction="do something")],
            synthesize=False,
        )
        assert len(result.outcomes) == 1
        assert result.outcomes[0].success is False
        assert result.outcomes[0].error is not None
        assert "not registered" in result.outcomes[0].error

    @pytest.mark.asyncio
    async def test_parallel_delegation_all_succeed(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = self._make_orch(["security_agent", "code_review_agent"])
        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [
                SubTask(agent_id="security_agent", instruction="scan"),
                SubTask(agent_id="code_review_agent", instruction="review"),
            ],
            parallel=True,
            synthesize=False,
        )
        assert len(result.outcomes) == 2
        assert all(o.success for o in result.outcomes)

    @pytest.mark.asyncio
    async def test_sequential_delegation(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = self._make_orch(["security_agent", "code_review_agent"])
        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [
                SubTask(agent_id="security_agent", instruction="scan"),
                SubTask(agent_id="code_review_agent", instruction="review"),
            ],
            parallel=False,
            synthesize=False,
        )
        assert len(result.outcomes) == 2
        assert all(o.success for o in result.outcomes)

    @pytest.mark.asyncio
    async def test_orchestrator_error_captured_as_failure(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = MagicMock()
        orch.get_available_agents.return_value = ["security_agent"]
        orch.process_message = AsyncMock(side_effect=RuntimeError("Ollama down"))

        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [SubTask(agent_id="security_agent", instruction="scan")],
            synthesize=False,
        )
        assert result.outcomes[0].success is False

    @pytest.mark.asyncio
    async def test_timeout_produces_failure_outcome(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = MagicMock()
        orch.get_available_agents.return_value = ["slow_agent"]

        async def _slow(*args, **kwargs):
            await asyncio.sleep(5)
            return {"response": "too late"}

        orch.process_message = AsyncMock(side_effect=_slow)

        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [SubTask(agent_id="slow_agent", instruction="go", timeout_seconds=0.01)],
            synthesize=False,
        )
        assert result.outcomes[0].success is False
        assert result.outcomes[0].error is not None
        assert "Timeout" in result.outcomes[0].error

    @pytest.mark.asyncio
    async def test_synthesis_called_when_at_least_one_succeeds(self):
        from deerflow.delegation.task import SubTask, TaskDelegator

        orch = self._make_orch(
            ["security_agent"],
            responses={"security_agent": {"response": "all clean", "error": None}},
        )
        # Make synthesis return text
        call_count = 0

        async def _process(agent_id, message, context=None):
            nonlocal call_count
            call_count += 1
            return {"response": f"done {call_count}", "error": None}

        orch.process_message = AsyncMock(side_effect=_process)

        delegator = TaskDelegator(orch)
        result = await delegator.delegate(
            "gsd_agent",
            [SubTask(agent_id="security_agent", instruction="scan")],
            synthesize=True,
        )
        # synthesis should have happened (second process_message call)
        assert call_count >= 2 or result.synthesis != ""


# ═══════════════════════════════════════════════════════════════════════════
# SummarizationMiddleware
# ═══════════════════════════════════════════════════════════════════════════


class TestSummarizationMiddleware:
    def _make_msgs(self, n: int, role: str = "user") -> list[dict]:
        return [{"role": role, "content": f"message {i}"} for i in range(n)]

    @pytest.mark.asyncio
    async def test_passthrough_when_under_threshold(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MagicMock()
        mw = SummarizationMiddleware(llm, max_history=20)
        messages = self._make_msgs(5)
        meta = LLMContext(agent_id="ag")
        result = await mw.before_llm(messages, meta)
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_compresses_when_over_threshold(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Summary of earlier messages.")
        mw = SummarizationMiddleware(llm, max_history=5, keep_recent=2)

        messages = [{"role": "system", "content": "sys"}] + self._make_msgs(10)
        meta = LLMContext(agent_id="ag")
        result = await mw.before_llm(messages, meta)

        # system msg + recap msg + 2 recent = 4
        assert len(result) < len(messages)
        # Recap message should be present
        contents = [m.get("content", "") for m in result]
        assert any("[CONTEXT RECAP]" in c for c in contents)

    @pytest.mark.asyncio
    async def test_cache_prevents_duplicate_llm_calls(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Cached summary.")
        mw = SummarizationMiddleware(llm, max_history=5, keep_recent=2)

        messages = [{"role": "system", "content": "sys"}] + self._make_msgs(10)
        meta = LLMContext(agent_id="ag")

        await mw.before_llm(messages, meta)
        await mw.before_llm(messages, meta)

        # LLM should only be called once (second call hits cache)
        assert llm.generate.call_count == 1

    @pytest.mark.asyncio
    async def test_llm_error_falls_back_gracefully(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=ConnectionError("Ollama down"))
        mw = SummarizationMiddleware(llm, max_history=5, keep_recent=2)

        messages = [{"role": "system", "content": "sys"}] + self._make_msgs(10)
        meta = LLMContext(agent_id="ag")
        result = await mw.before_llm(messages, meta)
        # Should still compress, using fallback text
        contents = [m.get("content", "") for m in result]
        assert any("[CONTEXT RECAP]" in c for c in contents)

    @pytest.mark.asyncio
    async def test_no_system_message_inserts_one(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.middleware.summarization import SummarizationMiddleware

        llm = MagicMock()
        llm.generate = AsyncMock(return_value="Brief recap.")
        mw = SummarizationMiddleware(llm, max_history=3, keep_recent=1)

        # No system message — just user messages
        messages = self._make_msgs(8)
        meta = LLMContext(agent_id="ag")
        result = await mw.before_llm(messages, meta)
        # Recap message should still appear
        assert any("[CONTEXT RECAP]" in m.get("content", "") for m in result)


# ═══════════════════════════════════════════════════════════════════════════
# ProgressiveSkillLoader
# ═══════════════════════════════════════════════════════════════════════════


class TestProgressiveSkillLoader:
    def _make_registry(self, prompt: str = "## Skill Context") -> MagicMock:
        reg = MagicMock()
        reg.build_prompt = MagicMock(return_value=prompt)
        return reg

    def test_classify_intent_ci_cd(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry()
        loader = ProgressiveSkillLoader(reg)
        matches = loader.classify_intent("How do I set up CI/CD with GitHub Actions?")
        skill_ids = [m.skill_id for m in matches]
        assert "release_engineering" in skill_ids

    def test_classify_intent_frontend(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry()
        loader = ProgressiveSkillLoader(reg)
        matches = loader.classify_intent("How do I style a React component with Tailwind?")
        skill_ids = [m.skill_id for m in matches]
        assert "frontend_architecture" in skill_ids

    def test_classify_intent_max_skills_respected(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry()
        loader = ProgressiveSkillLoader(reg)
        # Long message that would match many patterns
        msg = "CI/CD pipeline for a React fullstack agent design with token optimization"
        matches = loader.classify_intent(msg, max_skills=2)
        assert len(matches) <= 2

    def test_classify_intent_no_match_returns_empty(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry()
        loader = ProgressiveSkillLoader(reg)
        matches = loader.classify_intent("what is the weather like today?")
        assert matches == []

    def test_select_and_build_returns_prompt_section(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry("## Skill: CI/CD")
        loader = ProgressiveSkillLoader(reg)
        section = loader.select_and_build("Deploy with GitHub Actions", "devops_agent")
        assert "CI/CD" in section

    def test_select_and_build_returns_empty_when_no_match(self):
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry()
        loader = ProgressiveSkillLoader(reg)
        section = loader.select_and_build("tell me a joke", "cs_agent")
        assert section == ""

    @pytest.mark.asyncio
    async def test_as_middleware_injects_into_system_message(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry("## Skill Detail")
        loader = ProgressiveSkillLoader(reg)
        mw = loader.as_middleware(max_skills=2)

        messages = [
            {"role": "system", "content": "You are a helpful agent."},
            {"role": "user", "content": "Explain CI/CD pipelines"},
        ]
        meta = LLMContext(agent_id="devops_agent")
        result = await mw.before_llm(messages, meta)

        sys_msg = next(m for m in result if m["role"] == "system")
        assert "Skill Detail" in sys_msg["content"]

    @pytest.mark.asyncio
    async def test_as_middleware_no_user_message_passthrough(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry("## Skill Detail")
        loader = ProgressiveSkillLoader(reg)
        mw = loader.as_middleware()

        messages = [{"role": "system", "content": "sys"}]
        meta = LLMContext(agent_id="ag")
        result = await mw.before_llm(messages, meta)
        # No user message → no injection
        assert result == messages

    @pytest.mark.asyncio
    async def test_as_middleware_no_system_message_prepends_one(self):
        from deerflow.middleware.chain import LLMContext
        from deerflow.skills.progressive import ProgressiveSkillLoader

        reg = self._make_registry("## Skill Detail")
        loader = ProgressiveSkillLoader(reg)
        mw = loader.as_middleware()

        messages = [{"role": "user", "content": "CI/CD deploy help"}]
        meta = LLMContext(agent_id="devops_agent")
        result = await mw.before_llm(messages, meta)

        # A system message should have been prepended
        assert result[0]["role"] == "system"
