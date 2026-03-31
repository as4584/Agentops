"""
Content Pipeline — Orchestrates all content agents in sequence.
===============================================================
Jack Craig Method pipeline:

  TrendResearcher → [human greenlight] → ScriptWriterAgent → VoiceAgent
  → AvatarVideoAgent → CaptionAgent → QAAgent → PublisherAgent

Each agent only processes jobs at its trigger status.
Human approvals pause the pipeline between TrendResearcher and ScriptWriter.
"""

from __future__ import annotations

from backend.content.analytics_agent import AnalyticsAgent
from backend.content.avatar_video_agent import AvatarVideoAgent
from backend.content.base_agent import ContentAgent
from backend.content.caption_agent import CaptionAgent
from backend.content.idea_intake_agent import IdeaIntakeAgent
from backend.content.job_store import job_store
from backend.content.publisher_agent import PublisherAgent
from backend.content.qa_agent import QAAgent
from backend.content.script_writer_agent import ScriptWriterAgent
from backend.content.trend_researcher import TrendResearcher
from backend.content.video_job import JobStatus, VideoJob
from backend.content.voice_agent import VoiceAgent
from backend.llm import OllamaClient
from backend.utils import logger


class ContentPipeline:
    """Linear pipeline with state transitions + scheduled triggers."""

    def __init__(self, llm: OllamaClient):
        self.llm = llm
        # TrendResearcher runs first and creates IDEA_PENDING jobs.
        # Pipeline pauses there for human greenlight.
        # ScriptWriterAgent picks up IDEA_APPROVED jobs.
        self.researchers: list[ContentAgent] = [
            TrendResearcher(llm),
        ]
        self.agents: list[ContentAgent] = [
            IdeaIntakeAgent(llm),  # legacy manual-note intake
            ScriptWriterAgent(llm),  # trigger: IDEA_APPROVED
            VoiceAgent(llm),
            AvatarVideoAgent(llm),
            CaptionAgent(llm),
            QAAgent(llm),
            PublisherAgent(llm),
        ]
        self.analytics = AnalyticsAgent(llm)

    async def run_research(self) -> list[VideoJob]:
        """Step 1: Generate idea pitches and park them at IDEA_PENDING."""
        logger.info("--- Running TrendResearcher ---")
        results: list[VideoJob] = []
        for researcher in self.researchers:
            try:
                jobs = await researcher.run()
                results.extend(jobs)
            except Exception as e:
                logger.error(f"{researcher.name} FAILED: {e}")
        logger.info(f"TrendResearcher: {len(results)} ideas pending greenlight")
        return results

    async def run_full(self) -> dict[str, int]:
        """Run the complete pipeline once."""
        logger.info("=" * 60)
        logger.info("CONTENT PIPELINE RUN STARTED")
        logger.info("=" * 60)

        results: dict[str, int] = {}
        for agent in self.agents:
            logger.info(f"--- Running {agent.name} ---")
            try:
                processed = await agent.run()
                results[agent.name] = len(processed)
            except Exception as e:
                logger.error(f"{agent.name} FAILED: {e}")
                results[agent.name] = 0

        logger.info(f"PIPELINE COMPLETE: {results}")
        return results

    async def run_agent(self, name: str) -> list:
        if name == "TrendResearcher":
            return await self.researchers[0].run()
        for agent in self.agents:
            if agent.name == name:
                return await agent.run()
        if name == "AnalyticsAgent":
            return await self.analytics.run()
        raise ValueError(f"Unknown agent: {name}")

    async def run_weekly_analytics(self) -> list:
        return await self.analytics.run()

    # ── Idea approval gate ────────────────────────────────────────────────────

    def approve_idea(self, job_id: str) -> VideoJob:
        """Greenlight an IDEA_PENDING job → IDEA_APPROVED (ScriptWriter picks it up)."""
        logger.info(f"[Pipeline] Approving idea {job_id}")
        return job_store.transition_job(job_id, JobStatus.IDEA_APPROVED)

    def reject_idea(self, job_id: str, reason: str = "") -> VideoJob:
        """Reject an idea — moves to FAILED with reason."""
        logger.info(f"[Pipeline] Rejecting idea {job_id}: {reason}")
        return job_store.transition_job(job_id, JobStatus.FAILED, failure_reason=f"Idea rejected: {reason}")

    def get_pending_ideas(self) -> list[VideoJob]:
        """Return all jobs awaiting human greenlight."""
        return job_store.get_by_status(JobStatus.IDEA_PENDING)

    def approve_job(self, job_id: str) -> VideoJob:
        """QA-approved job → APPROVED (ready for scheduling)."""
        return job_store.transition_job(job_id, JobStatus.APPROVED)

    def reject_job(self, job_id: str, reason: str = "") -> VideoJob:
        return job_store.transition_job(job_id, JobStatus.FAILED, failure_reason=f"Rejected: {reason}")

    def retry_job(self, job_id: str, restart_from: JobStatus) -> VideoJob:
        return job_store.transition_job(job_id, restart_from)

    def get_status_summary(self) -> dict[str, int]:
        all_jobs = job_store.list_all()
        summary = {}
        for status in JobStatus:
            count = sum(1 for j in all_jobs if j.status == status)
            if count:
                summary[status.value] = count
        return summary
