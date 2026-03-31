"""
PublisherAgent — Captions, hashtags, and smart upload timing.
=============================================================
Jack Craig Method: Upload timing is as important as content quality.

Timing rules:
  1. Minimum 48 hours between any two posts (algorithm stability)
  2. Only post when the LAST video's views/hr has been
     below VIEW_VELOCITY_THRESHOLD for VIEW_VELOCITY_WINDOW_HOURS
     consecutive hours (signals algorithm has finished distributing it)
  3. If a trend is expiring, override to post immediately

Env knobs:
  UPLOAD_INTERVAL_HOURS         (default 48)
  VIEW_VELOCITY_THRESHOLD       (default 100 views/hr)
  VIEW_VELOCITY_WINDOW_HOURS    (default 12)
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from backend.config import MEMORY_DIR
from backend.content.base_agent import ContentAgent
from backend.content.video_job import JobStatus, VideoJob
from backend.utils import logger

PUBLISH_DIR = MEMORY_DIR / "content_publish"
PUBLISH_DIR.mkdir(parents=True, exist_ok=True)


class PublisherAgent(ContentAgent):
    name = "PublisherAgent"
    trigger_status = JobStatus.APPROVED

    async def process(self, job: VideoJob) -> VideoJob | None:
        logger.info(f"[{self.name}] Publishing job {job.job_id}")

        # Generate hashtags via local LLM
        hashtags = await self._generate_hashtags(job.topic, job.content_pillar)

        # Generate caption via local LLM
        caption = await self._generate_caption(job.topic, job.hook)

        # Determine post time (Jack Craig timing rules)
        scheduled_time = self._calculate_post_time(job)

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
                    "You are a social media hashtag expert. Output only hashtags, space-separated, starting with #."
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

    def _calculate_post_time(self, job: VideoJob | None = None) -> datetime:  # noqa: F841
        """
        Jack Craig upload timing rules:
          1. Never post within UPLOAD_INTERVAL_HOURS of the last post
          2. Only post when most-recent video's view velocity <
             VIEW_VELOCITY_THRESHOLD for VIEW_VELOCITY_WINDOW_HOURS+ hours
          3. Align to optimal UTC upload window for target market
        """
        interval_hours = int(os.getenv("UPLOAD_INTERVAL_HOURS", "48"))
        velocity_threshold = int(os.getenv("VIEW_VELOCITY_THRESHOLD", "100"))
        velocity_window = int(os.getenv("VIEW_VELOCITY_WINDOW_HOURS", "12"))

        now = datetime.now(UTC)

        # --- Rule 1: 48-hour interval from last posted video ---
        last_post_time = self._get_last_post_time()
        earliest_by_interval = last_post_time + timedelta(hours=interval_hours) if last_post_time else now

        # --- Rule 2: View velocity window ---
        # Check the most recent posted video's velocity data.
        # If channel_views_per_hr < threshold and held for velocity_window hours,
        # the algorithm has finished cycling — we're clear to post.
        velocity_clear = self._check_velocity_window(velocity_threshold, velocity_window)

        # --- Rule 3: Align to optimal upload hour (14:00 UTC default) ---
        optimal_hour = int(os.getenv("UPLOAD_HOUR_UTC", "14"))

        # Start from the later of (interval constraint) and (now if velocity is clear)
        base = max(earliest_by_interval, now if velocity_clear else now + timedelta(hours=velocity_window))

        # Advance to next occurrence of optimal_hour
        candidate = base.replace(minute=0, second=0, microsecond=0)
        if candidate.hour >= optimal_hour:
            candidate = candidate + timedelta(days=1)
        candidate = candidate.replace(hour=optimal_hour)

        logger.info(
            f"[{self.name}] Upload window: velocity_clear={velocity_clear}, "
            f"earliest_by_interval={earliest_by_interval.isoformat()}, "
            f"scheduled={candidate.isoformat()}"
        )
        return candidate

    def _get_last_post_time(self) -> datetime | None:
        """Return the posted_time of the most recently posted video."""
        try:
            posted = self.store.get_by_status(JobStatus.POSTED)
            if not posted:
                return None
            latest = max(
                (j for j in posted if j.posted_time),
                key=lambda j: j.posted_time,  # type: ignore[arg-type,return-value]
                default=None,
            )
            return latest.posted_time if latest else None
        except Exception:
            return None

    def _check_velocity_window(self, threshold: int, window_hours: int) -> bool:
        """
        Returns True if the most recent posted video's view velocity has been
        below `threshold` for at least `window_hours` consecutive hours.

        Uses velocity_hours_below_threshold field on the VideoJob.
        This field is updated by AnalyticsAgent when it polls platform APIs.
        Until real-time data is wired up it falls back to a conservative
        time-based heuristic: assume velocity drops after 36 hours.
        """
        try:
            posted = self.store.get_by_status(JobStatus.POSTED)
            if not posted:
                return True  # no previous video — free to post

            latest = max(
                (j for j in posted if j.posted_time),
                key=lambda j: j.posted_time,  # type: ignore[arg-type,return-value]
                default=None,
            )
            if not latest:
                return True

            # If we have real velocity data from analytics, use it
            if latest.velocity_hours_below_threshold >= window_hours:
                logger.info(
                    f"[{self.name}] Velocity window met: "
                    f"{latest.velocity_hours_below_threshold}h below {threshold} views/hr"
                )
                return True

            # Fallback heuristic: assume velocity window opens 36h after post
            hours_since_post = (datetime.now(UTC) - latest.posted_time).total_seconds() / 3600  # type: ignore[operator]
            if hours_since_post >= 36:
                logger.info(
                    f"[{self.name}] Velocity heuristic: {hours_since_post:.1f}h since last post (>= 36h threshold)"
                )
                return True

            logger.info(
                f"[{self.name}] Velocity window NOT met: "
                f"{hours_since_post:.1f}h since last post, "
                f"{latest.velocity_hours_below_threshold}h of sub-{threshold} velocity"
            )
            return False

        except Exception as e:
            logger.warning(f"[{self.name}] Velocity check failed: {e} — defaulting safe")
            return False

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
