"""
Job Store — File-backed persistence for VideoJob records.
=========================================================
Single source of truth. All agents read/write through here.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

CONTENT_JOBS_DIR = MEMORY_DIR / "content_jobs"


class JobStore:
    """Persist VideoJob records as individual JSON files."""

    def __init__(self, jobs_dir: Optional[Path] = None):
        self._dir = jobs_dir or CONTENT_JOBS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.json"

    def save(self, job: VideoJob) -> None:
        p = self._path(job.job_id)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(indent=2))
        tmp.rename(p)
        logger.info(f"[JobStore] Saved {job.job_id} [{job.status.value}]")

    def load(self, job_id: str) -> Optional[VideoJob]:
        p = self._path(job_id)
        if not p.exists():
            return None
        try:
            return VideoJob.model_validate_json(p.read_text())
        except Exception as e:
            logger.error(f"[JobStore] Failed to load {job_id}: {e}")
            return None

    def delete(self, job_id: str) -> bool:
        p = self._path(job_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def list_all(self) -> list[VideoJob]:
        jobs = []
        for f in sorted(self._dir.glob("*.json")):
            try:
                jobs.append(VideoJob.model_validate_json(f.read_text()))
            except Exception as e:
                logger.warning(f"[JobStore] Corrupt file {f.name}: {e}")
        return jobs

    def get_by_status(self, status: JobStatus) -> list[VideoJob]:
        return [j for j in self.list_all() if j.status == status]

    def get_recent_topics(self, days: int = 30) -> set[str]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return {
            j.topic.lower().strip()
            for j in self.list_all()
            if j.created_at >= cutoff and j.topic
        }

    def transition_job(
        self, job_id: str, new_status: JobStatus, **updates: object
    ) -> VideoJob:
        job = self.load(job_id)
        if job is None:
            raise FileNotFoundError(f"Job {job_id} not found")
        job.transition(new_status)
        for key, value in updates.items():
            if hasattr(job, key):
                setattr(job, key, value)
        self.save(job)
        logger.info(f"[JobStore] {job_id} → {new_status.value}")
        return job


# Module-level singleton
job_store = JobStore()
