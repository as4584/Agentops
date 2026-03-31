"""
VideoJob Data Model — Single source of truth for every content piece.
=====================================================================
Every video flowing through the pipeline MUST exist as a VideoJob record.
No agent operates outside this schema.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    # --- Ideation gate (new) ---
    IDEA_PENDING = "idea_pending"  # waiting for human greenlight
    IDEA_APPROVED = "idea_approved"  # greenlit → ready for scripting
    # --- Production pipeline ---
    DRAFT = "draft"  # legacy / manual entry
    GENERATED = "generated"
    AUDIO_READY = "audio_ready"
    VIDEO_READY = "video_ready"
    CAPTIONED = "captioned"
    QA = "qa"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    POSTED = "posted"
    FAILED = "failed"


class Analytics(BaseModel):
    views: int = 0
    retention: float = 0.0
    watch_time: float = 0.0
    shares: int = 0
    saves: int = 0
    comments: int = 0
    followers_gained: int = 0
    hook_retention: float = 0.0


class QAReport(BaseModel):
    audio_lufs: float | None = None
    audio_clipped: bool | None = None
    caption_accuracy: float | None = None
    video_duration_sec: float | None = None
    visual_artifacts: bool | None = None
    policy_violation: bool | None = None
    passed: bool = False
    notes: list[str] = Field(default_factory=list)


class VideoJob(BaseModel):
    """Immutable-style record — agents update via job_store only."""

    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    topic: str = ""
    hook: str = ""
    script: str = ""
    final_transcript: str = ""

    # --- Ideation / research fields ---
    idea_pitch: str = ""  # one-paragraph pitch with conflict angle
    trend_data: dict = {}  # raw trend signals from TrendResearcher
    prompt_frames: list[str] = Field(default_factory=list)  # one image-gen prompt per arc beat (8 beats)
    niche: str = ""  # e.g. "gaming", "ai_tools", "money"
    visual_style: str = ""  # e.g. "reddit_commentary", "cinematic", "news"
    style_notes: str = ""  # free-form style guide for frame generation

    # --- Upload timing ---
    channel_views_per_hr: float = 0.0  # latest video's current views/hr
    velocity_hours_below_threshold: int = 0  # consecutive hours below threshold

    # --- Production paths ---
    voice_audio_path: str = ""
    avatar_video_path: str = ""
    captioned_video_path: str = ""

    status: JobStatus = JobStatus.DRAFT

    platform_targets: list[str] = Field(default_factory=lambda: ["instagram", "tiktok", "youtube_shorts"])
    scheduled_time: datetime | None = None
    posted_time: datetime | None = None

    analytics: Analytics = Field(default_factory=Analytics)
    qa_report: QAReport = Field(default_factory=QAReport)

    content_pillar: str = ""
    source: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    failure_reason: str = ""
    retry_count: int = 0
    hashtags: list[str] = Field(default_factory=list)
    caption_text: str = ""

    def transition(self, new_status: JobStatus) -> None:
        """Enforce legal state transitions."""
        legal: dict[JobStatus, set[JobStatus]] = {
            # Ideation gate
            JobStatus.IDEA_PENDING: {JobStatus.IDEA_APPROVED, JobStatus.FAILED},
            JobStatus.IDEA_APPROVED: {JobStatus.GENERATED, JobStatus.FAILED},
            # Legacy / manual entry
            JobStatus.DRAFT: {JobStatus.GENERATED, JobStatus.FAILED},
            # Production pipeline
            JobStatus.GENERATED: {JobStatus.AUDIO_READY, JobStatus.FAILED},
            JobStatus.AUDIO_READY: {JobStatus.VIDEO_READY, JobStatus.FAILED},
            JobStatus.VIDEO_READY: {JobStatus.CAPTIONED, JobStatus.FAILED},
            JobStatus.CAPTIONED: {JobStatus.QA, JobStatus.FAILED},
            JobStatus.QA: {JobStatus.APPROVED, JobStatus.FAILED},
            JobStatus.APPROVED: {JobStatus.SCHEDULED, JobStatus.FAILED},
            JobStatus.SCHEDULED: {JobStatus.POSTED, JobStatus.FAILED},
            JobStatus.POSTED: set(),
            JobStatus.FAILED: {
                JobStatus.IDEA_PENDING,
                JobStatus.IDEA_APPROVED,
                JobStatus.DRAFT,
                JobStatus.GENERATED,
                JobStatus.AUDIO_READY,
                JobStatus.VIDEO_READY,
                JobStatus.CAPTIONED,
            },
        }
        allowed = legal.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(f"Illegal transition: {self.status.value} → {new_status.value}")
        self.status = new_status
        self.updated_at = datetime.now(UTC)
