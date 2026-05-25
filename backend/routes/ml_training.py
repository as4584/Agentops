"""
ML Training Data Routes — API endpoints for training data and learning lab.
===========================================================================
"""

from __future__ import annotations

import asyncio
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from backend.config import PROJECT_ROOT
from backend.ml.eval_framework import LLMEvalFramework
from backend.ml.experiment_tracker import ExperimentTracker
from backend.ml.learning_lab import LearningLab
from backend.ml.model_registry import ChampionRegistry
from backend.ml.training_job_manager import LexTrainingJobManager, SAFE_BASE_MODELS

router = APIRouter(prefix="/api/ml/training", tags=["ml-training"])

TRAINING_DIR = PROJECT_ROOT / "data" / "training"
_lab = LearningLab()
_tracker = ExperimentTracker()
_eval = LLMEvalFramework()
_job_manager = LexTrainingJobManager()
_registry = ChampionRegistry()
_TERMINAL_JOB_STATUSES = {"completed", "failed", "cancelled"}


@router.get("/files")
async def list_training_files() -> dict[str, Any]:
    """List all JSONL training files with stats."""
    files = []
    total_lines = 0

    if TRAINING_DIR.exists():
        for f in sorted(TRAINING_DIR.glob("*.jsonl")):
            if not f.is_file():
                continue
            line_count = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
            files.append(
                {
                    "name": f.name,
                    "size_bytes": f.stat().st_size,
                    "line_count": line_count,
                }
            )
            total_lines += line_count

    return {
        "files": files,
        "total_files": len(files),
        "total_lines": total_lines,
    }


# ── Learning Lab Endpoints ───────────────────────────────


class GoldenTaskRequest(BaseModel):
    task_id: str
    user_message: str
    expected_agent: str
    expected_tools: list[str] = []
    difficulty: str = "medium"
    boundary: str = ""


class StartTrainingJobRequest(BaseModel):
    mode: str = Field(pattern="^(prep-only|sft|dpo|export|native)$")
    base_model: str = SAFE_BASE_MODELS[0]
    epochs: int = Field(default=3, ge=1, le=20)
    learning_rate: float = Field(default=2e-4, gt=0.0, le=0.01)
    batch_size: int = Field(default=1, ge=1, le=16)
    grad_accum: int = Field(default=8, ge=1, le=128)
    max_seq_len: int = Field(default=4096, ge=256, le=16384)
    lora_rank: int = Field(default=64, ge=4, le=512)
    lora_alpha: int = Field(default=16, ge=4, le=512)
    training_files: list[str] = Field(default_factory=list)
    dpo_files: list[str] = Field(default_factory=list)
    source_artifact: str | None = None
    ollama_model: str = Field(default="lex", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._:-]+$")
    max_per_cat: int = Field(default=20, ge=1, le=100)
    deploy_to_ollama: bool = True

    @model_validator(mode="after")
    def _validate_mode_dependencies(self) -> "StartTrainingJobRequest":
        if self.mode in {"prep-only", "sft", "native"} and not self.training_files:
            raise ValueError("training_files must be set for this mode")
        if self.mode == "dpo":
            if not self.dpo_files:
                raise ValueError("dpo_files must be set for dpo mode")
            if not self.source_artifact:
                raise ValueError("source_artifact is required for dpo mode")
        if self.mode == "export" and not self.source_artifact:
            raise ValueError("source_artifact is required for export mode")
        return self


@router.get("/lab/health")
async def lab_health() -> dict[str, Any]:
    """Get ML learning lab health report."""
    report = _lab.health_report()
    return asdict(report)


@router.get("/lab/summary")
async def lab_summary() -> dict[str, Any]:
    """Get training data summary statistics."""
    stats = _lab.training_data_summary()
    return asdict(stats)


@router.get("/lab/golden-tasks")
async def list_golden_tasks() -> dict[str, Any]:
    """List all golden evaluation tasks."""
    tasks = _lab.list_golden_tasks()
    return {"tasks": tasks, "count": len(tasks)}


@router.post("/lab/golden-tasks")
async def add_golden_task(req: GoldenTaskRequest) -> dict[str, Any]:
    """Add a canonical evaluation task to the golden set."""
    task = _lab.add_golden_task(
        task_id=req.task_id,
        user_message=req.user_message,
        expected_agent=req.expected_agent,
        expected_tools=req.expected_tools,
        difficulty=req.difficulty,
        boundary=req.boundary,
    )
    return {"ok": True, "task": task}


@router.get("/lab/boundaries")
async def boundary_coverage() -> dict[str, Any]:
    """Show training example counts per agent boundary pair."""
    coverage = _lab.boundary_coverage()
    return {"boundaries": coverage, "total_boundaries": len(coverage)}


@router.get("/readiness")
async def training_readiness() -> dict[str, Any]:
    """Report local training prerequisites and hardware readiness."""
    return _job_manager.readiness()


@router.get("/datasets")
async def dataset_catalog() -> dict[str, Any]:
    """List curated training and DPO datasets available for selection."""
    datasets = _job_manager.list_datasets()
    return {
        "training": datasets["training"],
        "dpo": datasets["dpo"],
        "training_count": len(datasets["training"]),
        "dpo_count": len(datasets["dpo"]),
    }


@router.get("/artifacts")
async def artifact_catalog() -> dict[str, Any]:
    """List available local model artifacts suitable for DPO/export jobs."""
    artifacts = _job_manager.list_artifacts()
    return {"artifacts": artifacts, "count": len(artifacts)}


@router.get("/champion")
async def champion_status() -> dict[str, Any]:
    """Return the currently active promoted router model."""
    return _registry.current()


