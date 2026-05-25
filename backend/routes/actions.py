"""
Actions routes — operator approval loop endpoints.

Week 2 sprint A2+A3.

Endpoints:
  POST /actions/proposed       — agent submits a proposal
  GET  /actions/pending        — operator lists pending
  POST /actions/{id}/approve   — operator approves (idempotent) + executor runs
  POST /actions/{id}/reject    — operator rejects with reason
  GET  /audit                  — paginated audit-log read

When an action is approved, the corresponding tool (looked up via
``backend.tools.execute_tool``) is invoked synchronously and the result is
recorded both on the action row and as an ``audit_log`` row.

All state transitions write to the audit log. Mutations are idempotent:
re-approving an already-EXECUTED action returns the current state rather
than re-running the tool.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from backend.database import actions_store as actions_store_module
from backend.database import audit_store as audit_store_module
from backend.models.actions import (
    ActionStatus,
    ApproveRequest,
    ProposedAction,
    ProposeRequest,
    RejectRequest,
)
from backend.tools import process_restart
from backend.utils import logger

router = APIRouter(prefix="/actions", tags=["actions"])
audit_router = APIRouter(prefix="/audit", tags=["actions"])


def _store():
    """Return the live actions store (re-resolved so tests can swap singletons)."""
    return actions_store_module.actions_store


def _audit():
    return audit_store_module.audit_store


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _terminal(status: ActionStatus) -> bool:
    return status in (ActionStatus.EXECUTED, ActionStatus.FAILED, ActionStatus.REJECTED)


# ---------------------------------------------------------------------------
# POST /actions/proposed
# ---------------------------------------------------------------------------


@router.post("/proposed", status_code=201)
async def propose_action(payload: ProposeRequest, request: Request) -> ProposedAction:
    action = ProposedAction(
        agent_id=payload.agent_id,
        action_type=payload.action_type,
        parameters=payload.parameters,
        summary=payload.summary,
        source=payload.source,
    )
    _store().insert(action)
    _audit().write(
        operator=None,
        agent_id=action.agent_id,
        action_type=action.action_type,
        payload={
            "event": "proposed",
            "action_id": action.id,
            "parameters": action.parameters,
            "summary": action.summary,
        },
        ip=_client_ip(request),
        source=action.source,
    )
    return action


# ---------------------------------------------------------------------------
# GET /actions/pending
# ---------------------------------------------------------------------------


@router.get("/pending")
async def list_pending(limit: int = Query(100, ge=1, le=500)) -> list[ProposedAction]:
    return _store().list_by_status(ActionStatus.PENDING, limit=limit)


# ---------------------------------------------------------------------------
# POST /actions/{id}/approve
# ---------------------------------------------------------------------------


@router.post("/{action_id}/approve")
async def approve_action(action_id: str, payload: ApproveRequest, request: Request) -> ProposedAction:
    action = _store().get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")

    if _terminal(action.status):
        # Idempotent: return current state without re-running.
        return action

    action.status = ActionStatus.APPROVED
    action.operator = payload.operator
    _store().update(action)
    _audit().write(
        operator=action.operator,
        agent_id=action.agent_id,
        action_type=action.action_type,
        payload={"event": "approved", "action_id": action.id, "parameters": action.parameters},
        ip=_client_ip(request),
        source=action.source,
    )

    result = await _execute(action)
    action.result = result
    action.executed_at = datetime.now(UTC)
    action.status = ActionStatus.EXECUTED if result.get("success", False) else ActionStatus.FAILED
    _store().update(action)

    _audit().write(
        operator=action.operator,
        agent_id=action.agent_id,
        action_type=action.action_type,
        payload={"event": "executed", "action_id": action.id, "parameters": action.parameters},
        result=result,
        ip=_client_ip(request),
        source=action.source,
    )
    return action


# ---------------------------------------------------------------------------
# POST /actions/{id}/reject
# ---------------------------------------------------------------------------


@router.post("/{action_id}/reject")
async def reject_action(action_id: str, payload: RejectRequest, request: Request) -> ProposedAction:
    action = _store().get(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="action not found")

    if _terminal(action.status):
        return action

    action.status = ActionStatus.REJECTED
    action.operator = payload.operator
    action.reason = payload.reason
    _store().update(action)
    _audit().write(
        operator=action.operator,
        agent_id=action.agent_id,
        action_type=action.action_type,
        payload={"event": "rejected", "action_id": action.id, "reason": payload.reason},
        ip=_client_ip(request),
        source=action.source,
    )
    return action


# ---------------------------------------------------------------------------
# GET /audit
# ---------------------------------------------------------------------------


@audit_router.get("")
async def list_audit(
    limit: int = Query(100, ge=1, le=1000),
    since: datetime | None = Query(None),
    operator: str | None = Query(None),
) -> list[dict[str, Any]]:
    rows = _audit().query(limit=limit, since=since, operator=operator)
    return [r.model_dump(mode="json") for r in rows]


# ---------------------------------------------------------------------------
# Executor — looks up the tool by name and runs it with the action's parameters.
# ---------------------------------------------------------------------------


async def _execute(action: ProposedAction) -> dict[str, Any]:
    """Run the tool implied by ``action.action_type``. Always returns a dict.

    The approval-loop bypasses ``backend.tools.execute_tool`` because the
    operator's approval IS the drift-guard at this layer; ``allowed_tools``
    plumbing is unnecessary. ``ACTION_DISPATCH`` is module-level so tests can
    swap a mock in cleanly.
    """
    params = dict(action.parameters or {})
    handler = ACTION_DISPATCH.get(action.action_type)
    if handler is None:
        return {"success": False, "error": f"action_type '{action.action_type}' not in dispatch table"}
    try:
        result = await handler(action, params)
    except Exception as exc:  # noqa: BLE001 — surface failure to the operator
        logger.warning(f"[actions] executor failed action={action.id} type={action.action_type}: {exc}")
        return {"success": False, "error": str(exc)}
    if not isinstance(result, dict):
        return {"success": True, "result": result}
    if "success" not in result:
        result = {"success": True, **result}
    return result


async def _exec_process_restart(action: ProposedAction, params: dict[str, Any]) -> dict[str, Any]:
    return await process_restart(
        process_name=params.get("process_name", ""),
        agent_id=action.agent_id,
        confirm=True,
        reason=params.get("reason") or f"operator approval by {action.operator}",
    )


ACTION_DISPATCH: dict[str, Any] = {
    "process_restart": _exec_process_restart,
}
