"""
Proposed-action data model — Week 2 sprint A2.

The approval-loop spine of the MVP. Agents emit a ``ProposedAction`` instead
of executing remediation steps directly. An operator (web, Discord, or CLI)
approves or rejects, and only then does the executor run the underlying tool.
Every state transition is persisted to the audit log.

See: docs/WEEK_2_SPRINT.md §A2.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class ActionStatus(str, Enum):
    """Lifecycle states for a proposed action."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class ActionSource(str, Enum):
    """Origin surface for a proposal or audit event."""

    WEB = "web"
    DISCORD = "discord"
    CLI = "cli"


def _new_action_id() -> str:
    return f"act_{uuid4().hex[:12]}"


def _new_audit_id() -> str:
    return f"aud_{uuid4().hex[:12]}"


def _now() -> datetime:
    return datetime.now(UTC)


class ProposedAction(BaseModel):
    """A remediation step proposed by an agent, awaiting operator approval."""

    id: str = Field(default_factory=_new_action_id)
    agent_id: str
    action_type: str  # e.g. "process_restart"
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    status: ActionStatus = ActionStatus.PENDING
    source: ActionSource = ActionSource.WEB
    created_at: datetime = Field(default_factory=_now)
    operator: str | None = None  # set on approve/reject
    reason: str | None = None  # set on reject
    result: dict[str, Any] | None = None  # set after executor runs
    executed_at: datetime | None = None


class ProposeRequest(BaseModel):
    """Payload an agent (or its caller) submits to POST /actions/proposed."""

    agent_id: str
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    source: ActionSource = ActionSource.WEB


class ApproveRequest(BaseModel):
    operator: str = "operator"


class RejectRequest(BaseModel):
    operator: str = "operator"
    reason: str = ""


class ActionAuditRow(BaseModel):
    """A single immutable audit row. See backend/database/audit_store.py."""

    id: str = Field(default_factory=_new_audit_id)
    ts: datetime = Field(default_factory=_now)
    operator: str | None = None
    agent_id: str | None = None
    action_type: str | None = None
    payload_json: dict[str, Any] = Field(default_factory=dict)
    result_json: dict[str, Any] | None = None
    ip: str | None = None
    source: ActionSource = ActionSource.WEB
