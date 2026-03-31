"""Tests for Benchmark Suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ml.benchmark import (
    BenchmarkCase,
    BenchmarkResult,
    BenchmarkSuite,
)


@pytest.fixture
def suite(tmp_path: Path) -> BenchmarkSuite:
    return BenchmarkSuite(storage_dir=tmp_path / "bench")


def mock_runner(case: BenchmarkCase) -> BenchmarkResult:
    """Simple mock runner that always passes."""
    return BenchmarkResult(
        case_id=case.case_id,
        suite_id=case.suite_id,
        model="test_model",
        actual_output=case.expected_output or "ok",
        passed=True,
        score=0.9,
        latency_ms=100.0,
    )


def mock_runner_degraded(case: BenchmarkCase) -> BenchmarkResult:
    """Runner that produces worse results for regression testing."""
    return BenchmarkResult(
        case_id=case.case_id,
        suite_id=case.suite_id,
        model="test_model",
        actual_output="wrong",
        passed=False,
        score=0.4,
        latency_ms=5000.0,
    )


CASES = [
    {
        "case_id": "c1",
        "suite_id": "s",
        "task_type": "code",
        "input_prompt": "Write hello world",
        "expected_output": "print('hello')",
        "tags": ["python"],
    },
]


class TestBenchmarkSuite:
    def test_create_suite(self, suite: BenchmarkSuite) -> None:
        sid = suite.create_suite("test_suite", "Test Suite", CASES)
        assert sid == "test_suite"

    def test_get_suite(self, suite: BenchmarkSuite) -> None:
        suite.create_suite("get_test", "Get Test", CASES)
        data = suite.get_suite("get_test")
        assert data["name"] == "Get Test"
        assert len(data["cases"]) == 1

    def test_list_suites(self, suite: BenchmarkSuite) -> None:
        suite.create_suite("s1", "S1", [{"case_id": "c1", "suite_id": "s1", "task_type": "t", "input_prompt": "p"}])
        suite.create_suite("s2", "S2", [{"case_id": "c2", "suite_id": "s2", "task_type": "t", "input_prompt": "p"}])
        assert len(suite.list_suites()) == 2

    def test_run_suite(self, suite: BenchmarkSuite) -> None:
        cases = [
            {"case_id": "c1", "suite_id": "run", "task_type": "code", "input_prompt": "p", "expected_output": "o"},
            {"case_id": "c2", "suite_id": "run", "task_type": "code", "input_prompt": "p2", "expected_output": "o2"},
        ]
        suite.create_suite("run_test", "Run Test", cases)
        report = suite.run_suite("run_test", model="test_model", runner_fn=mock_runner)
        assert report.pass_rate == 1.0
        assert report.avg_score == pytest.approx(0.9)
        assert len(report.results) == 2

    def test_set_baseline(self, suite: BenchmarkSuite) -> None:
        cases = [{"case_id": "c1", "suite_id": "bl", "task_type": "t", "input_prompt": "p"}]
        suite.create_suite("baseline_test", "BL", cases)
        report = suite.run_suite("baseline_test", model="m", runner_fn=mock_runner)
        suite.set_baseline("baseline_test", "m", report)
        baseline = suite.get_baseline("baseline_test", "m")
        assert baseline is not None
        assert baseline.pass_rate == 1.0

    def test_detect_regressions(self, suite: BenchmarkSuite) -> None:
        cases = [{"case_id": "c1", "suite_id": "reg", "task_type": "t", "input_prompt": "p"}]
        suite.create_suite("regression_test", "Reg", cases)
        good_report = suite.run_suite("regression_test", model="m", runner_fn=mock_runner)
        suite.set_baseline("regression_test", "m", good_report)
        bad_report = suite.run_suite("regression_test", model="m", runner_fn=mock_runner_degraded)
        assert len(bad_report.regressions) > 0

    def test_regression_pass_rate_drop(self, suite: BenchmarkSuite) -> None:
        cases = [
            {"case_id": "c1", "suite_id": "pr", "task_type": "t", "input_prompt": "p"},
            {"case_id": "c2", "suite_id": "pr", "task_type": "t", "input_prompt": "p2"},
        ]
        suite.create_suite("passrate_test", "PR", cases)
        good = suite.run_suite("passrate_test", model="m", runner_fn=mock_runner)
        suite.set_baseline("passrate_test", "m", good)
        bad = suite.run_suite("passrate_test", model="m", runner_fn=mock_runner_degraded)
        assert any("Pass rate" in r for r in bad.regressions)

    def test_get_history(self, suite: BenchmarkSuite) -> None:
        cases = [{"case_id": "c1", "suite_id": "hist", "task_type": "t", "input_prompt": "p"}]
        suite.create_suite("history_test", "Hist", cases)
        suite.run_suite("history_test", model="m", runner_fn=mock_runner)
        suite.run_suite("history_test", model="m", runner_fn=mock_runner)
        history = suite.get_history("history_test")
        assert len(history) == 2

    def test_suite_not_found(self, suite: BenchmarkSuite) -> None:
        with pytest.raises(KeyError):
            suite.get_suite("nonexistent")

    def test_create_capability_suite(self, suite: BenchmarkSuite) -> None:
        data = BenchmarkSuite.create_capability_suite()
        assert len(data["cases"]) == 7
        types = {c["task_type"] for c in data["cases"]}
        assert "drafting" in types
        assert "tool_selection" in types

    def test_create_webgen_suite(self, suite: BenchmarkSuite) -> None:
        data = BenchmarkSuite.create_webgen_suite()
        assert len(data["cases"]) == 3

    def test_no_baseline_no_regressions(self, suite: BenchmarkSuite) -> None:
        cases = [{"case_id": "c1", "suite_id": "nb", "task_type": "t", "input_prompt": "p"}]
        suite.create_suite("no_baseline", "NB", cases)
        report = suite.run_suite("no_baseline", model="m", runner_fn=mock_runner)
        assert report.regressions == []
