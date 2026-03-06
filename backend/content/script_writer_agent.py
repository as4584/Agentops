"""
ScriptWriterAgent — Conflict arc scripts + visual prompt frames.
=================================================================
Jack Craig Method: Steps 2-3.

Takes an IDEA_APPROVED job and produces:
  1. Full conflict-arc script (8 beats, ~150 words, ~60 sec)
  2. 8 visual prompt frames — one per arc beat — for AI image/video generation

Script arc (mandatory):
  Hook → Rising Action → Conflict → Comeback →
  Second Rising Action → Second Conflict → Final Comeback → Payoff

Guardrails:
  - Max 60 sec / ~150 words spoken
  - 8th grade reading level
  - ONE arc per script, no tangents
  - Each beat must contain unresolved tension (except Payoff)
  - Swipe-through rate target: 80%+ on Hook
"""

from __future__ import annotations

from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.utils import logger


# ─── System prompts ───────────────────────────────────────────────────────────

SCRIPT_SYSTEM_PROMPT = """\
You are a world-class short-form video scriptwriter using the Jack Craig Conflict Arc Method.

You write scripts for 30-60 second vertical videos (Reels, TikTok, Shorts).

MANDATORY ARC FORMAT — use EXACTLY these section labels:
---
HOOK: [0-3 sec — Bold claim, shocking stat, or question. Stops the scroll. Creates instant stakes.]
RISING_ACTION: [3-8 sec — Relatable "before" state. Viewer nods: "that's me." DO NOT RESOLVE.]
CONFLICT: [8-15 sec — Problem escalates. Make it worse than expected. Viewer thinks: "Oh no..."]
COMEBACK_1: [15-22 sec — Partial resolution only. Win, but leave the door open: "I thought I had it..."]
SECOND_RISING: [22-30 sec — New complication. The problem returns at a higher level. The twist.]
SECOND_CONFLICT: [30-40 sec — Darkest moment. Concrete stakes: number, deadline, consequence.]
FINAL_COMEBACK: [40-50 sec — Real solution revealed. Must feel EARNED, not a shortcut.]
PAYOFF: [50-60 sec — Tangible result + CTA. Show the number. Ask viewer to follow/save/comment.]
---

RULES:
- Maximum 150 words total (≈60 seconds spoken)
- 8th grade reading level
- ONE arc — no sub-plots, no tangents
- NEVER resolve tension early — if tension is gone, viewer is gone
- Write in conversational spoken tone (read aloud naturally)
- No filler words: "basically", "actually", "literally", "you know"
- Each section = 1-3 spoken sentences maximum
- Hook MUST start with something that creates an immediate question or contradiction

Return ONLY the script in the format above. No preamble. No explanation."""


FRAMES_SYSTEM_PROMPT = """\
You are an AI video director generating image prompts for a short-form video.

Given a script with 8 arc beats, generate exactly 8 visual prompt frames.
One frame per beat.

Each prompt must be:
- Highly specific (subject + action + setting + lighting + camera angle + mood)
- Optimized for AI image generation (Midjourney / Stable Diffusion / Kling)
- 1-3 seconds of action when animated
- Visually dynamic — avoid static "person standing" shots
- Emotionally matched to the arc beat (tension in Conflict, relief in Payoff)

FORMAT — output exactly 8 lines, each starting with FRAME_N: where N is 1-8:
FRAME_1: [HOOK visual prompt]
FRAME_2: [RISING_ACTION visual prompt]
FRAME_3: [CONFLICT visual prompt]
FRAME_4: [COMEBACK_1 visual prompt]
FRAME_5: [SECOND_RISING visual prompt]
FRAME_6: [SECOND_CONFLICT visual prompt]
FRAME_7: [FINAL_COMEBACK visual prompt]
FRAME_8: [PAYOFF visual prompt]

No explanations. No extra text. Just the 8 FRAME lines."""


ARC_BEATS = [
    "HOOK",
    "RISING_ACTION",
    "CONFLICT",
    "COMEBACK_1",
    "SECOND_RISING",
    "SECOND_CONFLICT",
    "FINAL_COMEBACK",
    "PAYOFF",
]


# ─── Agent ────────────────────────────────────────────────────────────────────

