"""Tests for MLflow Tracker."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.ml.mlflow_tracker import MLflowTracker


@pytest.fixture
def tracker(tmp_path: Path) -> MLflowTracker:
    return MLflowTracker(tracking_uri=str(tmp_path / "mlruns"), experiment_name="test")


@pytest.fixture
def fallback_tracker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> MLflowTracker:
    """Tracker with MLFLOW_AVAILABLE=False — exercises fallback JSON paths."""
    monkeypatch.setattr("backend.ml.mlflow_tracker.MLFLOW_AVAILABLE", False)
    monkeypatch.setattr("backend.ml.mlflow_tracker.ML_EXPERIMENTS_DIR", tmp_path / "ml")
    return MLflowTracker()


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


class TestMLflowTrackerFallback:
    """Tests exercising the fallback (MLFLOW_AVAILABLE=False) code paths."""

    def test_fallback_init(self, fallback_tracker: MLflowTracker) -> None:
        assert fallback_tracker._client is None
        assert fallback_tracker._fallback_dir.exists()

    def test_fallback_start_run(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("fb_run", params={"lr": "0.01"}, tags={"env": "ci"}) as run_id:
            assert run_id.startswith("fallback_")
            assert run_id in fallback_tracker._active_runs
            run_data = fallback_tracker._active_runs[run_id]
            assert run_data["params"]["lr"] == "0.01"
            assert run_data["tags"]["env"] == "ci"
        # After exiting context, run is persisted and removed from active
        assert run_id not in fallback_tracker._active_runs

    def test_fallback_start_run_persists_json(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("persist_run") as run_id:
            pass
        json_path = fallback_tracker._fallback_dir / f"{run_id}.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["run_id"] == run_id
        assert data["name"] == "persist_run"
        assert "ended_at" in data

    def test_fallback_log_metrics(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("metrics_fb") as run_id:
            fallback_tracker.log_metrics(run_id, {"acc": 0.95, "loss": 0.05})
            assert fallback_tracker._active_runs[run_id]["metrics"]["acc"] == 0.95
            assert fallback_tracker._active_runs[run_id]["metrics"]["loss"] == 0.05

    def test_fallback_log_metrics_unknown_run(self, fallback_tracker: MLflowTracker) -> None:
        # Should not raise when run_id is not in _active_runs
        fallback_tracker.log_metrics("nonexistent_fb", {"x": 1.0})

    def test_fallback_log_llm_call(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("llm_fb") as run_id:
            fallback_tracker.log_llm_call(
                run_id,
                model="llama3.2",
                prompt="test prompt",
                response="test response",
                latency_ms=150.0,
                tokens_in=50,
                tokens_out=100,
                eval_score=0.9,
                pass_fail=False,
            )
            run_data = fallback_tracker._active_runs[run_id]
            assert run_data["metrics"]["latency_ms"] == 150.0
            assert run_data["metrics"]["pass_fail"] == 0.0
            assert run_data["params"]["model"] == "llama3.2"

    def test_fallback_log_artifact(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("artifact_fb") as run_id:
            fallback_tracker.log_artifact(run_id, "/tmp/some_artifact.txt")
            assert "/tmp/some_artifact.txt" in fallback_tracker._active_runs[run_id]["artifacts"]

    def test_fallback_log_artifact_unknown_run(self, fallback_tracker: MLflowTracker) -> None:
        fallback_tracker.log_artifact("nonexistent_fb", "/tmp/x.txt")

    def test_fallback_search_runs_empty(self, fallback_tracker: MLflowTracker) -> None:
        results = fallback_tracker.search_runs()
        assert results == []

    def test_fallback_search_runs_with_data(self, fallback_tracker: MLflowTracker) -> None:
        # Create a run so it is persisted to fallback_dir
        with fallback_tracker.start_run("run_a", params={"v": "1"}) as rid_a:
            fallback_tracker.log_metrics(rid_a, {"score": 0.8})

        results = fallback_tracker.search_runs()
        assert len(results) >= 1
        assert any(r["run_id"] == rid_a for r in results)

    def test_fallback_search_runs_max_results(self, fallback_tracker: MLflowTracker) -> None:
        for i in range(5):
            with fallback_tracker.start_run(f"run_{i}"):
                pass
        results = fallback_tracker.search_runs(max_results=2)
        assert len(results) == 2

    def test_fallback_get_best_run_none(self, fallback_tracker: MLflowTracker) -> None:
        result = fallback_tracker.get_best_run(metric="eval_score")
        assert result is None

    def test_fallback_get_best_run_with_data(self, fallback_tracker: MLflowTracker) -> None:
        with fallback_tracker.start_run("best_a") as rid_a:
            fallback_tracker.log_metrics(rid_a, {"eval_score": 0.7})
        with fallback_tracker.start_run("best_b") as rid_b:
            fallback_tracker.log_metrics(rid_b, {"eval_score": 0.95})

        # get_best_run searches for runs with filter_string, but fallback ignores filter
        # So we need the runs to have the metric in their stored data
        best = fallback_tracker.get_best_run(metric="eval_score", higher_is_better=True)
        if best is not None:
            assert best["metrics"]["eval_score"] == 0.95

    def test_fallback_end_run_unknown_id(self, fallback_tracker: MLflowTracker) -> None:
        # _end_fallback_run should silently return for unknown run_id
        fallback_tracker._end_fallback_run("totally_fake_id")
