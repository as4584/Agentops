"""
ML Pipeline — Training / evaluation / deployment orchestration.
================================================================
Defines reusable pipeline steps and orchestrates them with full experiment
tracking integration. Each pipeline run produces a tracked experiment.

Usage:
    pipeline = MLPipeline("intent_classifier", tracker=tracker)
    pipeline.add_step(PipelineStep("load_data", load_fn))
    pipeline.add_step(PipelineStep("train", train_fn))
    pipeline.add_step(PipelineStep("evaluate", eval_fn))
    result = await pipeline.run(hyperparams={"lr": 0.001}, dataset_version="v2")
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from backend.config import ML_MODELS_DIR
from backend.utils import logger


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    name: str
    status: StepStatus
    duration_ms: float = 0.0
    output: Any = None
    error: Optional[str] = None


@dataclass
class PipelineStep:
    """A single step in an ML pipeline."""
    name: str
    fn: Union[Callable[..., Any], Callable[..., Awaitable[Any]]]
    description: str = ""
    skip_on_failure: bool = False

    async def execute(self, context: dict[str, Any]) -> StepResult:
        """Execute this step. The function receives the pipeline context dict."""
        start = time.monotonic()
        try:
            import asyncio
            if asyncio.iscoroutinefunction(self.fn):
                output = await self.fn(context)
            else:
                output = self.fn(context)
            elapsed = (time.monotonic() - start) * 1000
            return StepResult(
                name=self.name,
                status=StepStatus.COMPLETED,
                duration_ms=elapsed,
                output=output,
            )
        except Exception as e:
            elapsed = (time.monotonic() - start) * 1000
            return StepResult(
                name=self.name,
                status=StepStatus.FAILED,
                duration_ms=elapsed,
                error=traceback.format_exc(),
            )


@dataclass
class PipelineRun:
    """Complete record of a pipeline execution."""
    pipeline_name: str
    run_id: str = ""
    steps: list[StepResult] = field(default_factory=list)
    status: str = "running"
    started_at: str = ""
    ended_at: str = ""
    total_duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "pipeline_name": self.pipeline_name,
            "run_id": self.run_id,
            "steps": [
                {"name": s.name, "status": s.status.value, "duration_ms": s.duration_ms, "error": s.error}
                for s in self.steps
            ],
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "total_duration_ms": self.total_duration_ms,
        }


class MLPipeline:
    """Orchestrates a sequence of ML steps with experiment tracking."""

    def __init__(
        self,
        name: str,
        tracker: Any = None,
        models_dir: Optional[Path] = None,
    ) -> None:
        self.name = name
        self.tracker = tracker
        self.models_dir = models_dir or ML_MODELS_DIR
        self.models_dir.mkdir(parents=True, exist_ok=True)
        self._steps: list[PipelineStep] = []

    def add_step(self, step: PipelineStep) -> None:
        self._steps.append(step)

    async def run(
        self,
        hyperparams: Optional[dict[str, Any]] = None,
        model_type: str = "",
        dataset_version: str = "",
        tags: Optional[dict[str, str]] = None,
    ) -> PipelineRun:
        """Execute all steps in order. Integrates with ExperimentTracker if available."""
        hyperparams = hyperparams or {}
        run_id = ""

        # Start experiment tracking
        if self.tracker:
            run_id = self.tracker.start_run(
                experiment_name=self.name,
                hyperparameters=hyperparams,
                model_type=model_type,
                dataset_version=dataset_version,
                tags=tags,
            )

        pipeline_run = PipelineRun(
            pipeline_name=self.name,
            run_id=run_id,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        context: dict[str, Any] = {
            "pipeline_name": self.name,
            "run_id": run_id,
            "hyperparams": hyperparams,
            "dataset_version": dataset_version,
            "models_dir": self.models_dir,
            "metrics": {},
            "artifacts": [],
        }

        overall_start = time.monotonic()
        failed = False

        for step in self._steps:
            if failed and not step.skip_on_failure:
                result = StepResult(name=step.name, status=StepStatus.SKIPPED)
                pipeline_run.steps.append(result)
                continue

            logger.info(f"[MLPipeline:{self.name}] Running step: {step.name}")
            result = await step.execute(context)
            pipeline_run.steps.append(result)

            if result.status == StepStatus.FAILED:
                failed = True
                logger.error(f"[MLPipeline:{self.name}] Step failed: {step.name}")

            # Pass step output to next step via context
            if result.output is not None:
                context[f"step_{step.name}_output"] = result.output

        total_ms = (time.monotonic() - overall_start) * 1000
        pipeline_run.total_duration_ms = total_ms
        pipeline_run.ended_at = datetime.now(timezone.utc).isoformat()
        pipeline_run.status = "failed" if failed else "completed"

        # Finalize experiment
        if self.tracker and run_id:
            for metric_name, metric_val in context.get("metrics", {}).items():
                self.tracker.log_metric(run_id, metric_name, metric_val)
            for artifact in context.get("artifacts", []):
                self.tracker.log_artifact(run_id, artifact)
            self.tracker.end_run(run_id, status=pipeline_run.status)

        logger.info(
            f"[MLPipeline:{self.name}] Pipeline {pipeline_run.status} "
            f"in {total_ms:.0f}ms ({len(pipeline_run.steps)} steps)"
        )
        return pipeline_run
