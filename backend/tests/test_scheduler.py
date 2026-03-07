from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_add_list_remove_job(tmp_path: Path):
    from backend.scheduler import AgentopScheduler

    async def run_test() -> None:
        scheduler = AgentopScheduler(db_path=tmp_path / "scheduler.db")
        scheduler.start()
        try:
            scheduler.add_cron_job(
                job_id="cron-job-1",
                agent_id="knowledge_agent",
                message="run cron",
                cron_expr="*/5 * * * *",
            )

            jobs = scheduler.list_jobs()
            assert any(job["job_id"] == "cron-job-1" for job in jobs)

            scheduler.remove_job("cron-job-1")
            jobs_after = scheduler.list_jobs()
            assert not any(job["job_id"] == "cron-job-1" for job in jobs_after)
        finally:
            scheduler.shutdown()

    asyncio.run(run_test())


def test_pause_resume_job(tmp_path: Path):
    from backend.scheduler import AgentopScheduler

    async def run_test() -> None:
        scheduler = AgentopScheduler(db_path=tmp_path / "scheduler.db")
        scheduler.start()
        try:
            scheduler.add_interval_job(
                job_id="interval-job-1",
                agent_id="knowledge_agent",
                message="run interval",
                seconds=60,
            )

            paused = scheduler.pause_job("interval-job-1")
            assert paused["status"] == "paused"

            resumed = scheduler.resume_job("interval-job-1")
            assert resumed["status"] == "active"
        finally:
            scheduler.shutdown()

    asyncio.run(run_test())


def test_dispatch_job_calls_dispatcher(tmp_path: Path):
    from backend.scheduler import AgentopScheduler

    scheduler = AgentopScheduler(db_path=tmp_path / "scheduler.db")

    captured: dict[str, object] = {}

    async def fake_dispatch(agent_id: str, message: str, context: dict[str, object]):
        captured["agent_id"] = agent_id
        captured["message"] = message
        captured["context"] = context
        return {"ok": True}

    scheduler.set_dispatcher(fake_dispatch)

    asyncio.run(
        scheduler.dispatch_job(
            agent_id="knowledge_agent",
            message="scheduled message",
            context={"source": "test"},
        )
    )

    assert captured["agent_id"] == "knowledge_agent"
    assert captured["message"] == "scheduled message"
    assert captured["context"] == {"source": "test"}
