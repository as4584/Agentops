from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents import ALL_AGENT_DEFINITIONS
from backend.scheduler import scheduler as job_scheduler

router = APIRouter(prefix="/scheduler", tags=["scheduler"])


class CronJobCreate(BaseModel):
    job_id: str = Field(..., min_length=1)
    agent_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)
    schedule_type: Literal["cron", "interval"]
    cron_expr: str | None = None
    interval_seconds: int | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class CronJobResponse(BaseModel):
    job_id: str
    agent_id: str
    message: str
    schedule_type: str
    next_run_time: str | None
    status: Literal["active", "paused", "missed"]


def _valid_agent_ids() -> set[str]:
    ids = set(ALL_AGENT_DEFINITIONS.keys())
    ids.add("knowledge_agent")
    return ids


def _infer_schedule_type(trigger_text: str) -> str:
    lowered = trigger_text.lower()
    if "cron" in lowered:
        return "cron"
    if "interval" in lowered:
        return "interval"
    return "unknown"


def _to_response(job_data: dict[str, Any]) -> CronJobResponse:
    schedule_type = _infer_schedule_type(str(job_data.get("trigger", "")))
    status = str(job_data.get("status", "active"))
    if status not in {"active", "paused", "missed"}:
        status = "active"

    return CronJobResponse(
        job_id=str(job_data.get("job_id", "")),
        agent_id=str(job_data.get("agent_id", "")),
        message=str(job_data.get("message", "")),
        schedule_type=schedule_type,
        next_run_time=job_data.get("next_run_time"),
        status=status,  # type: ignore[arg-type]
    )


@router.get("/jobs")
async def list_jobs() -> list[CronJobResponse]:
    jobs = job_scheduler.list_jobs()
    return [_to_response(job) for job in jobs]


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> CronJobResponse:
    try:
        job = job_scheduler.get_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.post("/jobs")
async def create_job(payload: CronJobCreate) -> CronJobResponse:
    if payload.agent_id not in _valid_agent_ids():
        raise HTTPException(status_code=404, detail="Unknown agent_id")

    if payload.schedule_type == "cron":
        if not payload.cron_expr:
            raise HTTPException(status_code=422, detail="cron_expr is required for cron schedule_type")
        try:
            from apscheduler.triggers.cron import CronTrigger

            CronTrigger.from_crontab(payload.cron_expr)  # type: ignore[no-untyped-call]
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Invalid cron expression: {exc}")

        job = job_scheduler.add_cron_job(
            job_id=payload.job_id,
            agent_id=payload.agent_id,
            message=payload.message,
            cron_expr=payload.cron_expr,
            context=payload.context,
        )
        return _to_response(job)

    if payload.interval_seconds is None or payload.interval_seconds <= 0:
        raise HTTPException(status_code=422, detail="interval_seconds must be > 0 for interval schedule_type")

    job = job_scheduler.add_interval_job(
        job_id=payload.job_id,
        agent_id=payload.agent_id,
        message=payload.message,
        seconds=payload.interval_seconds,
        context=payload.context,
    )
    return _to_response(job)


@router.patch("/jobs/{job_id}/pause")
async def pause_job(job_id: str) -> CronJobResponse:
    try:
        job = job_scheduler.pause_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.patch("/jobs/{job_id}/resume")
async def resume_job(job_id: str) -> CronJobResponse:
    try:
        job = job_scheduler.resume_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    return _to_response(job)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str) -> dict[str, str]:
    try:
        job_scheduler.remove_job(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": "deleted"}
