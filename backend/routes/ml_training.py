"""
ML Training Data Routes — API endpoints for training data and learning lab.
===========================================================================
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from backend.config import PROJECT_ROOT
from backend.ml.learning_lab import LearningLab

router = APIRouter(prefix="/api/ml/training", tags=["ml-training"])

TRAINING_DIR = PROJECT_ROOT / "data" / "training"
_lab = LearningLab()


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
