```python
# ------------------------------------------------------------------
# 1. Python interface (method signatures, input/output types)
# ------------------------------------------------------------------

from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Optional, TypedDict
from zoneinfo import ZoneInfo


# ---- User-supplied unstructured payload from the client ----
class BrandIntake(TypedDict, total=False):
    posting_frequency: Literal["daily", "3x/week", "weekly"]   # optional
    # any other keys are ignored


# ---- Minimal job descriptor injected by the caller ----
@dataclass(slots=True)
class VideoJob:
    job_id: str
    topic: str
    platforms: list[Literal["Instagram", "TikTok", "YouTube"]]


# ---- Public return shape ----
@dataclass(slots=True)
class ScheduledSlot:
    job_id: str
    topic: str
    platform: Literal["Instagram", "TikTok", "YouTube"]
    scheduled_time: datetime      # always UTC
    status: Literal["scheduled"]  # hardcoded today


class ContentCalendar:
    """
    Deterministic scheduler that maps VideoJob(s) to platform-optimal time
    slots while enforcing:
        1. Time-of-day per platform (local to brand, but stored UTC)
        2. ≥4-hour separation between posts
        3. Tue-Thu preference
        4. Brand posting_frequency cap
    No LLM, no I/O, no persistence, no side effects.
    """

    def __init__(self, brand_timezone: str = "UTC") -> None:
        """
        Args:
            brand_timezone: IANA tz identifier, e.g. "America/New_York"
        """
        ...

    # ---------- Primary API ----------
    def schedule_job(
        self,
        job: VideoJob,
        brand_intake: BrandIntake | None = None,
        *,
        after: datetime | None = None,
    ) -> datetime:
        """
        Pick the next UTC datetime that satisfies platform heuristics, spacing,
        and weekly cap (if provided).  `after` defaults to utcnow().
        Idempotent for identical inputs and internal state.
        """
        ...

    def get_week_schedule(
        self, jobs: list[VideoJob]
    ) -> list[ScheduledSlot]:
        """
        Batch-schedule the supplied jobs for the upcoming 7-day rolling window
        and return a chronologically-sorted list of simple public DTOs.
        """
        ...

    # ---------- Internal ----------
    def _find_optimal_slot(
        self,
        platform: Literal["Instagram", "TikTok", "YouTube"],
        existing_times: list[datetime],
        *,
        after: datetime,
    ) -> datetime:
        """
        Brute-force walk forward from `after` (UTC) until a slot satisfies:
            1. Platform local-time windows
            2. ≥4 h clearance from any entry in `existing_times`
            3. Preference Tue-Thu when within same week
        Returns first matching UTC datetime.
        """
        ...


# ------------------------------------------------------------------
# 2. Core logic (step by step)
# ------------------------------------------------------------------

# stateless constants ------------------------------------------------
PLATFORM_OPTIMAL = {
    "Instagram": [(11, 13), (19, 21)],          # 11-13h & 19-21h *local*
    "TikTok": [(7, 9), (12, 15), (19, 23)],
    "YouTube": [(14, 16)],
}
MIN_GAP = timedelta(hours=4)
PREF_DAYS = {1, 2, 3}                # Monday=0 … Thursday=3
MAX_POSTS = {
    "daily": 7,
    "3x/week": 3,
    "weekly": 1,
}
# ---------------------------------------------------------------------


# 2.1 schedule_job ----------------------------------------------------
def schedule_job(
    self,
    job: VideoJob,
    brand_intake: BrandIntake | None = None,
    *,
    after: datetime | None = None,
) -> datetime:
    if after is None:
        after = datetime.now(tz=ZoneInfo("UTC"))

    # 1. decide how many posts the brand allows this week
    freq = (brand_intake or {}).get("posting_frequency")
    cap = MAX_POSTS.get(freq, 999) if freq else 999

    # 2. build a lightweight in-memory list of already scheduled UTC
    #    times for this brand (simulated here by scanning the same job list)
    existing = self._already_scheduled_this_week(after, cap)

    # 3. pick the earliest slot that respects cap & spacing
    best: datetime | None = None
    for platform in job.platforms:
        candidate = self._find_optimal_slot(platform, existing, after=after)
        if best is None or candidate < best:
            best = candidate
    if best is None:                       # should never occur
        raise RuntimeError("No feasible slot")
    return best


# 2.2 _find_optimal_slot ----------------------------------------------
def _find_optimal_slot(
    self,
    platform: Literal["Instagram", "TikTok", "YouTube"],
    existing_times: list[datetime],
    *,
    after: datetime,
) -> datetime:
    tz = ZoneInfo(self.brand_timezone)
   .slot_start = after
    while True:
        # convert to brand local time to check windows
        local = slot_start.astimezone(tz)
        local_time = local.time()
        weekday = local.weekday()

        # 1. platform window match
        windows = PLATFORM_OPTIMAL[platform]
        in_window = any(
            st <= local_time.hour < en for st, en in windows
        )
        if not in_window:
            slot_start += timedelta(hours=1)
            continue

        # 2. 4-hour clearance
        collision = any(
            abs(slot_start - t) < MIN_GAP for t in existing_times
        )
        if collision:
            slot_start += timedelta(minutes=30)
            continue

        # 3. Tue-Thu preference (skip Mon/Fri unless no choice)
        if weekday not in PREF_DAYS:
            # peek next Tue
            next_tue = slot_start + timedelta(days=(1 - weekday) % 7)
            if next_tue - slot_start <= timedelta(days=3):
                slot_start = next_tue.replace(hour=0, minute=0, second=0)
                continue

        # winner
        return slot_start


# 2.3 get_week_schedule ----------------------------------------------
def get_week_schedule(
    self, jobs: list[VideoJob]
) -> list[ScheduledSlot]:
    slots: list[ScheduledSlot] = []
    existing: list[datetime] = []

    for job in jobs:
        dt = self.schedule_job(job, brand_intake=None)  # no intake -> no cap
        existing.append(dt)
        for platform in job.platforms:
            slots.append(
                ScheduledSlot(
                    job_id=job.job_id,
                    topic=job.topic,
                    platform=platform,
                    scheduled_time=dt,
                    status="scheduled",
                )
            )
    slots.sort(key=lambda s: s.scheduled_time)
    return slots


# ------------------------------------------------------------------
# 3. Edge cases it must handle
# ------------------------------------------------------------------
1. Empty job.platforms → raise ValueError
2. Overlapping optimal windows across platforms (choose earliest UTC)
3. Brand frequency cap already reached → postpone into next week
4. Time-zone transitions (DST) handled transparently via ZoneInfo
5. Clock granularity smaller than 1 min → truncated to minute
6. All weekdays exhausted within cap → raise RuntimeError("no feasible slot")
7. Input after=datetime.utcnow() but tz-naive → force UTC
8. Duplicate job_ids in list → idempotent scheduling (same output)
9. 4-hour gap crosses midnight → still enforced
10. _find_optimal_slot runsaway → bounded by +90 days then raise


# ------------------------------------------------------------------
# 4. What it must NOT do
# ------------------------------------------------------------------
- No LLM calls, no embeddings, no prompt engineering
- No persistence or DB writes
- No knowledge of past performance metrics
- No multi-brand conflict resolution (caller isolated)
- No image/video generation or upload
- No retry/queueing logic (pure function)
- No holidays or event awareness
- No locale-specific format localization (return UTC only)
- No back-filling of missed slots
- No mutation of input objects
```