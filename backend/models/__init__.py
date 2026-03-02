"""
Models — Pydantic data models for the Agentop system.
=====================================================
Typed models enforce structure across all boundaries.
These models form the contract between subsystems.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ModificationType(str, Enum):
    """Classification of tool modification impact."""
    READ_ONLY = "READ_ONLY"
    STATE_MODIFY = "STATE_MODIFY"
    ARCHITECTURAL_MODIFY = "ARCHITECTURAL_MODIFY"


class ChangeImpactLevel(str, Enum):
    """Impact level of a change or agent."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DriftStatus(str, Enum):
    """System drift status indicator."""
    GREEN = "GREEN"      # Aligned — all documentation matches code
    YELLOW = "YELLOW"    # Pending — documentation update needed
    RED = "RED"          # Violation — architectural invariant broken


class AgentStatus(str, Enum):
    """Runtime status of an agent."""
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"
    HALTED = "HALTED"


# ---------------------------------------------------------------------------
# Agent Models
# ---------------------------------------------------------------------------

class AgentDefinition(BaseModel):
    """Canonical agent definition mirroring AGENT_REGISTRY.md."""
    agent_id: str = Field(..., description="Unique agent identifier")
    role: str = Field(..., description="Immutable role definition")
    system_prompt: str = Field(..., description="Agent system prompt")
    tool_permissions: list[str] = Field(default_factory=list, description="Allowed tool names")
    memory_namespace: str = Field(..., description="Isolated memory namespace path")
    allowed_actions: list[str] = Field(default_factory=list, description="Explicit action whitelist")
    change_impact_level: ChangeImpactLevel = Field(..., description="Change impact classification")
    skills: list[str] = Field(default_factory=list, description="Skill pack IDs from backend/skills/data/")


class AgentState(BaseModel):
    """Runtime state of an agent."""
    agent_id: str
    status: AgentStatus = AgentStatus.IDLE
    last_active: datetime | None = None
    memory_size_bytes: int = 0
    total_actions: int = 0
    error_count: int = 0


# ---------------------------------------------------------------------------
# Tool Models
# ---------------------------------------------------------------------------

class ToolDefinition(BaseModel):
    """Definition of a registered tool."""
    name: str = Field(..., description="Unique tool name")
    description: str = Field(..., description="Tool purpose")
    modification_type: ModificationType = Field(..., description="Impact classification")
    requires_doc_update: bool = Field(default=False, description="Whether tool requires doc update")


class ToolExecutionRecord(BaseModel):
    """Log record for a tool execution."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    tool_name: str
    agent_id: str
    modification_type: ModificationType
    input_summary: str = ""
    output_summary: str = ""
    success: bool = True
    error: str | None = None
    doc_updated: bool = False


# ---------------------------------------------------------------------------
# Change Log Models
# ---------------------------------------------------------------------------

class ChangeLogEntry(BaseModel):
    """Structured entry for CHANGE_LOG.md."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    agent_id: str = Field(..., description="Agent responsible for the change")
    files_modified: list[str] = Field(default_factory=list)
    reason: str = Field(..., description="Description of change")
    risk_assessment: ChangeImpactLevel = Field(..., description="Risk level")
    impacted_subsystems: list[str] = Field(default_factory=list)
    documentation_updated: bool = Field(default=False)


# ---------------------------------------------------------------------------
# Drift Models
# ---------------------------------------------------------------------------

class DriftEvent(BaseModel):
    """A detected drift event."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    invariant_id: str = Field(..., description="Which invariant was violated")
    description: str = Field(..., description="What happened")
    severity: ChangeImpactLevel = Field(..., description="Severity of the drift")
    resolved: bool = False


class DriftReport(BaseModel):
    """Current drift status of the system."""
    status: DriftStatus = DriftStatus.GREEN
    pending_updates: list[str] = Field(default_factory=list)
    violations: list[DriftEvent] = Field(default_factory=list)
    last_check: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# API Request/Response Models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    """Incoming chat request to an agent."""
    agent_id: str = Field(..., description="Target agent ID")
    message: str = Field(..., description="User message")
    context: dict[str, Any] = Field(default_factory=dict, description="Optional context")


class ChatResponse(BaseModel):
    """Response from an agent."""
    agent_id: str
    message: str
    tool_calls: list[ToolExecutionRecord] = Field(default_factory=list)
    drift_status: DriftStatus = DriftStatus.GREEN
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class IntakeStartRequest(BaseModel):
    """Start a business intake session."""
    business_id: str = Field(..., description="Unique business identifier")


class IntakeStartResponse(BaseModel):
    """Initial intake state and first question."""
    business_id: str
    current_question_index: int
    total_questions: int
    question_key: str
    question: str
    completed: bool = False


class IntakeAnswerRequest(BaseModel):
    """Submit a single intake answer."""
    business_id: str = Field(..., description="Business identifier")
    answer: str = Field(..., description="Answer text for current intake question")


class IntakeStatusResponse(BaseModel):
    """Current intake status for a business profile."""
    business_id: str
    current_question_index: int
    total_questions: int
    completed: bool
    next_question_key: str | None = None
    next_question: str | None = None
    answers: dict[str, str] = Field(default_factory=dict)


class CampaignGenerateRequest(BaseModel):
    """Generate a social campaign from completed intake context."""
    business_id: str = Field(..., description="Business identifier")
    platform: str = Field(..., description="Target platform")
    objective: str = Field(..., description="Campaign objective")
    format_type: str = Field(default="reel", description="Content format")
    duration_seconds: int = Field(default=30, description="Target duration in seconds")


class CampaignGenerateResponse(BaseModel):
    """Generated campaign package."""
    business_id: str
    platform: str
    objective: str
    format_type: str
    duration_seconds: int
    generated_at: str
    campaign: dict[str, Any]


class SystemStatus(BaseModel):
    """Full system status for dashboard."""
    agents: list[AgentState] = Field(default_factory=list)
    drift_report: DriftReport = Field(default_factory=DriftReport)
    recent_logs: list[ToolExecutionRecord] = Field(default_factory=list)
    total_tool_executions: int = 0
    uptime_seconds: float = 0.0