class ScriptWriterAgent(ContentAgent):
    name = "ScriptWriterAgent"
    trigger_status = JobStatus.IDEA_APPROVED  # previously DRAFT

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] Writing conflict-arc script for: {job.topic!r}")

        context = self._build_context(job)

        # 1. Generate script
        script = await self._generate_script(job.topic, context)

        # 2. Extract hook
        hook = self._extract_section(script, "HOOK")

        # 3. Word count check
        word_count = len(script.split())
        if word_count > 200:
            logger.warning(f"[{self.name}] Script is {word_count} words — trimming")
            script = await self._trim_script(script)

        # 4. Validate all 8 beats are present
        missing = [b for b in ARC_BEATS if b + ":" not in script.upper()]
        if missing:
            logger.warning(f"[{self.name}] Missing beats: {missing} — requesting fix")
            script = await self._fix_missing_beats(script, missing, job.topic)

        # 5. Generate visual prompt frames
        frames = await self._generate_frames(job.topic, script)

        logger.info(
            f"[{self.name}] Script: {len(script.split())} words | "
            f"Frames: {len(frames)} | Hook: {hook[:50]!r}"
        )

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.GENERATED,
            script=script,
            hook=hook,
            prompt_frames=frames,
        )
        return updated

    # ── Script generation ──────────────────────────────────────────────────────

    async def _generate_script(self, topic: str, context: str) -> str:
        user_prompt = (
            f"Write a conflict-arc short-form video script about:\n\n"
            f"Topic: {topic}\n"
            f"{context}\n\n"
            f"Remember: 8 beats, max 150 words total, unresolved tension at every beat except Payoff."
        )
        return await self.llm.chat(
            messages=[
                {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=700,
        )

    # ── Visual frames generation ───────────────────────────────────────────────

    async def _generate_frames(self, topic: str, script: str) -> list[str]:
        """Generate 8 image-gen prompts (one per arc beat)."""
        user_prompt = (
            f"Video topic: {topic}\n\n"
            f"Script:\n{script}\n\n"
            f"Generate 8 visual prompt frames — one per arc beat."
        )
        try:
            raw = await self.llm.chat(
                messages=[
                    {"role": "system", "content": FRAMES_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.75,
                max_tokens=800,
            )
            return self._parse_frames(raw)
        except Exception as e:
            logger.warning(f"[{self.name}] Frame generation failed: {e}")
            return []

    def _parse_frames(self, raw: str) -> list[str]:
        frames = []
        for line in raw.strip().splitlines():
            line = line.strip()
            if line.upper().startswith("FRAME_") and ":" in line:
                prompt = line.partition(":")[2].strip()
                if prompt:
                    frames.append(prompt)
        return frames[:8]

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _build_context(self, job: VideoJob) -> str:
        parts = []
        if job.content_pillar:
            parts.append(f"Content pillar: {job.content_pillar}")
        if job.niche:
            parts.append(f"Niche: {job.niche}")
        if job.idea_pitch:
            parts.append(f"Idea pitch: {job.idea_pitch}")
        if job.trend_data.get("conflict"):
            parts.append(f"Core conflict: {job.trend_data['conflict']}")
        if job.hook:
            parts.append(f"Suggested hook: {job.hook}")
        return "\n".join(parts)

    def _extract_section(self, script: str, section: str) -> str:
        for line in script.splitlines():
            if line.strip().upper().startswith(section + ":"):
                return line.split(":", 1)[1].strip()
        return ""

    async def _trim_script(self, script: str) -> str:
        return await self.llm.chat(
            messages=[
                {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"This script is too long ({len(script.split())} words). "
                        f"Trim it to under 150 words while keeping ALL 8 beats and the same arc:\n\n"
                        f"{script}"
                    ),
                },
            ],
            temperature=0.5,
            max_tokens=600,
        )

    async def _fix_missing_beats(
        self, script: str, missing: list[str], topic: str
    ) -> str:
        """Ask LLM to add missing arc beats."""
        return await self.llm.chat(
            messages=[
                {"role": "system", "content": SCRIPT_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"This script is missing these arc beats: {missing}.\n"
                        f"Topic: {topic}\n"
                        f"Rewrite it with all 8 beats present:\n\n{script}"
                    ),
                },
            ],
            temperature=0.7,
            max_tokens=700,
        )