@router.get("/jobs")
async def list_jobs(limit: int = 20) -> dict[str, Any]:
    """List recent Lex training jobs for the operator cockpit."""
    jobs = _job_manager.list_jobs(limit=limit)
    return {"jobs": jobs, "count": len(jobs)}


@router.post("/jobs")
async def start_job(req: StartTrainingJobRequest) -> dict[str, Any]:
    """Launch a validated local Lex training job."""
    try:
        job = _job_manager.start_job(
            mode=req.mode,  # type: ignore[arg-type]
            base_model=req.base_model,
            epochs=req.epochs,
            learning_rate=req.learning_rate,
            batch_size=req.batch_size,
            grad_accum=req.grad_accum,
            max_seq_len=req.max_seq_len,
            lora_rank=req.lora_rank,
            lora_alpha=req.lora_alpha,
            training_files=req.training_files,
            dpo_files=req.dpo_files,
            source_artifact=req.source_artifact,
            ollama_model=req.ollama_model,
            max_per_cat=req.max_per_cat,
            deploy_to_ollama=req.deploy_to_ollama,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"job": job}


@router.get("/jobs/{job_id}")
async def get_job_detail(job_id: str) -> dict[str, Any]:
    """Fetch the latest lifecycle state for a single training job."""
    try:
        job = _job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"job": job}


@router.get("/jobs/{job_id}/logs")
async def get_job_logs(job_id: str, tail: int = 200) -> dict[str, Any]:
    """Return a recent log tail for the selected training job."""
    try:
        return _job_manager.get_job_logs(job_id, tail=tail)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/jobs/{job_id}/metrics")
async def stream_job_metrics(job_id: str) -> StreamingResponse:
    """Tail training step metrics as SSE until the job reaches a terminal state."""
    try:
        job = _job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    metrics_path = Path(job["output_dir"]) / "training_metrics.jsonl"

    async def event_stream():  # type: ignore[no-untyped-def]
        position = 0
        while True:
            if metrics_path.exists():
                with metrics_path.open(encoding="utf-8", errors="ignore") as handle:
                    handle.seek(position)
                    for line in handle:
                        payload = line.strip()
                        if payload:
                            yield f"data: {payload}\n\n"
                    position = handle.tell()

            latest_job = _job_manager.get_job(job_id)
            file_size = metrics_path.stat().st_size if metrics_path.exists() else 0
            if latest_job["status"] in _TERMINAL_JOB_STATUSES and position >= file_size:
                yield f"event: done\ndata: {json.dumps({'status': latest_job['status']})}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict[str, Any]:
    """Request cancellation for a running local training job."""
    try:
        job = _job_manager.cancel_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"job": job}


@router.post("/jobs/{job_id}/promote")
async def promote_job(job_id: str) -> dict[str, Any]:
    """Promote a completed job's evaluated model to the active router champion."""
    try:
        job = _job_manager.get_job(job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    eval_score = job.get("eval_score")
    eval_n = job.get("eval_n")
    if eval_score is None or not isinstance(eval_n, int) or eval_n <= 0:
        raise HTTPException(status_code=409, detail="Job has no persisted eval score to promote")

    model_name = "lex-v3" if job.get("mode") == "native" else str(job.get("ollama_model") or "")
    if not model_name:
        raise HTTPException(status_code=409, detail="Job does not expose a promotable model name")

    champion = _registry.promote(model_name=model_name, job_id=job_id, eval_score=float(eval_score))
    return {"champion": champion, "job_id": job_id, "model_name": model_name}


@router.get("/workbench")
async def workbench_snapshot() -> dict[str, Any]:
    """Aggregate the operator-facing ML control center state."""
    lab_health_report = asdict(_lab.health_report())
    boundary_counts = _lab.boundary_coverage()
    golden_tasks = _lab.list_golden_tasks()
    golden_difficulty = Counter(task.get("difficulty", "unknown") for task in golden_tasks)
    eval_summary = _eval.get_summary()
    recent_evals = _eval.get_results(limit=8)
    experiments = _tracker.list_runs(experiment_name="lex_finetune")[:6]
    datasets = _job_manager.list_datasets()

    return {
        "readiness": _job_manager.readiness(),
        "artifacts": _job_manager.list_artifacts(),
        "jobs": _job_manager.list_jobs(limit=8),
        "lab_health": lab_health_report,
        "golden_coverage": {
            "total_tasks": len(golden_tasks),
            "by_difficulty": dict(golden_difficulty),
        },
        "boundary_coverage": {
            "total_boundaries": len(boundary_counts),
            "top_boundaries": [
                {"boundary": boundary, "count": count}
                for boundary, count in list(boundary_counts.items())[:6]
            ],
        },
        "dataset_selection_summary": _job_manager.summarize_dataset_selection(
            [entry["name"] for entry in datasets["training"]],
            [entry["name"] for entry in datasets["dpo"]],
        ),
        "dataset_file_snapshot": _job_manager.boundary_snapshot(),
        "eval_summary": {
            "total_cases": eval_summary.get("total", 0),
            "avg_score": eval_summary.get("avg_score", 0.0),
            "pass_rate": eval_summary.get("pass_rate", 0.0),
            "by_dimension": {
                dim: values.get("avg", 0.0)
                for dim, values in eval_summary.get("dimensions", {}).items()
            },
        },
        "recent_evals": recent_evals,
        "recent_experiments": experiments,
        "presets": {
            "modes": [
                {"value": "prep-only", "label": "Prep Only"},
                {"value": "sft", "label": "SFT"},
                {"value": "dpo", "label": "DPO"},
                {"value": "export", "label": "Export"},
                {"value": "native", "label": "Native"},
            ],
            "base_models": SAFE_BASE_MODELS,
        },
    }
