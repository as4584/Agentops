"""Tests for LLM Eval Framework."""

from __future__ import annotations

import pytest
from pathlib import Path

from backend.ml.eval_framework import (
    LLMEvalFramework,
    EvalCase,
    EvalDimension,
    EvalResult,
)


@pytest.fixture
def framework(tmp_path: Path) -> LLMEvalFramework:
    return LLMEvalFramework(storage_dir=tmp_path / "eval_results")


def _make_case(**overrides) -> EvalCase:
    defaults = {
        "case_id": "test_001",
        "task_type": "general",
        "input_prompt": "What is 2+2?",
        "expected_output": "4",
        "actual_output": "4",
        "model": "llama3.2",
        "latency_ms": 100.0,
        "tokens_in": 10,
        "tokens_out": 5,
    }
    defaults.update(overrides)
    return EvalCase(**defaults)


class TestEvalFramework:
    def test_evaluate_all_dimensions(self, framework: LLMEvalFramework) -> None:
        case = _make_case()
        result = framework.evaluate(case)
        assert result.results
        assert result.overall_score > 0

    def test_tool_selection_correct(self, framework: LLMEvalFramework) -> None:
        case = _make_case(context={"expected_tool": "git_ops", "actual_tool": "git_ops"})
        result = framework.evaluate_tool_selection(case)
        assert result.score == 1.0
        assert result.pass_fail is True

    def test_tool_selection_wrong(self, framework: LLMEvalFramework) -> None:
        case = _make_case(context={"expected_tool": "git_ops", "actual_tool": "file_reader"})
        result = framework.evaluate_tool_selection(case)
        assert result.score == 0.0
        assert result.pass_fail is False

    def test_tool_selection_no_expected(self, framework: LLMEvalFramework) -> None:
        case = _make_case()
        result = framework.evaluate_tool_selection(case)
        assert result.score == 1.0  # skipped

    def test_retrieval_accuracy(self, framework: LLMEvalFramework) -> None:
        case = _make_case(context={
            "expected_docs": ["a.md", "b.md", "c.md"],
            "actual_docs": ["a.md", "b.md"],
        })
        result = framework.evaluate_retrieval(case)
        assert 0.0 < result.score <= 1.0
        assert result.metadata["recall"] == pytest.approx(2 / 3)

    def test_retrieval_no_docs_retrieved(self, framework: LLMEvalFramework) -> None:
        case = _make_case(context={"expected_docs": ["a.md"], "actual_docs": []})
        result = framework.evaluate_retrieval(case)
        assert result.score == 0.0

    def test_correctness_exact_match(self, framework: LLMEvalFramework) -> None:
        case = _make_case(expected_output="hello world", actual_output="hello world")
        result = framework.evaluate_correctness(case)
        assert result.score == 1.0

    def test_correctness_containment(self, framework: LLMEvalFramework) -> None:
        case = _make_case(expected_output="error", actual_output="there was an error in processing")
        result = framework.evaluate_correctness(case)
        assert result.score == 0.8

    def test_correctness_no_match(self, framework: LLMEvalFramework) -> None:
        case = _make_case(expected_output="foo", actual_output="bar")
        result = framework.evaluate_correctness(case)
        assert result.score == 0.0

    def test_constraints_met(self, framework: LLMEvalFramework) -> None:
        case = _make_case(
            actual_output="This is a short response with keyword",
            context={"constraints": {"max_length": 100, "required_keywords": ["keyword"]}},
        )
        result = framework.evaluate_constraints(case)
        assert result.pass_fail is True

    def test_constraints_violated(self, framework: LLMEvalFramework) -> None:
        case = _make_case(
            actual_output="x" * 200,
            context={"constraints": {"max_length": 50}},
        )
        result = framework.evaluate_constraints(case)
        assert result.pass_fail is False

    def test_hallucination_none(self, framework: LLMEvalFramework) -> None:
        case = _make_case(
            actual_output="Python is a programming language",
            context={"known_facts": [{"claim": "Python is a language", "negation": "Python is not a language"}]},
        )
        result = framework.evaluate_hallucination(case)
        assert result.pass_fail is True

    def test_hallucination_detected(self, framework: LLMEvalFramework) -> None:
        case = _make_case(
            actual_output="Python is not a language at all",
            context={"known_facts": [{"claim": "Python is a language", "negation": "Python is not a language"}]},
        )
        result = framework.evaluate_hallucination(case)
        assert result.pass_fail is False

    def test_latency_within_threshold(self, framework: LLMEvalFramework) -> None:
        case = _make_case(latency_ms=500, context={"latency_threshold_ms": 2000})
        result = framework.evaluate_latency(case)
        assert result.pass_fail is True

    def test_latency_exceeded(self, framework: LLMEvalFramework) -> None:
        case = _make_case(latency_ms=5000, context={"latency_threshold_ms": 2000})
        result = framework.evaluate_latency(case)
        assert result.pass_fail is False

    def test_token_efficiency(self, framework: LLMEvalFramework) -> None:
        case = _make_case(tokens_in=100, tokens_out=200, context={"max_tokens": 4096})
        result = framework.evaluate_token_efficiency(case)
        assert result.pass_fail is True
        assert result.score > 0.9

    def test_get_results_empty(self, framework: LLMEvalFramework) -> None:
        results = framework.get_results()
        assert results == []

    def test_get_summary_empty(self, framework: LLMEvalFramework) -> None:
        summary = framework.get_summary()
        assert summary["total"] == 0

    def test_persist_and_retrieve(self, framework: LLMEvalFramework) -> None:
        case = _make_case(case_id="persist_test")
        framework.evaluate(case)
        results = framework.get_results()
        assert len(results) == 1
        assert results[0]["case_id"] == "persist_test"

    def test_eval_case_properties(self) -> None:
        case = _make_case()
        case.results = [
            EvalResult(dimension="test1", score=0.8, pass_fail=True),
            EvalResult(dimension="test2", score=0.6, pass_fail=False),
        ]
        assert case.overall_score == pytest.approx(0.7)
        assert case.passed is False

    def test_specific_dimensions(self, framework: LLMEvalFramework) -> None:
        case = _make_case()
        result = framework.evaluate(case, dimensions=[EvalDimension.LATENCY])
        assert len(result.results) == 1
        assert result.results[0].dimension == EvalDimension.LATENCY
