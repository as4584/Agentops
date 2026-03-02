"""
ScriptWriterAgent — Converts draft topics into short-form video scripts.
========================================================================
Uses local Ollama LLM. No cloud dependency.

Script format (mandatory):
  1. Hook (1-2 sec)
  2. Problem
  3. Framework (max 3 steps)
  4. Example
  5. CTA

Guardrails: max 60 sec / ~150 words, 8th grade level, one idea, no fluff.
"""

from __future__ import annotations

from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.utils import logger


SYSTEM_PROMPT = """\
You are a world-class short-form video scriptwriter.

You write scripts for 30-60 second vertical videos (Reels, TikTok, Shorts).

MANDATORY FORMAT:
---
HOOK: [1-2 second attention grabber — question, bold claim, or pattern interrupt]
PROBLEM: [Relatable pain point — 1-2 sentences]
FRAMEWORK: [Max 3 actionable steps — numbered]
EXAMPLE: [Quick concrete example — 1-2 sentences]
CTA: [Clear call to action — follow, save, comment]
---

RULES:
- Maximum 150 words total (≈60 seconds spoken)
- 8th grade reading level
- ONE idea per script — no tangents
- No filler words ("basically", "actually", "you know")
- Write in spoken conversational tone
- Each line should be spoken aloud naturally
- Start the hook with something that stops the scroll

Return ONLY the script in the format above. No preamble."""


class ScriptWriterAgent(ContentAgent):
    name = "ScriptWriterAgent"
    trigger_status = JobStatus.DRAFT

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] Generating script for: {job.topic!r}")

        prompt = (
            f"Write a short-form video script about:\n\n"
            f"Topic: {job.topic}\n"
            f"Content pillar: {job.content_pillar or 'general'}\n\n"
            f"Remember: max 150 words, one idea only."
        )

        script = await self.llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
            max_tokens=500,
        )

        # Extract hook
        hook = ""
        for line in script.splitlines():
            if line.strip().upper().startswith("HOOK:"):
                hook = line.split(":", 1)[1].strip()
                break

        # Check word count
        word_count = len(script.split())
        if word_count > 200:
            logger.warning(f"[{self.name}] Script is {word_count} words — trimming")
            script = await self._trim_script(script)

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.GENERATED,
            script=script,
            hook=hook,
        )

        logger.info(f"[{self.name}] Script: {len(script.split())} words, hook={hook[:50]!r}")
        return updated

    async def _trim_script(self, script: str) -> str:
        """Ask LLM to trim an overlong script."""
        result = await self.llm.chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"This script is too long. Trim it to under 150 words "
                        f"while keeping the same format and core message:\n\n{script}"
                    ),
                },
            ],
            temperature=0.5,
            max_tokens=400,
        )
        return result
