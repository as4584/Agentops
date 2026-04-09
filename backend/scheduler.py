from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from apscheduler.job import Job
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import SCHEDULER_DB_PATH
from backend.tasks import task_tracker
from backend.utils import logger

DispatchCallable = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any] | Any]]


_SCHEDULER_INSTANCES: dict[str, AgentopScheduler] = {}


async def _run_scheduled_dispatch(
    scheduler_id: str,
    agent_id: str,
    message: str,
    context: dict[str, Any] | None = None,
) -> None:
    instance = _SCHEDULER_INSTANCES.get(scheduler_id)
    if instance is None:
        logger.warning(f"Scheduler instance missing for id={scheduler_id}; dropping job dispatch")
        return
    await instance.dispatch_job(agent_id=agent_id, message=message, context=context or {})


class AgentopScheduler:
    def __init__(self, db_path: Path) -> None:
        self.scheduler_id = "agentop_main"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=f"sqlite:///{self.db_path}")},
            timezone="UTC",
        )
        self._dispatcher: DispatchCallable | None = None
        _SCHEDULER_INSTANCES[self.scheduler_id] = self

    def set_dispatcher(self, dispatcher: DispatchCallable | None) -> None:
        self._dispatcher = dispatcher

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("Scheduler started", event_type="scheduler_started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler shutdown", event_type="scheduler_shutdown")
        _SCHEDULER_INSTANCES.pop(self.scheduler_id, None)

    async def dispatch_job(self, agent_id: str, message: str, context: dict[str, Any] | None = None) -> None:
        if self._dispatcher is None:
            logger.warning("Scheduler job skipped: dispatcher is not set")
            return

        task_id = task_tracker.create_task(
            agent_id=agent_id,
            action="scheduled_dispatch",
            detail=message,
        )
        task_tracker.emit_activity(
            "task_created",
            {
                "task_id": task_id,
                "agent_id": agent_id,
                "source": "scheduler",
                "action": "scheduled_dispatch",
            },
        )

        task_tracker.start_task(task_id)
        try:
            await self._dispatcher(agent_id, message, context or {})
            task_tracker.complete_task(task_id, detail="Scheduled dispatch completed")
            logger.info(
                "Scheduler dispatch completed",
                event_type="scheduler_dispatch_completed",
                task_id=task_id,
                agent_id=agent_id,
            )
        except Exception as exc:
            logger.error(f"Scheduler dispatch failed for agent={agent_id}: {exc}")
            logger.error(
                "Scheduler dispatch failed",
                event_type="scheduler_dispatch_failed",
                task_id=task_id,
                agent_id=agent_id,
                error=str(exc),
            )
            task_tracker.fail_task(task_id, str(exc))
            raise

    def add_cron_job(
        self,
        job_id: str,
        agent_id: str,
        message: str,
        cron_expr: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        trigger = CronTrigger.from_crontab(cron_expr)  # type: ignore[no-untyped-call]
        self._scheduler.add_job(  # type: ignore[no-untyped-call]
            _run_scheduled_dispatch,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs={
                "scheduler_id": self.scheduler_id,
                "agent_id": agent_id,
                "message": message,
                "context": context or {},
            },
        )
        logger.info(
            "Scheduler cron job added",
            event_type="scheduler_job_created",
            job_id=job_id,
            schedule_type="cron",
            agent_id=agent_id,
        )
        return self.get_job(job_id)

    def add_interval_job(
        self,
        job_id: str,
        agent_id: str,
        message: str,
        seconds: int,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._scheduler.add_job(
            _run_scheduled_dispatch,
            trigger="interval",
            seconds=seconds,
            id=job_id,
            replace_existing=True,
            kwargs={
                "scheduler_id": self.scheduler_id,
                "agent_id": agent_id,
                "message": message,
                "context": context or {},
            },
        )
        logger.info(
            "Scheduler interval job added",
            event_type="scheduler_job_created",
            job_id=job_id,
            schedule_type="interval",
            agent_id=agent_id,
        )
        return self.get_job(job_id)

    def remove_job(self, job_id: str) -> None:
        self._scheduler.remove_job(job_id)
        logger.info("Scheduler job removed", event_type="scheduler_job_deleted", job_id=job_id)

    def pause_job(self, job_id: str) -> dict[str, Any]:
        self._scheduler.pause_job(job_id)
        logger.info("Scheduler job paused", event_type="scheduler_job_paused", job_id=job_id)
        return self.get_job(job_id)

    def resume_job(self, job_id: str) -> dict[str, Any]:
        self._scheduler.resume_job(job_id)
        logger.info("Scheduler job resumed", event_type="scheduler_job_resumed", job_id=job_id)
        return self.get_job(job_id)

    def _serialize_job(self, job: Job | None) -> dict[str, Any]:
        if job is None:
            raise KeyError("Job not found")

        kwargs = job.kwargs or {}
        next_run = job.next_run_time.isoformat() if job.next_run_time else None
        status = "paused" if job.next_run_time is None else "active"

        return {
            "job_id": job.id,
            "agent_id": kwargs.get("agent_id", ""),
            "message": kwargs.get("message", ""),
            "next_run_time": next_run,
            "status": status,
            "trigger": str(job.trigger),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._serialize_job(self._scheduler.get_job(job_id))

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = self._scheduler.get_jobs()
        return [self._serialize_job(job) for job in jobs]


scheduler = AgentopScheduler(SCHEDULER_DB_PATH)
