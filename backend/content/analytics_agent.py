"""
AnalyticsAgent — Weekly self-optimization loop.
================================================
Uses local Ollama LLM for performance analysis and recommendations.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.config import MEMORY_DIR
from backend.content.base_agent import ContentAgent
from backend.content.video_job import JobStatus, VideoJob
from backend.utils import logger

REPORTS_DIR = MEMORY_DIR / "content_reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class AnalyticsAgent(ContentAgent):
    name = "AnalyticsAgent"
    trigger_status = None  # weekly schedule, not per-job

    async def process(self, job: VideoJob) -> VideoJob | None:
        return None

    async def run(self) -> list[VideoJob]:
        logger.info(f"[{self.name}] Starting weekly analytics...")

        posted = self.store.get_by_status(JobStatus.POSTED)
        week_ago = datetime.now(UTC) - timedelta(days=7)
        recent = [j for j in posted if j.posted_time and j.posted_time >= week_ago]

        logger.info(f"[{self.name}] {len(recent)} videos this week ({len(posted)} total)")

        report = self._build_report(recent, posted)
        report_path = self._save_report(report)

        # LLM-powered recommendations
        recs = await self._generate_recommendations(recent)
        recs_path = REPORTS_DIR / "optimization_recs.json"
        recs_path.write_text(json.dumps(recs, indent=2))

        logger.info(f"[{self.name}] Report: {report_path}")
        logger.info(f"[{self.name}] Recs: {recs_path}")

        return recent

    def _build_report(self, recent: list[VideoJob], all_jobs: list[VideoJob]) -> dict:
        if not recent:
            return {"period": "last_7_days", "total_videos": 0, "summary": "No videos posted."}

        total_views = sum(j.analytics.views for j in recent)
        avg_ret = sum(j.analytics.retention for j in recent) / len(recent)

        by_views = sorted(recent, key=lambda j: j.analytics.views, reverse=True)

        # Pillar breakdown
        pillars: dict[str, dict] = {}
        for j in recent:
            p = j.content_pillar or "uncategorized"
            if p not in pillars:
                pillars[p] = {"count": 0, "total_views": 0}
            pillars[p]["count"] += 1
            pillars[p]["total_views"] += j.analytics.views

        return {
            "period": "last_7_days",
            "generated_at": datetime.now(UTC).isoformat(),
            "total_videos": len(recent),
            "aggregate": {
                "total_views": total_views,
                "avg_retention": round(avg_ret, 1),
                "total_shares": sum(j.analytics.shares for j in recent),
                "total_saves": sum(j.analytics.saves for j in recent),
                "followers_gained": sum(j.analytics.followers_gained for j in recent),
            },
            "top_by_views": [{"job_id": j.job_id, "topic": j.topic, "views": j.analytics.views} for j in by_views[:5]],
            "top_hooks": [{"hook": j.hook, "views": j.analytics.views} for j in by_views[:5] if j.hook],
            "pillar_breakdown": pillars,
        }

    async def _generate_recommendations(self, recent: list[VideoJob]) -> dict:
        if not recent:
            return {"recommendations": [], "topics_to_double_down": [], "topics_to_avoid": []}

        summaries = "\n".join(
            f"- {j.topic} | Hook: {j.hook} | Views: {j.analytics.views} | "
            f"Retention: {j.analytics.retention}% | Shares: {j.analytics.shares}"
            for j in recent
        )

        try:
            raw = await self.llm.chat(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a data-driven content strategist. "
                            "Analyze video performance and give recommendations. "
                            "Respond ONLY with valid JSON: "
                            '{"recommendations": [...], "topics_to_double_down": [...], '
                            '"topics_to_avoid": [...], "hook_patterns": [...]}'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"This week's performance:\n\n{summaries}",
                    },
                ],
                temperature=0.5,
                max_tokens=600,
            )
            # Try to parse JSON from response
            import re

            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"[{self.name}] LLM recs failed: {e}")
            return {"recommendations": [], "error": str(e)}

    def _save_report(self, report: dict) -> Path:
        ts = datetime.now(UTC).strftime("%Y-%m-%d")
        path = REPORTS_DIR / f"weekly_{ts}.json"
        path.write_text(json.dumps(report, indent=2))
        return path
