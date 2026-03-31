"""A2UI REST routes — canvas event endpoints for agent → frontend communication.

Sprint 5.2 — Transport
Sprint 5.4 — Interaction Loop
Sprint 5.5 — Guardrails (clear, quota, state)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.a2ui.bus import A2UIPermissionError, A2UIQuotaError, get_a2ui_bus
from backend.a2ui.schema import A2UIAction, A2UIMessage

router = APIRouter(prefix="/canvas", tags=["canvas"])

# Injectable for testing
_get_bus = get_a2ui_bus


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class CanvasEmitResponse(BaseModel):
    ok: bool
    seq: int
    ws_clients_reached: int


class CanvasStateResponse(BaseModel):
    session_id: str
    targets: dict[str, Any]
    event_count: int


class CanvasClearResponse(BaseModel):
    ok: bool
    session_id: str
    widgets_removed: int


class ActionDispatchResponse(BaseModel):
    ok: bool
    action_id: str
    dispatched: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Emit endpoint
# ---------------------------------------------------------------------------


@router.post("/{session_id}/event", response_model=CanvasEmitResponse, status_code=200)
async def emit_canvas_event(session_id: str, body: A2UIMessage) -> CanvasEmitResponse:
    """Agent emits a canvas event for the given session."""
    if body.session_id != session_id:
        raise HTTPException(
            status_code=422,
            detail=f"session_id in URL ({session_id!r}) does not match body ({body.session_id!r})",
        )

    bus = _get_bus()
    try:
        result = await bus.emit(body)
    except A2UIPermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except A2UIQuotaError as exc:
        raise HTTPException(status_code=429, detail=str(exc))

    return CanvasEmitResponse(
        ok=result["ok"],
        seq=result["seq"],
        ws_clients_reached=result["ws_clients_reached"],
    )


# ---------------------------------------------------------------------------
# State endpoint
# ---------------------------------------------------------------------------


@router.get("/{session_id}/state", response_model=CanvasStateResponse)
async def get_canvas_state(session_id: str) -> CanvasStateResponse:
    """Return current canvas widget state for the session."""
    bus = _get_bus()
    state = bus.get_canvas_state(session_id)
    count = bus.get_event_count(session_id)
    return CanvasStateResponse(session_id=session_id, targets=state, event_count=count)


# ---------------------------------------------------------------------------
# Clear endpoint (Sprint 5.5)
# ---------------------------------------------------------------------------


@router.delete("/{session_id}", response_model=CanvasClearResponse)
async def clear_canvas(session_id: str) -> CanvasClearResponse:
    """Operator clear-all endpoint — removes all widgets for the session."""
    bus = _get_bus()
    result = await bus.clear_canvas(session_id)
    return CanvasClearResponse(
        ok=result["ok"],
        session_id=result["session_id"],
        widgets_removed=result["widgets_removed"],
    )


# ---------------------------------------------------------------------------
# Widget action endpoint (Sprint 5.4)
# ---------------------------------------------------------------------------


@router.post("/action", response_model=ActionDispatchResponse)
async def handle_canvas_action(body: A2UIAction) -> ActionDispatchResponse:
    """Receive a widget interaction and dispatch it to the agent's mailbox.

    The action is forwarded as a message via the orchestrator.
    """
    try:
        from backend.server import _orchestrator  # type: ignore[attr-defined]
    except ImportError:
        _orchestrator = None

    if _orchestrator is None:
        return ActionDispatchResponse(
            ok=True,
            action_id=body.action_id,
            dispatched=False,
            detail="Orchestrator not available; action logged only.",
        )

    try:
        await _orchestrator.process_message(
            agent_id=body.agent_id,
            message=f"[A2UI Action] widget={body.widget_id} action={body.action_type}",
            context={
                "a2ui_action": body.model_dump(),
                "session_id": body.session_id,
            },
        )
        dispatched = True
        detail = "dispatched"
    except Exception as exc:
        dispatched = False
        detail = str(exc)

    return ActionDispatchResponse(
        ok=True,
        action_id=body.action_id,
        dispatched=dispatched,
        detail=detail,
    )
