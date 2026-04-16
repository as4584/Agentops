"""
Models — Pydantic data models for the Agentop system.
=====================================================
Typed models enforce structure across all boundaries.
These models form the contract between subsystems.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

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

    GREEN = "GREEN"  # Aligned — all documentation matches code
    YELLOW = "YELLOW"  # Pending — documentation update needed
    RED = "RED"  # Violation — architectural invariant broken


class AgentStatus(str, Enum):
    """Runtime status of an agent."""

    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"
    HALTED = "HALTED"


class ToolCallStatus(str, Enum):
    """Outcome classification for a single tool invocation.

    Used by ToolResult to communicate exactly how an invocation ended
    so callers can branch on structured outcomes instead of string-matching.
    """

    SUCCESS = "success"
    VALIDATION_FAILURE = "validation_failure"  # tool name / arg schema rejected
    EXECUTION_ERROR = "execution_error"         # tool ran but returned an error
    TIMEOUT = "timeout"                         # tool exceeded its time budget
    UNAVAILABLE = "unavailable"                 # tool not registered / not allowed
    DEGRADED = "degraded"                       # result produced by a fallback path


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
    # Sprint 1: schema-first additions
    parameters: dict[str, Any] | None = Field(
        default=None,
        description="JSON Schema object describing the tool's input parameters",
    )
    timeout_seconds: int = Field(default=30, description="Maximum execution time in seconds")
    idempotent: bool = Field(default=False, description="True if re-running with same args is safe")
    side_effects: list[str] = Field(
        default_factory=list,
        description="Human-readable list of external side effects (e.g. 'writes to disk', 'sends HTTP request')",
    )


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
# Sprint 1 — Typed runtime contracts
# ---------------------------------------------------------------------------


class ToolCall(BaseModel):
    """A single structured tool invocation within an agent turn."""

    id: str = Field(..., description="Unique call ID (e.g. uuid4 hex)")
    name: str = Field(..., description="Tool name from TOOL_REGISTRY")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Parsed tool arguments")
    result: Any | None = Field(default=None, description="Execution result once available")
    error: str | None = Field(default=None, description="Error message if execution failed")
    duration_ms: float | None = Field(default=None, description="Wall-clock execution time")


class ToolResult(BaseModel):
    """Canonical result of a single tool invocation.

    Returned by tool-execution helpers and consumed by the agent v2 runtime.
    Separates the invocation record (ToolCall) from the outcome so the
    runtime can branch on ``status`` without inspecting raw strings.
    """

    call_id: str = Field(..., description="Matches ToolCall.id that produced this result")
    tool_name: str = Field(..., description="Matches ToolCall.name")
    status: ToolCallStatus = Field(..., description="Structured outcome classification")
    content: Any = Field(default=None, description="Structured output on success")
    error: str | None = Field(default=None, description="Error message when status != success")
    duration_ms: float | None = Field(default=None, description="Wall-clock execution time in ms")
    degraded: bool = Field(
        default=False,
        description="True when this result was produced by a degraded or fallback path",
    )


class AgentTurn(BaseModel):
    """One reasoning step produced by an agent in the ReAct loop."""

    turn_id: str = Field(..., description="Unique turn ID")
    role: Literal["planner", "executor", "validator"] = Field(
        ..., description="Which sub-role produced this turn"
    )
    model_id: str = Field(..., description="Model that generated this turn")
    content: str = Field(..., description="Raw LLM output for this turn")
    tool_calls: list[ToolCall] = Field(
        default_factory=list, description="Structured tool calls parsed from this turn"
    )
    observations: list[str] = Field(
        default_factory=list, description="Tool execution results observed after this turn"
    )
    is_final: bool = Field(default=False, description="True when the agent signals task complete")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ExecutionPlan(BaseModel):
    """A structured plan produced by the planner sub-role before executor runs."""

    goal: str = Field(..., description="Original task goal")
    steps: list[str] = Field(default_factory=list, description="Ordered list of execution steps")
    required_tools: list[str] = Field(
        default_factory=list, description="Tools the executor will need"
    )
    risk_level: ChangeImpactLevel = Field(
        default=ChangeImpactLevel.LOW, description="Risk of the planned actions"
    )
    model_role_hints: dict[str, str] = Field(
        default_factory=dict,
        description="Suggested model IDs keyed by role (e.g. executor, validator)",
    )
    rejected_alternatives: list[str] = Field(
        default_factory=list, description="Approaches considered but rejected"
    )


class ValidationReport(BaseModel):
    """Validator sub-role output assessing an execution result."""

    passed: bool = Field(..., description="True if the result meets acceptance criteria")
    score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Quality score 0–1"
    )
    issues: list[str] = Field(default_factory=list, description="Identified problems")
    recommendations: list[str] = Field(
        default_factory=list, description="Suggested improvements"
    )
    requires_retry: bool = Field(
        default=False, description="True if the executor should retry"
    )
    retry_hint: str = Field(
        default="", description="Guidance for the retry attempt"
    )


class ModelRolePolicy(BaseModel):
    """Maps agent execution roles to preferred model IDs."""

    router: str = Field(default="qwen2.5:3b", description="Fast classification / intent routing")
    planner: str = Field(default="kimi-k2", description="Task decomposition and plan generation")
    code_planner: str = Field(
        default="qwen3-coder:free", description="Code-task plan generation"
    )
    executor: str = Field(
        default="qwen2.5-coder:7b", description="Tool-calling execution (local first)"
    )
    validator_routine: str = Field(
        default="llama3.2", description="Routine output validation"
    )
    validator_high_risk: str = Field(
        default="deepseek-r1:free", description="High-risk / architectural validation"
    )
    retrieval_rewrite: str = Field(
        default="llama3.2:1b", description="Query rewriting for RAG retrieval"
    )


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


# ---------------------------------------------------------------------------
# Sprint 2 — S2.1: GitNexus Health Model
# ---------------------------------------------------------------------------


class GitNexusHealthState(BaseModel):
    """Runtime health state for the GitNexus code-intelligence subsystem.

    Produced by reading .gitnexus/meta.json and the current config.
    All consumers must check `enabled` and `transport_available` before use.
    """

    enabled: bool = False
    """Whether GITNEXUS_ENABLED=true in config."""

    transport_available: bool = False
    """Whether the MCP transport (docker-mcp CLI or socket) is reachable."""

    repo_name: str = ""
    """Repo name from config (GITNEXUS_REPO_NAME)."""

    index_exists: bool = False
    """Whether .gitnexus/meta.json exists on disk."""

    symbol_count: int = 0
    """Number of symbols in the index (0 if missing)."""

    relationship_count: int = 0
    """Number of relationships in the index (0 if missing)."""

    embeddings_present: bool = False
    """Whether the index was built with embeddings."""

    last_analyzed_at: str = ""
    """ISO-8601 timestamp of the last analysis, empty if unknown."""

    stale: bool = False
    """True when last_analyzed_at is older than GITNEXUS_STALE_HOURS."""

    stale_hours: int = 0
    """Configured staleness threshold in hours."""

    reason: str = ""
    """Human-readable reason for degraded/disabled/unavailable states."""

    @property
    def usable(self) -> bool:
        """Convenience: True only when the subsystem is fully operational."""
        return self.enabled and self.transport_available and self.index_exists and not self.stale


# ---------------------------------------------------------------------------
# Sprint 2 — Embedding Configuration Contract
# ---------------------------------------------------------------------------


class EmbeddingConfig(BaseModel):
    """Typed configuration for the embedding model used across Qdrant collections.

    A single ``EmbeddingConfig`` instance is the source of truth for embedding
    model name and expected vector dimension.  Both values must be consistent —
    changing one without the other will cause silent collection dimension mismatches.

    Validated at startup via ``validate_embedding_startup()`` in
    ``backend.knowledge.context_assembler``.
    """

    model: str = Field(..., description="Ollama model name used for embedding (e.g. nomic-embed-text)")
    dim: int = Field(..., gt=0, description="Expected embedding vector dimension")
    collection_prefix: str = Field(
        default="",
        description="Optional prefix applied to all Qdrant collection names in this context",
    )

    def dim_matches_known(self) -> bool:
        """Return True if dim is consistent with a known model→dim mapping."""
        try:
            from backend.config import KNOWN_EMBED_DIMS
            known = KNOWN_EMBED_DIMS.get(self.model.lower())
            if known is None:
                return True  # unknown model — can't validate, assume OK
            return known == self.dim
        except Exception:
            return True

    @classmethod
    def from_config(cls) -> "EmbeddingConfig":
        """Build from the central config module values."""
        from backend.config import QDRANT_DEFAULT_DIM, QDRANT_EMBED_MODEL
        return cls(model=QDRANT_EMBED_MODEL, dim=QDRANT_DEFAULT_DIM)
