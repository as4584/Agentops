"""
Content Pipeline Agents — All LLM calls use local Ollama.
==========================================================
Each agent:
  - Has isolated responsibility
  - Only acts on specific job statuses
  - Uses the shared OllamaClient from backend.llm
  - Logs all actions
  - Is idempotent (safe to re-run)
"""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod

from backend.content.job_store import job_store
from backend.content.video_job import JobStatus, VideoJob
from backend.llm import OllamaClient
from backend.utils import logger


class ContentAgent(ABC):
    """Base class for all content pipeline agents."""

    name: str = "ContentAgent"
    trigger_status: JobStatus | None = None

    def __init__(self, llm: OllamaClient):
        self.llm = llm
        self.store = job_store

    async def run(self) -> list[VideoJob]:
        """Find jobs at trigger_status, process each."""
        if self.trigger_status is None:
            return []

        jobs = self.store.get_by_status(self.trigger_status)
        logger.info(f"[{self.name}] Found {len(jobs)} job(s) at '{self.trigger_status.value}'")

        results: list[VideoJob] = []
        for job in jobs:
            try:
                logger.info(f"[{self.name}] Processing {job.job_id}: {job.topic!r}")
                processed = await self.process(job)
                if processed:
                    results.append(processed)
            except Exception as e:
                self._handle_failure(job, e)

        return results

    async def run_single(self, job_id: str) -> VideoJob | None:
        job = self.store.load(job_id)
        if job is None:
            logger.error(f"[{self.name}] Job {job_id} not found")
            return None
        try:
            return await self.process(job)
        except Exception as e:
            self._handle_failure(job, e)
            return None

    @abstractmethod
    async def process(self, job: VideoJob) -> VideoJob | None: ...

    def _handle_failure(self, job: VideoJob, error: Exception) -> None:
        tb = traceback.format_exc()
        logger.error(f"[{self.name}] Job {job.job_id} FAILED: {error}\n{tb}")
        try:
            self.store.transition_job(
                job.job_id,
                JobStatus.FAILED,
                failure_reason=f"[{self.name}] {error}",
                retry_count=job.retry_count + 1,
            )
        except Exception as save_err:
            logger.error(f"[{self.name}] Could not save failure: {save_err}")
