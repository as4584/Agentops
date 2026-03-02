"""
PublisherAgent — Generates hashtags, captions, schedules posts.
===============================================================
Uses local Ollama LLM for caption + hashtag generation.
Publishing integrations are optional.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from backend.content.base_agent import ContentAgent
from backend.content.video_job import VideoJob, JobStatus
from backend.config import MEMORY_DIR
from backend.utils import logger

PUBLISH_DIR = MEMORY_DIR / "content_publish"
PUBLISH_DIR.mkdir(parents=True, exist_ok=True)


class PublisherAgent(ContentAgent):
    name = "PublisherAgent"
    trigger_status = JobStatus.APPROVED

    async def process(self, job: VideoJob) -> Optional[VideoJob]:
        logger.info(f"[{self.name}] Publishing job {job.job_id}")

        # Generate hashtags via local LLM
        hashtags = await self._generate_hashtags(job.topic, job.content_pillar)

        # Generate caption via local LLM
        caption = await self._generate_caption(job.topic, job.hook)

        # Determine post time
        scheduled_time = self._calculate_post_time()

        # Export publish package
        self._export_package(job, caption, hashtags, scheduled_time)

        updated = self.store.transition_job(
            job.job_id,
            JobStatus.SCHEDULED,
            hashtags=hashtags,
            caption_text=caption,
            scheduled_time=scheduled_time,
        )

        logger.info(f"[{self.name}] {job.job_id} scheduled for {scheduled_time.isoformat()}")
        return updated

    async def _generate_hashtags(self, topic: str, pillar: str) -> list[str]:
        try:
            raw = await self.llm.generate(
                prompt=(
                    f"Generate 15-20 hashtags for a short-form video about: {topic}\n"
                    f"Content pillar: {pillar or 'general'}\n\n"
                    f"Mix broad and niche hashtags. "
                    f"Return them space-separated on one line, each starting with #."
                ),
                system=(
                    "You are a social media hashtag expert. "
                    "Output only hashtags, space-separated, starting with #."
                ),
                temperature=0.7,
                max_tokens=200,
            )
            tags = [t.strip() for t in raw.split() if t.startswith("#")]
            return tags[:20]
        except Exception as e:
            logger.warning(f"[{self.name}] Hashtag generation failed: {e}")
            return ["#shorts", "#viral", "#trending"]

    async def _generate_caption(self, topic: str, hook: str) -> str:
        try:
            raw = await self.llm.generate(
                prompt=(
                    f"Write a short engaging social media caption for a video about: {topic}\n"
                    f"Hook used: {hook}\n\n"
                    f"Under 200 characters. Include a CTA. No hashtags."
                ),
                system="You are a social media copywriter. Output only the caption.",
                temperature=0.7,
                max_tokens=100,
            )
            return raw.strip()
        except Exception as e:
            logger.warning(f"[{self.name}] Caption generation failed: {e}")
            return topic

    def _calculate_post_time(self) -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(hour=12, minute=0, second=0) + timedelta(days=1)

    def _export_package(
        self,
        job: VideoJob,
        caption: str,
        hashtags: list[str],
        scheduled: datetime,
    ) -> None:
        """Export a ready-to-post package with all metadata."""
        package = {
            "job_id": job.job_id,
            "topic": job.topic,
            "caption": caption,
            "hashtags": hashtags,
            "full_post": f"{caption}\n\n{' '.join(hashtags)}",
            "video_path": job.captioned_video_path,
            "platforms": job.platform_targets,
            "scheduled_time": scheduled.isoformat(),
        }
        pkg_path = PUBLISH_DIR / f"{job.job_id}_package.json"
        pkg_path.write_text(json.dumps(package, indent=2))
        logger.info(f"[{self.name}] Package exported: {pkg_path}")
