"""
TrendResearcher — Niche trend analysis + video idea pitch generation.
======================================================================
Jack Craig Method: Step 1 — "Don't invent, improve."

Process:
  1. Pull niche + any notes from content_notes/
  2. Use LLM to generate 5 video idea pitches, each with a conflict angle
  3. Create VideoJob records in IDEA_PENDING status
  4. Wait for human greenlight (/api/ideas/{id}/approve or /api/ideas/{id}/reject)

No cloud dependency — uses local Ollama.
"""

from __future__ import annotations

import os
from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

NOTES_DIR = MEMORY_DIR / "content_notes"
IDEAS_TARGET = 5

# Jack Craig scoring criteria baked into the prompt
RESEARCH_SYSTEM_PROMPT = """\
You are a viral short-form video strategist using the Jack Craig Method.

Rules you follow:
1. NEVER invent from scratch — improve on what's already working
2. Every idea MUST have a conflict/stakes angle (money, status, identity, time)
3. Every idea must have a hook that stops the scroll in under 3 seconds
4. Think about what question the viewer can't leave unanswered
5. The best ideas come from comment sections — what are viewers ASKING for?

For each idea, output EXACTLY this format and nothing else:

---IDEA---
TITLE: [Compelling video title / hook — max 10 words]
NICHE: [gaming|ai_tools|money|productivity|tech|business]
PILLAR: [same as niche]
CONFLICT: [One-sentence description of the core conflict/tension]
HOOK: [First 1-2 spoken sentences — must stop the scroll]
PITCH: [2-3 sentence pitch explaining the full arc: what's the before, the conflict, and the payoff]
WHY_NOW: [Why will this perform well THIS week specifically]
---END---"""


class TrendResearcher(ContentAgent):
    """Generates 5 idea pitches in IDEA_PENDING status for human review."""

    name = "TrendResearcher"
    trigger_status = None  # Runs on schedule, creates new jobs

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        return None  # Not a per-job agent

    async def run(self) -> list[VideoJob]:
        logger.info(f"[{self.name}] Starting trend research run...")

        niche = os.getenv("CONTENT_NICHE", "gaming")
        notes = self._pull_existing_notes()

        # Research ideas via LLM (local Ollama)
        pitches = await self._generate_ideas(niche, notes)
        logger.info(f"[{self.name}] Generated {len(pitches)} idea pitches")

        # Dedup against recent topics
        existing = self.store.get_recent_topics(days=30)
        unique_pitches = [
            p for p in pitches
            if p.get("title", "").lower().strip() not in existing
        ]

        # Create IDEA_PENDING jobs
        created: list[VideoJob] = []
        for pitch in unique_pitches[:IDEAS_TARGET]:
            job = VideoJob(
                topic=pitch.get("title", ""),
                hook=pitch.get("hook", ""),
                idea_pitch=pitch.get("pitch", ""),
                niche=pitch.get("niche", niche),
                content_pillar=pitch.get("pillar", niche),
                trend_data={
                    "why_now": pitch.get("why_now", ""),
                    "conflict": pitch.get("conflict", ""),
                    "niche": pitch.get("niche", niche),
                },
                source="trend_researcher",
                status=JobStatus.IDEA_PENDING,
            )
            self.store.save(job)
            created.append(job)
            logger.info(
                f"[{self.name}] IDEA_PENDING {job.job_id}: {job.topic!r}"
            )

        logger.info(
            f"[{self.name}] Created {len(created)} ideas awaiting human greenlight"
        )
        self._log_idea_table(created)
        return created

    async def _generate_ideas(
        self, niche: str, notes: list[str]
    ) -> list[dict]:
        """Use local LLM to generate idea pitches using Jack Craig's method."""
        notes_str = "\n".join(f"- {n}" for n in notes) if notes else "No recent notes."

        user_prompt = (
            f"Current niche: {niche}\n\n"
            f"Recent content notes / performing topics:\n{notes_str}\n\n"
            f"Generate {IDEAS_TARGET} unique video idea pitches for this niche.\n"
            f"Each idea must have a genuine conflict arc and a scroll-stopping hook.\n"
            f"Think like a viewer first — what would YOU stop scrolling to watch?"
        )

        try:
            raw = await self.llm.chat(
                messages=[
                    {"role": "system", "content": RESEARCH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.9,
                max_tokens=2000,
            )
            return self._parse_ideas(raw)
        except Exception as e:
            logger.error(f"[{self.name}] LLM idea generation failed: {e}")
            return []

    def _parse_ideas(self, raw: str) -> list[dict]:
        """Parse ---IDEA--- blocks from LLM output."""
        ideas = []
        blocks = raw.split("---IDEA---")
        for block in blocks[1:]:  # skip text before first block
            end = block.find("---END---")
            if end == -1:
                end = len(block)
            chunk = block[:end].strip()

            idea: dict = {}
            for line in chunk.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    key = key.strip().lower()
                    val = val.strip()
                    if key in {
                        "title", "niche", "pillar", "conflict",
                        "hook", "pitch", "why_now",
                    }:
                        idea[key] = val
            if idea.get("title"):
                ideas.append(idea)

        return ideas

    def _pull_existing_notes(self) -> list[str]:
        """Pull topics from content_notes/ to avoid repeating recent ideas."""
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        notes = []
        for f in NOTES_DIR.glob("*.txt"):
            for line in f.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    notes.append(line)
        return notes[:20]  # cap to avoid bloating prompt

    def _log_idea_table(self, jobs: list[VideoJob]) -> None:
        """Pretty-print the idea table to logs."""
        if not jobs:
            return
        logger.info("-" * 60)
        logger.info("IDEAS AWAITING GREENLIGHT:")
        for i, job in enumerate(jobs, 1):
            logger.info(f"  [{i}] {job.job_id} | {job.topic!r}")
            logger.info(f"       Pillar: {job.content_pillar} | Niche: {job.niche}")
            logger.info(f"       Pitch: {job.idea_pitch[:80]}...")
        logger.info("Approve via: PATCH /api/content/ideas/{job_id}/approve")
        logger.info("-" * 60)
