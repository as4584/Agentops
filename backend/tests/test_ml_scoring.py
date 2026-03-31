"""Tests for Scoring Methods and Golden Tasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ml.scoring import (
    AgentJudgeScorer,
    ExactMatchScorer,
    GoldenTaskRegistry,
    RubricScorer,
)


class TestExactMatchScorer:
    def test_exact_match(self) -> None:
        scorer = ExactMatchScorer()
        result = scorer.score("hello", "hello")
        assert result.score == 1.0
        assert result.passed is True

    def test_case_insensitive(self) -> None:
        scorer = ExactMatchScorer()
        result = scorer.score("Hello", "hello")
        assert result.score == 1.0

    def test_case_sensitive(self) -> None:
        scorer = ExactMatchScorer(case_sensitive=True)
        result = scorer.score("Hello", "hello")
        assert result.score == 0.0

    def test_no_match(self) -> None:
        scorer = ExactMatchScorer()
        result = scorer.score("foo", "bar")
        assert result.score == 0.0
        assert result.passed is False

    def test_whitespace_strip(self) -> None:
        scorer = ExactMatchScorer()
        result = scorer.score("  hello  ", "hello")
        assert result.score == 1.0


class TestRubricScorer:
    def test_all_criteria_met(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {
                    "name": "contains_hello",
                    "description": "Must contain hello",
                    "check_type": "contains",
                    "check_value": "hello",
                },
                {"name": "min_length", "description": "At least 5 chars", "check_type": "min_length", "check_value": 5},
            ]
        )
        result = scorer.score("", "hello world")
        assert result.score == 1.0
        assert result.passed is True

    def test_partial_criteria(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {
                    "name": "has_hello",
                    "description": "Must contain hello",
                    "check_type": "contains",
                    "check_value": "hello",
                    "weight": 1.0,
                },
                {
                    "name": "has_goodbye",
                    "description": "Must contain goodbye",
                    "check_type": "contains",
                    "check_value": "goodbye",
                    "weight": 1.0,
                },
            ]
        )
        result = scorer.score("", "hello there")
        assert result.score == 0.5

    def test_regex_criterion(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {
                    "name": "has_number",
                    "description": "Must contain number",
                    "check_type": "regex",
                    "check_value": r"\d+",
                },
            ]
        )
        result = scorer.score("", "answer is 42")
        assert result.score == 1.0

    def test_not_contains_criterion(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {
                    "name": "no_error",
                    "description": "Must not contain error",
                    "check_type": "not_contains",
                    "check_value": "error",
                },
            ]
        )
        result = scorer.score("", "all good")
        assert result.score == 1.0

    def test_max_length_criterion(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {"name": "max_len", "description": "Max 10 chars", "check_type": "max_length", "check_value": 10},
            ]
        )
        result = scorer.score("", "x" * 20)
        assert result.score == 0.0

    def test_no_criteria(self) -> None:
        scorer = RubricScorer()
        result = scorer.score("", "anything")
        assert result.score == 1.0

    def test_keyword_count(self) -> None:
        scorer = RubricScorer(
            criteria=[
                {
                    "name": "keywords",
                    "description": "Must contain keywords",
                    "check_type": "keyword_count",
                    "check_value": ["python", "fastapi"],
                },
            ]
        )
        result = scorer.score("", "Use Python with FastAPI")
        assert result.score == 1.0


class TestAgentJudgeScorer:
    def test_no_judge_fn(self) -> None:
        scorer = AgentJudgeScorer()
        result = scorer.score("expected", "actual")
        assert result.score == 0.5
        assert result.passed is False

    def test_json_response(self) -> None:
        def mock_judge(prompt: str) -> str:
            return '{"score": 0.9, "reasoning": "Good output"}'

        scorer = AgentJudgeScorer(judge_fn=mock_judge)
        result = scorer.score("expected", "actual")
        assert result.score == 0.9
        assert result.passed is True

    def test_text_response_with_score(self) -> None:
        def mock_judge(prompt: str) -> str:
            return "I would rate this output Score: 8.5 out of 10"

        scorer = AgentJudgeScorer(judge_fn=mock_judge)
        result = scorer.score("expected", "actual")
        assert result.score == 0.85

    def test_unparseable_response(self) -> None:
        def mock_judge(prompt: str) -> str:
            return "This output is pretty good I guess"

        scorer = AgentJudgeScorer(judge_fn=mock_judge)
        result = scorer.score("expected", "actual")
        assert result.score == 0.5

    def test_judge_error(self) -> None:
        def mock_judge(prompt: str) -> str:
            raise RuntimeError("LLM unavailable")

        scorer = AgentJudgeScorer(judge_fn=mock_judge)
        result = scorer.score("expected", "actual")
        assert result.score == 0.0


class TestGoldenTaskRegistry:
    @pytest.fixture
    def registry(self, tmp_path: Path) -> GoldenTaskRegistry:
        return GoldenTaskRegistry(storage_dir=tmp_path / "golden")

    def test_add_and_get(self, registry: GoldenTaskRegistry) -> None:
        task_id = registry.add_task(
            {
                "task_id": "t1",
                "task_type": "classification",
                "description": "Test task",
                "input_prompt": "Classify this",
                "expected_output": "bug_report",
            }
        )
        task = registry.get_task(task_id)
        assert task["task_id"] == "t1"

    def test_list_tasks(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "t1",
                "task_type": "classification",
                "description": "d1",
                "input_prompt": "p1",
                "expected_output": "o1",
            }
        )
        registry.add_task(
            {
                "task_id": "t2",
                "task_type": "extraction",
                "description": "d2",
                "input_prompt": "p2",
                "expected_output": "o2",
            }
        )
        assert len(registry.list_tasks()) == 2
        assert len(registry.list_tasks(task_type="classification")) == 1

    def test_remove_task(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "rm1",
                "task_type": "test",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "o",
            }
        )
        registry.remove_task("rm1")
        with pytest.raises(KeyError):
            registry.get_task("rm1")

    def test_score_against_golden(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "score1",
                "task_type": "test",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "correct answer",
            }
        )
        result = registry.score_against_golden("score1", "correct answer")
        assert result.score == 1.0

    def test_score_with_rubric(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "rubric1",
                "task_type": "test",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "expected",
                "scoring_method": "rubric",
                "rubric_criteria": [
                    {
                        "name": "has_keyword",
                        "description": "Contains hello",
                        "check_type": "contains",
                        "check_value": "hello",
                    },
                ],
            }
        )
        result = registry.score_against_golden("rubric1", "hello world")
        assert result.score == 1.0

    def test_task_not_found(self, registry: GoldenTaskRegistry) -> None:
        with pytest.raises(KeyError):
            registry.get_task("nonexistent")

    def test_list_by_difficulty(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "easy1",
                "task_type": "test",
                "difficulty": "easy",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "o",
            }
        )
        registry.add_task(
            {
                "task_id": "hard1",
                "task_type": "test",
                "difficulty": "hard",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "o",
            }
        )
        assert len(registry.list_tasks(difficulty="easy")) == 1

    def test_list_by_tags(self, registry: GoldenTaskRegistry) -> None:
        registry.add_task(
            {
                "task_id": "tagged1",
                "task_type": "test",
                "tags": ["python", "async"],
                "description": "d",
                "input_prompt": "p",
                "expected_output": "o",
            }
        )
        assert len(registry.list_tasks(tags=["python"])) == 1
        assert len(registry.list_tasks(tags=["java"])) == 0

    def test_persistence(self, tmp_path: Path) -> None:
        r1 = GoldenTaskRegistry(storage_dir=tmp_path / "golden")
        r1.add_task(
            {
                "task_id": "persist1",
                "task_type": "test",
                "description": "d",
                "input_prompt": "p",
                "expected_output": "o",
            }
        )
        r2 = GoldenTaskRegistry(storage_dir=tmp_path / "golden")
        assert r2.get_task("persist1")["task_id"] == "persist1"
