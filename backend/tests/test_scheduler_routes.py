from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def add_cron_job(
        self, job_id: str, agent_id: str, message: str, cron_expr: str, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        job = {
            "job_id": job_id,
            "agent_id": agent_id,
            "message": message,
            "next_run_time": "2099-01-01T00:00:00+00:00",
            "status": "active",
            "trigger": f"cron[{cron_expr}]",
            "context": context or {},
        }
        self.jobs[job_id] = job
        return job

    def add_interval_job(
        self, job_id: str, agent_id: str, message: str, seconds: int, context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        job = {
            "job_id": job_id,
            "agent_id": agent_id,
            "message": message,
            "next_run_time": "2099-01-01T00:00:00+00:00",
            "status": "active",
            "trigger": f"interval[{seconds}]",
            "context": context or {},
        }
        self.jobs[job_id] = job
        return job

    def list_jobs(self) -> list[dict[str, Any]]:
        return list(self.jobs.values())

    def get_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        return self.jobs[job_id]

    def remove_job(self, job_id: str) -> None:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        del self.jobs[job_id]

    def pause_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs[job_id]["status"] = "paused"
        self.jobs[job_id]["next_run_time"] = None
        return self.jobs[job_id]

    def resume_job(self, job_id: str) -> dict[str, Any]:
        if job_id not in self.jobs:
            raise KeyError(job_id)
        self.jobs[job_id]["status"] = "active"
        self.jobs[job_id]["next_run_time"] = "2099-01-01T00:00:00+00:00"
        return self.jobs[job_id]


def _client_with_fake_scheduler() -> TestClient:
    from backend.routes import schedule_routes as scheduler_routes

    fake = _FakeScheduler()
    scheduler_routes.job_scheduler = fake  # type: ignore[assignment]

    app = FastAPI()
    app.include_router(scheduler_routes.router)
    return TestClient(app)


def test_create_valid_cron_job_and_list():
    client = _client_with_fake_scheduler()

    create = client.post(
        "/scheduler/jobs",
        json={
            "job_id": "job-1",
            "agent_id": "knowledge_agent",
            "message": "hello",
            "schedule_type": "cron",
            "cron_expr": "*/5 * * * *",
            "context": {},
        },
    )
    assert create.status_code == 200
    body = create.json()
    assert body["job_id"] == "job-1"
    assert body["schedule_type"] == "cron"

    listed = client.get("/scheduler/jobs")
    assert listed.status_code == 200
    jobs = listed.json()
    assert any(job["job_id"] == "job-1" for job in jobs)


def test_create_invalid_cron_returns_422():
    client = _client_with_fake_scheduler()

    create = client.post(
        "/scheduler/jobs",
        json={
            "job_id": "job-invalid",
            "agent_id": "knowledge_agent",
            "message": "hello",
            "schedule_type": "cron",
            "cron_expr": "not a cron",
        },
    )
    assert create.status_code == 422


def test_unknown_agent_returns_404():
    client = _client_with_fake_scheduler()

    create = client.post(
        "/scheduler/jobs",
        json={
            "job_id": "job-unknown-agent",
            "agent_id": "nonexistent_agent",
            "message": "hello",
            "schedule_type": "interval",
            "interval_seconds": 30,
        },
    )
    assert create.status_code == 404


def test_delete_pause_resume_roundtrip():
    client = _client_with_fake_scheduler()

    create = client.post(
        "/scheduler/jobs",
        json={
            "job_id": "job-2",
            "agent_id": "knowledge_agent",
            "message": "hello",
            "schedule_type": "interval",
            "interval_seconds": 60,
        },
    )
    assert create.status_code == 200

    paused = client.patch("/scheduler/jobs/job-2/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    resumed = client.patch("/scheduler/jobs/job-2/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"

    deleted = client.delete("/scheduler/jobs/job-2")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    listed = client.get("/scheduler/jobs")
    assert listed.status_code == 200
    assert all(job["job_id"] != "job-2" for job in listed.json())
