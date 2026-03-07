from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.orchestrator import AgentOrchestrator

router = APIRouter(prefix="/agents-control", tags=["agent-control"])
a2a_router = APIRouter(prefix="/agents", tags=["agent-control"])

_orchestrator: AgentOrchestrator | None = None


class AgentMessageSendRequest(BaseModel):
    from_agent: str = Field(..., min_length=1)
    to_agent: str = Field(..., min_length=1)
    purpose: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_message_id: str | None = None
    depth: int = Field(default=0, ge=0)
    allow_self: bool = False
    message_id: str | None = None
    thread_id: str | None = None


def set_orchestrator(orchestrator: AgentOrchestrator | None) -> None:
    global _orchestrator
    _orchestrator = orchestrator


def _require_orchestrator() -> AgentOrchestrator:
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator unavailable")
    return _orchestrator


@router.get("/health")
async def routes_health() -> dict[str, str]:
    return {"status": "ok"}


@a2a_router.get("/messages")
async def list_agent_messages(
    agent_id: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    orchestrator = _require_orchestrator()
    return orchestrator.list_agent_messages(agent_id=agent_id, limit=limit)


@a2a_router.post("/messages/send")
async def send_agent_message(payload: AgentMessageSendRequest) -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    try:
        return orchestrator.send_agent_message(
            from_agent=payload.from_agent,
            to_agent=payload.to_agent,
            purpose=payload.purpose,
            payload=payload.payload,
            parent_message_id=payload.parent_message_id,
            depth=payload.depth,
            allow_self=payload.allow_self,
            message_id=payload.message_id,
            thread_id=payload.thread_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@a2a_router.get("/messages/thread/{thread_id}")
async def get_message_history(thread_id: str) -> list[dict[str, Any]]:
    orchestrator = _require_orchestrator()
    return orchestrator.get_message_history(thread_id=thread_id)
