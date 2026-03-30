"""
Tests for ML Pipeline orchestration.
"""

from __future__ import annotations

import pytest
from pathlib import Path
from typing import Any

from backend.ml.pipeline import MLPipeline, PipelineStep, PipelineRun, StepStatus
from backend.ml.experiment_tracker import ExperimentTracker


@pytest.fixture
def tracker(tmp_path: Path) -> ExperimentTracker:
    return ExperimentTracker(experiments_dir=tmp_path / "experiments")


def _step_load_data(context: dict[str, Any]) -> dict[str, Any]:
    return {"samples": 100, "features": 10}


def _step_train(context: dict[str, Any]) -> dict[str, Any]:
    context["metrics"]["accuracy"] = 0.92
    context["metrics"]["f1"] = 0.89
    return {"model_path": str(context["models_dir"] / "model.pkl")}


def _step_evaluate(context: dict[str, Any]) -> dict[str, Any]:
    return {"eval_accuracy": 0.91}


def _step_failing(context: dict[str, Any]) -> None:
    raise ValueError("Training exploded")


async def _async_step(context: dict[str, Any]) -> str:
    return "async_done"


class TestPipelineStep:
    async def test_sync_step_executes(self) -> None:
        step = PipelineStep("load", _step_load_data)
        result = await step.execute({"models_dir": Path("/tmp")})
        assert result.status == StepStatus.COMPLETED
        assert result.output == {"samples": 100, "features": 10}
        assert result.duration_ms > 0

    async def test_async_step_executes(self) -> None:
        step = PipelineStep("async_test", _async_step)
        result = await step.execute({})
        assert result.status == StepStatus.COMPLETED
        assert result.output == "async_done"

    async def test_failing_step(self) -> None:
        step = PipelineStep("fail", _step_failing)
        result = await step.execute({})
        assert result.status == StepStatus.FAILED
        assert "Training exploded" in (result.error or "")


class TestMLPipeline:
    async def test_successful_pipeline(self, tmp_path: Path, tracker: ExperimentTracker) -> None:
        pipeline = MLPipeline("test_pipeline", tracker=tracker, models_dir=tmp_path / "models")
        pipeline.add_step(PipelineStep("load_data", _step_load_data))
        pipeline.add_step(PipelineStep("train", _step_train))
        pipeline.add_step(PipelineStep("evaluate", _step_evaluate))

        result = await pipeline.run(
            hyperparams={"lr": 0.001, "epochs": 50},
            model_type="random_forest",
            dataset_version="v1",
        )

        assert result.status == "completed"
        assert len(result.steps) == 3
        assert all(s.status == StepStatus.COMPLETED for s in result.steps)
        assert result.total_duration_ms > 0
        assert result.run_id  # tracked

        # Verify experiment was recorded
        run = tracker.get_run(result.run_id)
        assert run["status"] == "completed"
        assert run["metrics"]["accuracy"][0]["value"] == 0.92

    async def test_pipeline_with_failure(self, tmp_path: Path) -> None:
        pipeline = MLPipeline("fail_pipeline", models_dir=tmp_path / "models")
        pipeline.add_step(PipelineStep("load", _step_load_data))
        pipeline.add_step(PipelineStep("train", _step_failing))
        pipeline.add_step(PipelineStep("evaluate", _step_evaluate))

        result = await pipeline.run()
        assert result.status == "failed"
        assert result.steps[0].status == StepStatus.COMPLETED
        assert result.steps[1].status == StepStatus.FAILED
        assert result.steps[2].status == StepStatus.SKIPPED

    async def test_pipeline_without_tracker(self, tmp_path: Path) -> None:
        pipeline = MLPipeline("no_tracker", models_dir=tmp_path / "models")
        pipeline.add_step(PipelineStep("load", _step_load_data))

        result = await pipeline.run(hyperparams={"x": 1})
        assert result.status == "completed"
        assert result.run_id == ""

    async def test_pipeline_run_serialization(self, tmp_path: Path) -> None:
        pipeline = MLPipeline("serial_test", models_dir=tmp_path / "models")
        pipeline.add_step(PipelineStep("step1", _step_load_data))

        result = await pipeline.run()
        data = result.to_dict()

        assert data["pipeline_name"] == "serial_test"
        assert data["status"] == "completed"
        assert len(data["steps"]) == 1
        assert data["steps"][0]["name"] == "step1"
        assert data["steps"][0]["status"] == "completed"

    async def test_step_output_passed_via_context(self, tmp_path: Path) -> None:
        outputs: list[Any] = []

        def step_a(ctx: dict[str, Any]) -> str:
            return "hello_from_a"

        def step_b(ctx: dict[str, Any]) -> None:
            outputs.append(ctx.get("step_step_a_output"))

        pipeline = MLPipeline("chain_test", models_dir=tmp_path / "models")
        pipeline.add_step(PipelineStep("step_a", step_a))
        pipeline.add_step(PipelineStep("step_b", step_b))

        await pipeline.run()
        assert outputs == ["hello_from_a"]
