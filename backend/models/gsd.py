"""
GSD (Get Shit Done) — Pydantic models.

Covers the data shapes for all five GSD commands:
  map-codebase / plan-phase / execute-phase / quick / verify-work
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PhaseStatus(str, Enum):
    PENDING    = "pending"
    PLANNING   = "planning"
    PLANNED    = "planned"
    EXECUTING  = "executing"
    COMPLETED  = "completed"
    FAILED     = "failed"


class TaskStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    DONE      = "done"
    SKIPPED   = "skipped"
    FAILED    = "failed"


# ---------------------------------------------------------------------------
# Plan models
# ---------------------------------------------------------------------------

class GSDTask(BaseModel):
    id: str
    description: str
    file_targets: list[str] = Field(default_factory=list)
    symbol_refs: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)   # task ids
    wave: int = 1
    status: TaskStatus = TaskStatus.PENDING
    result_summary: str = ""


class GSDPlan(BaseModel):
    phase: int
    title: str
    description: str
    tasks: list[GSDTask] = Field(default_factory=list)
    status: PhaseStatus = PhaseStatus.PLANNED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    gatekeeper_violations: list[str] = Field(default_factory=list)
    gatekeeper_revision: int = 0


# ---------------------------------------------------------------------------
# Map-codebase result
# ---------------------------------------------------------------------------

class GSDMapResult(BaseModel):
    stack: str = ""
    architecture: str = ""
    conventions: str = ""
    concerns: str = ""
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------

class WaveResult(BaseModel):
    wave: int
    task_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class GSDExecutionResult(BaseModel):
    phase: int
    waves_completed: int = 0
    wave_results: list[WaveResult] = Field(default_factory=list)
    gatekeeper_approved: bool = False
    gatekeeper_violations: list[str] = Field(default_factory=list)
    status: PhaseStatus = PhaseStatus.EXECUTING
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Quick task
# ---------------------------------------------------------------------------

class GSDQuickRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    full: bool = False   # True = commit via git_ops after task


class GSDQuickResult(BaseModel):
    prompt: str
    response: str
    committed: bool = False
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Verify-work report
# ---------------------------------------------------------------------------

class VerifyCheckItem(BaseModel):
    description: str
    status: str    # "passed" | "failed" | "unverifiable"
    detail: str = ""


class GSDVerifyReport(BaseModel):
    phase: int | None = None
    passed: list[VerifyCheckItem] = Field(default_factory=list)
    failed: list[VerifyCheckItem] = Field(default_factory=list)
    unverifiable: list[VerifyCheckItem] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Persistent state file model
# ---------------------------------------------------------------------------

class GSDRoadmapEntry(BaseModel):
    title: str
    milestone: str
    priority: int = 1
    done: bool = False


class GSDStateFile(BaseModel):
    active_phase: int | None = None
    completed_phases: list[int] = Field(default_factory=list)
    failed_phases: list[int] = Field(default_factory=list)
    roadmap: list[GSDRoadmapEntry] = Field(default_factory=list)
    quick_log: list[str] = Field(default_factory=list)   # "<timestamp>: <prompt>"
    map_generated_at: datetime | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
