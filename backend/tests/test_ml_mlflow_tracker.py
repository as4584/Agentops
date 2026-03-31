"""Tests for MLflow Tracker."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ml.mlflow_tracker import MLflowTracker


@pytest.fixture
def tracker(tmp_path: Path) -> MLflowTracker:
    return MLflowTracker(tracking_uri=str(tmp_path / "mlruns"), experiment_name="test")


class TestMLflowTracker:
    def test_start_run_context_manager(self, tracker: MLflowTracker) -> None:
        with tracker.start_run("test_run", params={"model": "llama3"}) as run_id:
            assert run_id
            assert isinstance(run_id, str)

    def test_log_metrics(self, tracker: MLflowTracker) -> None:
        with tracker.start_run("metrics_run") as run_id:
            tracker.log_metrics(run_id, {"accuracy": 0.95, "latency_ms": 200.0})

    def test_log_llm_call(self, tracker: MLflowTracker) -> None:
        with tracker.start_run("llm_run") as run_id:
            tracker.log_llm_call(
                run_id,
                model="llama3.2",
                prompt="test prompt",
                response="test response",
                temperature=0.7,
                latency_ms=150.0,
                tokens_in=50,
                tokens_out=100,
                cost_usd=0.001,
                eval_score=0.9,
                pass_fail=True,
                task_type="classification",
            )

    def test_log_artifact(self, tracker: MLflowTracker, tmp_path: Path) -> None:
        artifact = tmp_path / "test_artifact.txt"
        artifact.write_text("test data")
        with tracker.start_run("artifact_run") as run_id:
            tracker.log_artifact(run_id, str(artifact))

    def test_search_runs_empty(self, tracker: MLflowTracker) -> None:
        results = tracker.search_runs()
        assert isinstance(results, list)

    def test_start_run_with_tags(self, tracker: MLflowTracker) -> None:
        with tracker.start_run("tagged_run", tags={"env": "test"}) as run_id:
            assert run_id

    def test_get_best_run_none(self, tracker: MLflowTracker) -> None:
        result = tracker.get_best_run(metric="eval_score")
        assert result is None

    def test_exception_in_run(self, tracker: MLflowTracker) -> None:
        with pytest.raises(ValueError):
            with tracker.start_run("error_run"):
                raise ValueError("intentional error")

    def test_log_metrics_unknown_run(self, tracker: MLflowTracker) -> None:
        # Should not raise
        tracker.log_metrics("nonexistent_run_id", {"x": 1.0})

    def test_log_llm_call_unknown_run(self, tracker: MLflowTracker) -> None:
        tracker.log_llm_call("nonexistent", model="x", prompt="y")
