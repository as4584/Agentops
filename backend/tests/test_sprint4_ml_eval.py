"""
Sprint 4 Acceptance Tests — ML Closed Loop and Regression Gating
================================================================
Validates that LearningLab can score routing accuracy against a golden eval
set and that failing below threshold surfaces actionable recommendations.

PR coverage:
  PR1  GoldenEvalReport model and ROUTING_ACCURACY_THRESHOLD constant
  PR2  evaluate_routing() with predictions dict list
  PR3  seed_golden_eval_set() — idempotent canonical task seeding
  PR4  routing_eval_from_file() loads JSONL predictions
  PR5  health_report() includes routing_accuracy + golden_tasks_count
  PR6  CI gate — accuracy below threshold yields non-empty recommendations
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

# ---------------------------------------------------------------------------
# PR1 — GoldenEvalReport + ROUTING_ACCURACY_THRESHOLD
# ---------------------------------------------------------------------------


class TestGoldenEvalReport:
    def test_threshold_constant_value(self) -> None:
        from backend.ml.learning_lab import ROUTING_ACCURACY_THRESHOLD

        assert 0.0 < ROUTING_ACCURACY_THRESHOLD <= 1.0

    def test_golden_eval_report_defaults(self) -> None:
        from backend.ml.learning_lab import GoldenEvalReport

        r = GoldenEvalReport()
        assert r.total_tasks == 0
        assert r.correct == 0
        assert r.routing_accuracy == 0.0
        assert isinstance(r.by_difficulty, dict)
        assert isinstance(r.by_boundary, dict)
        assert isinstance(r.recommendations, list)

    def test_golden_eval_report_perfect_accuracy(self) -> None:
        from backend.ml.learning_lab import GoldenEvalReport

        r = GoldenEvalReport(total_tasks=10, correct=10, routing_accuracy=1.0)
        assert r.routing_accuracy == 1.0
        assert r.correct == r.total_tasks

    def test_golden_eval_report_with_breakdown(self) -> None:
        from backend.ml.learning_lab import GoldenEvalReport

        r = GoldenEvalReport(
            total_tasks=5,
            correct=4,
            routing_accuracy=0.8,
            by_difficulty={"easy": 1.0, "hard": 0.5},
            by_boundary={"monitor_agent<>it_agent": 0.5},
        )
        assert r.by_difficulty["easy"] == 1.0
        assert r.by_boundary["monitor_agent<>it_agent"] == 0.5


# ---------------------------------------------------------------------------
# PR2 — evaluate_routing()
# ---------------------------------------------------------------------------


class TestEvaluateRouting:
    def test_perfect_accuracy(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "t2", "expected_agent": "monitor_agent", "difficulty": "easy"},
        ]
        predictions = [
            {"task_id": "t1", "predicted_agent": "devops_agent"},
            {"task_id": "t2", "predicted_agent": "monitor_agent"},
        ]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert report.total_tasks == 2
        assert report.correct == 2
        assert report.routing_accuracy == 1.0
        assert report.recommendations == []

    def test_partial_accuracy(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "t2", "expected_agent": "monitor_agent", "difficulty": "hard"},
            {"task_id": "t3", "expected_agent": "security_agent", "difficulty": "medium"},
            {"task_id": "t4", "expected_agent": "it_agent", "difficulty": "easy"},
        ]
        predictions = [
            {"task_id": "t1", "predicted_agent": "devops_agent"},  # correct
            {"task_id": "t2", "predicted_agent": "devops_agent"},  # wrong
            {"task_id": "t3", "predicted_agent": "security_agent"},  # correct
            {"task_id": "t4", "predicted_agent": "monitor_agent"},  # wrong
        ]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert report.correct == 2
        assert report.total_tasks == 4
        assert abs(report.routing_accuracy - 0.5) < 0.01

    def test_zero_accuracy_below_threshold_adds_recommendation(self) -> None:
        from backend.ml.learning_lab import ROUTING_ACCURACY_THRESHOLD, LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
        ]
        predictions: list[dict[str, Any]] = []  # no predictions → 0 correct
        report = lab.evaluate_routing(predictions, golden_tasks=golden, threshold=ROUTING_ACCURACY_THRESHOLD)
        assert report.routing_accuracy == 0.0
        assert len(report.recommendations) > 0

    def test_missing_prediction_counts_as_wrong(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "t2", "expected_agent": "monitor_agent", "difficulty": "easy"},
        ]
        predictions = [{"task_id": "t1", "predicted_agent": "devops_agent"}]  # t2 missing
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert report.correct == 1
        assert report.total_tasks == 2

    def test_empty_golden_set_returns_recommendation(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        report = lab.evaluate_routing([], golden_tasks=[])
        assert report.total_tasks == 0
        assert len(report.recommendations) > 0

    def test_by_difficulty_breakdown(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "e1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "h1", "expected_agent": "monitor_agent", "difficulty": "hard"},
            {"task_id": "h2", "expected_agent": "security_agent", "difficulty": "hard"},
        ]
        predictions = [
            {"task_id": "e1", "predicted_agent": "devops_agent"},  # easy correct
            {"task_id": "h1", "predicted_agent": "monitor_agent"},  # hard correct
            {"task_id": "h2", "predicted_agent": "devops_agent"},  # hard wrong
        ]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert report.by_difficulty["easy"] == 1.0
        assert abs(report.by_difficulty["hard"] - 0.5) < 0.01

    def test_by_boundary_breakdown(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [
            {
                "task_id": "b1",
                "expected_agent": "monitor_agent",
                "difficulty": "hard",
                "boundary": "monitor_agent<>it_agent",
            },
            {
                "task_id": "b2",
                "expected_agent": "it_agent",
                "difficulty": "hard",
                "boundary": "monitor_agent<>it_agent",
            },
        ]
        predictions = [
            {"task_id": "b1", "predicted_agent": "monitor_agent"},  # correct
            {"task_id": "b2", "predicted_agent": "monitor_agent"},  # wrong
        ]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert abs(report.by_boundary["monitor_agent<>it_agent"] - 0.5) < 0.01

    def test_accepts_chosen_agent_field_alias(self) -> None:
        """evaluate_routing should accept 'chosen_agent' as alternative to 'predicted_agent'."""
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [{"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"}]
        predictions = [{"task_id": "t1", "chosen_agent": "devops_agent"}]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert report.correct == 1


# ---------------------------------------------------------------------------
# PR3 — seed_golden_eval_set()
# ---------------------------------------------------------------------------


class TestSeedGoldenEvalSet:
    def test_seed_returns_count(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        with patch("backend.ml.learning_lab.PROJECT_ROOT", tmp_path):
            (tmp_path / "data" / "training").mkdir(parents=True, exist_ok=True)
            lab2 = LearningLab()
            lab2._training_dir = tmp_path / "data" / "training"

            # Monkeypatch add_golden_task and list_golden_tasks to use tmp path
            def _list() -> list[dict[str, Any]]:
                p = tmp_path / "data" / "training" / "golden_eval_set.jsonl"
                if not p.exists():
                    return []
                tasks = []
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line:
                        tasks.append(json.loads(line))
                return tasks

            def _add(task_id, user_message, expected_agent, difficulty="medium", boundary="", **kw) -> dict[str, Any]:  # type: ignore[override]
                p = tmp_path / "data" / "training" / "golden_eval_set.jsonl"
                task = {
                    "task_id": task_id,
                    "user_message": user_message,
                    "expected_agent": expected_agent,
                    "difficulty": difficulty,
                    "boundary": boundary,
                }
                with p.open("a") as f:
                    f.write(json.dumps(task) + "\n")
                return task

            lab2.list_golden_tasks = _list  # type: ignore[method-assign]
            lab2.add_golden_task = _add  # type: ignore[method-assign, assignment]

            count = lab2.seed_golden_eval_set()
            assert count > 0

    def test_seed_is_idempotent(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path / "data" / "training"
        lab._training_dir.mkdir(parents=True, exist_ok=True)

        tasks_added: list[dict[str, Any]] = []

        def _list() -> list[dict[str, Any]]:
            return tasks_added

        def _add(task_id, user_message, expected_agent, difficulty="medium", boundary="", **kw) -> dict[str, Any]:  # type: ignore[override]
            task = {"task_id": task_id, "user_message": user_message, "expected_agent": expected_agent}
            tasks_added.append(task)
            return task

        lab.list_golden_tasks = _list  # type: ignore[method-assign]
        lab.add_golden_task = _add  # type: ignore[method-assign, assignment]

        count1 = lab.seed_golden_eval_set()
        count2 = lab.seed_golden_eval_set()
        assert count1 > 0
        assert count2 == 0  # All already present

    def test_seed_includes_redline_tasks(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path / "data" / "training"
        lab._training_dir.mkdir(parents=True, exist_ok=True)

        tasks_added: list[dict[str, Any]] = []

        lab.list_golden_tasks = lambda: tasks_added  # type: ignore[method-assign]

        def _add_redline(
            task_id, user_message, expected_agent, difficulty="medium", boundary="", **kw
        ) -> dict[str, Any]:  # type: ignore[override]
            tasks_added.append({"task_id": task_id, "expected_agent": expected_agent, "difficulty": difficulty})
            return tasks_added[-1]

        lab.add_golden_task = _add_redline  # type: ignore[method-assign, assignment]

        lab.seed_golden_eval_set()
        blocked = [t for t in tasks_added if t.get("expected_agent") == "BLOCKED"]
        assert len(blocked) >= 2

    def test_seed_includes_boundary_tasks(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path / "data" / "training"
        lab._training_dir.mkdir(parents=True, exist_ok=True)

        tasks_added: list[dict[str, Any]] = []

        lab.list_golden_tasks = lambda: tasks_added  # type: ignore[method-assign]

        def _add_boundary(
            task_id, user_message, expected_agent, difficulty="medium", boundary="", **kw
        ) -> dict[str, Any]:  # type: ignore[override]
            task = {
                "task_id": task_id,
                "expected_agent": expected_agent,
                "difficulty": difficulty,
                "boundary": boundary,
            }
            tasks_added.append(task)
            return task

        lab.add_golden_task = _add_boundary  # type: ignore[method-assign, assignment]

        lab.seed_golden_eval_set()
        boundary_tasks = [t for t in tasks_added if t.get("boundary")]
        assert len(boundary_tasks) >= 4


# ---------------------------------------------------------------------------
# PR4 — routing_eval_from_file()
# ---------------------------------------------------------------------------


class TestRoutingEvalFromFile:
    def test_load_predictions_from_jsonl(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path

        predictions_file = tmp_path / "predictions.jsonl"
        lines = [
            {"task_id": "t1", "predicted_agent": "devops_agent"},
            {"task_id": "t2", "predicted_agent": "monitor_agent"},
        ]
        predictions_file.write_text("\n".join(json.dumps(item) for item in lines))

        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "t2", "expected_agent": "monitor_agent", "difficulty": "easy"},
        ]
        lab.list_golden_tasks = lambda: golden  # type: ignore[method-assign]

        report = lab.routing_eval_from_file(predictions_file)
        assert report.routing_accuracy == 1.0
        assert report.correct == 2

    def test_missing_file_returns_recommendation(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path
        report = lab.routing_eval_from_file(tmp_path / "nonexistent.jsonl")
        assert len(report.recommendations) > 0

    def test_no_predictions_file_uses_latest_log(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path

        # Create a live_routing file
        log_file = tmp_path / "live_routing_20260416_120000.jsonl"
        log_file.write_text(json.dumps({"task_id": "t1", "chosen_agent": "devops_agent"}) + "\n")

        golden = [{"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"}]
        lab.list_golden_tasks = lambda: golden  # type: ignore[method-assign]

        report = lab.routing_eval_from_file()
        assert report.routing_accuracy == 1.0

    def test_no_log_files_returns_recommendation(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path  # empty
        report = lab.routing_eval_from_file()
        assert len(report.recommendations) > 0


# ---------------------------------------------------------------------------
# PR5 — health_report() with routing_accuracy
# ---------------------------------------------------------------------------


class TestHealthReportWithAccuracy:
    def test_health_report_has_routing_accuracy_field(self) -> None:
        from backend.ml.learning_lab import LabHealthReport

        r = LabHealthReport(routing_accuracy=0.85)
        assert r.routing_accuracy == 0.85

    def test_health_report_routing_accuracy_default_none(self) -> None:
        from backend.ml.learning_lab import LabHealthReport

        r = LabHealthReport()
        assert r.routing_accuracy is None

    def test_health_report_golden_tasks_count(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path
        lab._dpo_dir = tmp_path
        lab.list_golden_tasks = lambda: [{"task_id": "t1"}, {"task_id": "t2"}]  # type: ignore[method-assign]

        report = lab.health_report()
        assert report.golden_tasks_count == 2

    def test_health_report_no_golden_adds_seed_recommendation(self, tmp_path: Path) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        lab._training_dir = tmp_path
        lab._dpo_dir = tmp_path
        lab.list_golden_tasks = lambda: []  # type: ignore[method-assign]

        report = lab.health_report()
        assert any("seed" in r.lower() or "empty" in r.lower() for r in report.recommendations)


# ---------------------------------------------------------------------------
# PR6 — CI gate — failing accuracy yields non-empty recommendations
# ---------------------------------------------------------------------------


class TestCIAccuracyGate:
    def test_failing_accuracy_produces_recommendation(self) -> None:
        from backend.ml.learning_lab import ROUTING_ACCURACY_THRESHOLD, LearningLab

        lab = LearningLab()
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
            {"task_id": "t2", "expected_agent": "monitor_agent", "difficulty": "easy"},
            {"task_id": "t3", "expected_agent": "security_agent", "difficulty": "easy"},
        ]
        # All wrong
        predictions = [
            {"task_id": "t1", "predicted_agent": "monitor_agent"},
            {"task_id": "t2", "predicted_agent": "security_agent"},
            {"task_id": "t3", "predicted_agent": "devops_agent"},
        ]
        report = lab.evaluate_routing(predictions, golden_tasks=golden, threshold=ROUTING_ACCURACY_THRESHOLD)
        assert report.routing_accuracy < ROUTING_ACCURACY_THRESHOLD
        assert len(report.recommendations) > 0

    def test_passing_accuracy_no_threshold_recommendation(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        # Use a very low threshold to guarantee pass
        golden = [
            {"task_id": "t1", "expected_agent": "devops_agent", "difficulty": "easy"},
        ]
        predictions = [{"task_id": "t1", "predicted_agent": "devops_agent"}]
        report = lab.evaluate_routing(predictions, golden_tasks=golden, threshold=0.1)
        assert report.routing_accuracy >= 0.1
        # Threshold recommendation should not appear
        threshold_recs = [r for r in report.recommendations if "below threshold" in r]
        assert len(threshold_recs) == 0

    def test_accuracy_is_float_between_0_and_1(self) -> None:
        from backend.ml.learning_lab import LearningLab

        lab = LearningLab()
        golden = [{"task_id": f"t{i}", "expected_agent": "devops_agent", "difficulty": "easy"} for i in range(5)]
        predictions = [{"task_id": f"t{i}", "predicted_agent": "devops_agent"} for i in range(3)]
        report = lab.evaluate_routing(predictions, golden_tasks=golden)
        assert 0.0 <= report.routing_accuracy <= 1.0
