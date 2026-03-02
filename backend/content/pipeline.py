"""
Content Pipeline — Orchestrates all content agents in sequence.
===============================================================
Each agent only processes jobs at its trigger status.
Fully async, uses the shared OllamaClient.
"""

from __future__ import annotations

from backend.llm import OllamaClient
from backend.content.video_job import JobStatus
from backend.content.job_store import job_store
from backend.content.base_agent import ContentAgent
from backend.content.idea_intake_agent import IdeaIntakeAgent
from backend.content.script_writer_agent import ScriptWriterAgent
from backend.content.voice_agent import VoiceAgent
from backend.content.avatar_video_agent import AvatarVideoAgent
from backend.content.caption_agent import CaptionAgent
from backend.content.qa_agent import QAAgent
from backend.content.publisher_agent import PublisherAgent
from backend.content.analytics_agent import AnalyticsAgent
from backend.utils import logger


class ContentPipeline:
    """Linear pipeline with state transitions + scheduled triggers."""

    def __init__(self, llm: OllamaClient):
        self.llm = llm
        self.agents: list[ContentAgent] = [
            IdeaIntakeAgent(llm),
            ScriptWriterAgent(llm),
            VoiceAgent(llm),
            AvatarVideoAgent(llm),
            CaptionAgent(llm),
            QAAgent(llm),
            PublisherAgent(llm),
        ]
        self.analytics = AnalyticsAgent(llm)

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
        for agent in self.agents:
            if agent.name == name:
                return await agent.run()
        if name == "AnalyticsAgent":
            return await self.analytics.run()
        raise ValueError(f"Unknown agent: {name}")

    async def run_weekly_analytics(self) -> list:
        return await self.analytics.run()

    def approve_job(self, job_id: str):
        return job_store.transition_job(job_id, JobStatus.APPROVED)

    def reject_job(self, job_id: str, reason: str = ""):
        return job_store.transition_job(
            job_id, JobStatus.FAILED, failure_reason=f"Rejected: {reason}"
        )

    def retry_job(self, job_id: str, restart_from: JobStatus):
        return job_store.transition_job(job_id, restart_from)

    def get_status_summary(self) -> dict[str, int]:
        all_jobs = job_store.list_all()
        summary = {}
        for status in JobStatus:
            count = sum(1 for j in all_jobs if j.status == status)
            if count:
                summary[status.value] = count
        return summary
