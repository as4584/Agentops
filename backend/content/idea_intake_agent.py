"""
IdeaIntakeAgent — Daily idea sourcing + deduplication.
======================================================
Sources ideas from local notes, external integrations (optional),
and creates draft VideoJob records.

LLM: Used for topic expansion/refinement (local Ollama).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

NOTES_DIR = MEMORY_DIR / "content_notes"
DAILY_TARGET = 5
DEDUP_WINDOW_DAYS = 30


class IdeaIntakeAgent(ContentAgent):
    name = "IdeaIntakeAgent"
    trigger_status = None  # Creates new jobs, not triggered by status

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        return None

    async def run(self) -> list[VideoJob]:
        """Source ideas and create new draft VideoJobs."""
        logger.info(f"[{self.name}] Starting daily idea intake...")

        raw_ideas: list[dict] = []
        raw_ideas.extend(self._pull_notes_folder())

        # Optional: LLM-powered topic expansion
        if len(raw_ideas) < DAILY_TARGET:
            expanded = await self._expand_topics(raw_ideas)
            raw_ideas.extend(expanded)

        logger.info(f"[{self.name}] Sourced {len(raw_ideas)} raw ideas")

        # Dedup
        existing = self.store.get_recent_topics(days=DEDUP_WINDOW_DAYS)
        unique = []
        for idea in raw_ideas:
            topic = idea.get("topic", "").lower().strip()
            if topic and topic not in existing:
                existing.add(topic)
                unique.append(idea)

        logger.info(
            f"[{self.name}] {len(unique)} unique (filtered {len(raw_ideas) - len(unique)})"
        )

        to_create = unique[:DAILY_TARGET]

        created: list[VideoJob] = []
        for idea in to_create:
            job = VideoJob(
                topic=idea.get("topic", ""),
                content_pillar=idea.get("pillar", ""),
                source=idea.get("source", "manual"),
                status=JobStatus.DRAFT,
            )
            self.store.save(job)
            created.append(job)
            logger.info(f"[{self.name}] Created draft {job.job_id}: {job.topic!r}")

        return created

    def _pull_notes_folder(self) -> list[dict]:
        """Pull ideas from local content_notes/*.txt files."""
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        ideas = []
        for f in NOTES_DIR.glob("*.txt"):
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    ideas.append({
                        "topic": line,
                        "pillar": "",
                        "source": "notes",
                    })
            # Archive processed
            archive = NOTES_DIR / "processed"
            archive.mkdir(exist_ok=True)
            f.rename(archive / f.name)

        return ideas

    async def _expand_topics(self, existing: list[dict]) -> list[dict]:
        """Use local LLM to generate additional topic ideas."""
        existing_topics = [i.get("topic", "") for i in existing if i.get("topic")]
        context = ", ".join(existing_topics) if existing_topics else "none yet"

        prompt = (
            f"I create short-form video content. "
            f"Topics I already have: {context}\n\n"
            f"Generate {DAILY_TARGET} NEW unique topic ideas for short viral videos. "
            f"Each should be specific and actionable.\n"
            f"Return one topic per line, no numbering, no bullets."
        )

        try:
            raw = await self.llm.generate(
                prompt=prompt,
                system="You are a content strategist for short-form video. Output only topic ideas, one per line.",
                temperature=0.9,
                max_tokens=500,
            )
            ideas = []
            for line in raw.strip().splitlines():
                line = line.strip().lstrip("-•*0123456789.)")
                if line and len(line) > 5:
                    ideas.append({
                        "topic": line.strip(),
                        "pillar": "",
                        "source": "llm_generated",
                    })
            return ideas
        except Exception as e:
            logger.warning(f"[{self.name}] LLM topic expansion failed: {e}")
            return []
