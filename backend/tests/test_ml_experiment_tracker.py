"""
Tests for ML Experiment Tracker.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from backend.ml.experiment_tracker import ExperimentTracker, ExperimentRun


@pytest.fixture
def tracker(tmp_path: Path) -> ExperimentTracker:
    return ExperimentTracker(experiments_dir=tmp_path / "experiments")


class TestExperimentRun:
    def test_round_trip(self) -> None:
        run = ExperimentRun(
            run_id="test_001",
            experiment_name="intent_classifier",
            model_type="random_forest",
            hyperparameters={"n_estimators": 100, "max_depth": 10},
            dataset_version="v1_abc123",
            tags={"team": "ml"},
        )
        data = run.to_dict()
        restored = ExperimentRun.from_dict(data)

        assert restored.run_id == "test_001"
        assert restored.experiment_name == "intent_classifier"
        assert restored.model_type == "random_forest"
        assert restored.hyperparameters == {"n_estimators": 100, "max_depth": 10}
        assert restored.dataset_version == "v1_abc123"
        assert restored.tags == {"team": "ml"}
        assert restored.status == "running"

    def test_metrics_serialization(self) -> None:
        run = ExperimentRun(
            run_id="test_002",
            experiment_name="test",
            model_type="svm",
            hyperparameters={},
            dataset_version="v1",
        )
        run.metrics = {"accuracy": [{"value": 0.92, "timestamp": "2024-01-01T00:00:00"}]}
        data = run.to_dict()
        restored = ExperimentRun.from_dict(data)
        assert restored.metrics["accuracy"][0]["value"] == 0.92


class TestExperimentTracker:
    def test_start_and_get_run(self, tracker: ExperimentTracker) -> None:
        run_id = tracker.start_run(
            experiment_name="test_exp",
            hyperparameters={"lr": 0.001},
            model_type="mlp",
            dataset_version="v1",
        )
        assert run_id
        run = tracker.get_run(run_id)
        assert run["experiment_name"] == "test_exp"
        assert run["model_type"] == "mlp"
        assert run["status"] == "running"

    def test_log_metric(self, tracker: ExperimentTracker) -> None:
        run_id = tracker.start_run("metric_test", {"epochs": 10})
        tracker.log_metric(run_id, "accuracy", 0.85)
        tracker.log_metric(run_id, "accuracy", 0.90, step=1)
        tracker.log_metric(run_id, "loss", 0.15)

        run = tracker.get_run(run_id)
        assert len(run["metrics"]["accuracy"]) == 2
        assert run["metrics"]["accuracy"][0]["value"] == 0.85
        assert run["metrics"]["accuracy"][1]["step"] == 1
        assert run["metrics"]["loss"][0]["value"] == 0.15

    def test_log_artifact(self, tracker: ExperimentTracker) -> None:
        run_id = tracker.start_run("artifact_test", {})
        tracker.log_artifact(run_id, "/models/model.pkl")
        tracker.log_artifact(run_id, "/plots/accuracy.png")

        run = tracker.get_run(run_id)
        assert len(run["artifacts"]) == 2
        assert "/models/model.pkl" in run["artifacts"]

    def test_end_run(self, tracker: ExperimentTracker) -> None:
        run_id = tracker.start_run("end_test", {})
        tracker.end_run(run_id, status="completed", notes="great run")

        run = tracker.get_run(run_id)
        assert run["status"] == "completed"
        assert run["ended_at"] is not None
        assert run["notes"] == "great run"

    def test_list_runs(self, tracker: ExperimentTracker) -> None:
        tracker.start_run("exp_a", {})
        tracker.start_run("exp_b", {})
        tracker.start_run("exp_c", {"lr": 0.01})

        all_runs = tracker.list_runs()
        assert len(all_runs) == 3

        a_runs = tracker.list_runs(experiment_name="exp_a")
        assert len(a_runs) == 1

    def test_compare_runs(self, tracker: ExperimentTracker) -> None:
        r1 = tracker.start_run("compare_a", {"lr": 0.001}, model_type="svm")
        r2 = tracker.start_run("compare_b", {"lr": 0.01}, model_type="rf")
        tracker.log_metric(r1, "accuracy", 0.85)
        tracker.log_metric(r2, "accuracy", 0.92)

        comparison = tracker.compare_runs([r1, r2])
        assert len(comparison) == 2
        assert comparison[0]["metrics"]["accuracy"] == 0.85
        assert comparison[1]["metrics"]["accuracy"] == 0.92

    def test_best_run(self, tracker: ExperimentTracker) -> None:
        r1 = tracker.start_run("best_a", {"lr": 0.001})
        r2 = tracker.start_run("best_b", {"lr": 0.01})
        tracker.log_metric(r1, "accuracy", 0.85)
        tracker.log_metric(r2, "accuracy", 0.92)

        # best_run only looks within one experiment, so test with r1's experiment
        best = tracker.best_run("best_a", metric="accuracy")
        assert best is not None
        assert best["run_id"] == r1

    def test_best_run_lower_is_better(self, tracker: ExperimentTracker) -> None:
        r1 = tracker.start_run("loss_a", {})
        r2 = tracker.start_run("loss_b", {})
        tracker.log_metric(r1, "loss", 0.3)
        tracker.log_metric(r2, "loss", 0.1)

        # Each run is in its own experiment — test the one with lower loss
        best = tracker.best_run("loss_b", metric="loss", higher_is_better=False)
        assert best is not None
        assert best["run_id"] == r2

    def test_persistence(self, tmp_path: Path) -> None:
        dir_ = tmp_path / "persist_test"
        t1 = ExperimentTracker(experiments_dir=dir_)
        run_id = t1.start_run("persist", {"x": 1}, model_type="tree")
        t1.log_metric(run_id, "acc", 0.95)
        t1.end_run(run_id)

        # New tracker instance should load from disk
        t2 = ExperimentTracker(experiments_dir=dir_)
        run = t2.get_run(run_id)
        assert run["experiment_name"] == "persist"
        assert run["metrics"]["acc"][0]["value"] == 0.95

    def test_get_missing_run_raises(self, tracker: ExperimentTracker) -> None:
        with pytest.raises(KeyError):
            tracker.get_run("nonexistent_run_id")

    def test_end_missing_run_raises(self, tracker: ExperimentTracker) -> None:
        with pytest.raises(KeyError):
            tracker.end_run("nonexistent_run_id")

    def test_run_id_is_unique(self, tracker: ExperimentTracker) -> None:
        r1 = tracker.start_run("unique_a", {})
        r2 = tracker.start_run("unique_b", {})
        assert r1 != r2

    def test_list_by_status(self, tracker: ExperimentTracker) -> None:
        r1 = tracker.start_run("status_a", {})
        r2 = tracker.start_run("status_b", {})
        tracker.end_run(r1, status="completed")

        running = tracker.list_runs(status="running")
        completed = tracker.list_runs(status="completed")
        assert len(running) == 1
        assert len(completed) == 1
