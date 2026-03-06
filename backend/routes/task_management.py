from __future__ import annotations

from fastapi import APIRouter, Query

from backend.tasks import task_tracker

router = APIRouter(tags=["task-management"])


@router.get("/tasks")
async def list_tasks(limit: int = Query(default=50, ge=1, le=500)) -> dict:
    return {
        "tasks": task_tracker.get_tasks(limit=limit),
        "stats": task_tracker.get_stats(),
    }
