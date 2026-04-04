"""
Agent Factory & Training Data Routes — API endpoints for dynamic agent
creation and training data management.
=====================================================================
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.models import ChangeImpactLevel

router = APIRouter(prefix="/api/factory", tags=["agent-factory"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CreateAgentRequest(BaseModel):
    agent_id: str = Field(..., description="snake_case identifier")
    role: str = Field(..., description="What this agent does")
    system_prompt: str = Field(..., description="Agent system prompt")
    tool_permissions: list[str] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    change_impact_level: str = Field(default="MEDIUM")
    skills: list[str] = Field(default_factory=list)
    rationale: str = Field(..., description="Why this agent is needed")
    requested_by: str = Field(default="orchestrator")


class FeedbackRequest(BaseModel):
    user_message: str
    original_agent: str
    correct_agent: str
    reasoning: str = ""


class GenerateRequest(BaseModel):
    count: int = Field(default=50, ge=1, le=200)


# ---------------------------------------------------------------------------
# Factory endpoints
# ---------------------------------------------------------------------------


@router.post("/agents")
async def create_agent(request: CreateAgentRequest) -> dict[str, Any]:
    """Create a new agent via the factory."""
    from backend.orchestrator.agent_factory import AgentBlueprint

    _get = _get_orchestrator()

    try:
        impact = ChangeImpactLevel(request.change_impact_level)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid impact level: {request.change_impact_level}. "
            f"Valid: {[e.value for e in ChangeImpactLevel]}",
        )

    blueprint = AgentBlueprint(
        agent_id=request.agent_id,
        role=request.role,
        system_prompt=request.system_prompt,
        tool_permissions=request.tool_permissions,
        allowed_actions=request.allowed_actions,
        change_impact_level=impact,
        skills=request.skills,
        rationale=request.rationale,
        requested_by=request.requested_by,
    )

    result = _get.create_dynamic_agent(blueprint)

    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    return {
        "agent_id": result.agent_id,
        "status": "created",
        "definition": result.definition.model_dump() if result.definition else None,
    }


@router.get("/agents")
async def list_factory_agents() -> dict[str, Any]:
    """List all dynamically created agents."""
    _get = _get_orchestrator()
    agents = _get.list_factory_agents()
    return {
        "agents": [a.model_dump() for a in agents],
        "count": len(agents),
    }


@router.delete("/agents/{agent_id}")
async def delete_factory_agent(agent_id: str) -> dict[str, Any]:
    """Delete a factory-created agent."""
    _get = _get_orchestrator()
    success = _get.delete_factory_agent(agent_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Factory agent '{agent_id}' not found")
    return {"agent_id": agent_id, "status": "deleted"}


# ---------------------------------------------------------------------------
# Training data endpoints
# ---------------------------------------------------------------------------


@router.get("/training/stats")
async def training_stats() -> dict[str, Any]:
    """Return statistics about collected training data."""
    _get = _get_orchestrator()
    return _get.get_training_stats()


@router.post("/training/feedback")
async def record_feedback(request: FeedbackRequest) -> dict[str, Any]:
    """Record human feedback that a routing decision was wrong (DPO pair)."""
    _get = _get_orchestrator()
    return _get.record_routing_feedback(
        user_message=request.user_message,
        original_agent=request.original_agent,
        correct_agent=request.correct_agent,
        reasoning=request.reasoning,
    )


@router.post("/training/export")
async def export_training() -> dict[str, Any]:
    """Compile and export all collected training data."""
    _get = _get_orchestrator()
    return _get.export_training_data()


@router.post("/training/generate/routing")
async def generate_routing(request: GenerateRequest) -> dict[str, Any]:
    """Generate synthetic routing examples using the LLM."""
    from backend.ml.training_generator import TrainingGenerator

    _get = _get_orchestrator()
    gen = TrainingGenerator(_get.llm_client)
    return await gen.generate_routing_batch(count=request.count)


@router.post("/training/generate/trajectories")
async def generate_trajectories(request: GenerateRequest) -> dict[str, Any]:
    """Generate synthetic trajectory examples using the LLM."""
    from backend.ml.training_generator import TrainingGenerator

    _get = _get_orchestrator()
    gen = TrainingGenerator(_get.llm_client)
    return await gen.generate_trajectory_batch(count=request.count)


@router.post("/training/generate/dpo")
async def generate_dpo(request: GenerateRequest) -> dict[str, Any]:
    """Generate synthetic DPO preference pairs using the LLM."""
    from backend.ml.training_generator import TrainingGenerator

    _get = _get_orchestrator()
    gen = TrainingGenerator(_get.llm_client)
    return await gen.generate_preference_batch(count=request.count)


# ---------------------------------------------------------------------------
# Helper: get orchestrator from app state
# ---------------------------------------------------------------------------

_orchestrator_ref = None


def _get_orchestrator():  # noqa: ANN202
    """Lazy-load the orchestrator singleton."""
    global _orchestrator_ref
    if _orchestrator_ref is not None:
        return _orchestrator_ref

    # Import at call-time to avoid circular imports at module load
    try:
        from backend.server import _orchestrator as orchestrator

        _orchestrator_ref = orchestrator
        return orchestrator
    except (ImportError, AttributeError):
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
