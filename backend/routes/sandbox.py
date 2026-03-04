from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT
from sandbox.session_manager import SandboxSession, list_active_sessions

router = APIRouter(prefix="/sandbox", tags=["sandbox"])


class SandboxCreateRequest(BaseModel):
    task: str
    model: str = "local"
    session_id: str | None = None


class SandboxCreateResponse(BaseModel):
    session_id: str
    path: str
    task: str
    model: str


class SandboxPromoteRequest(BaseModel):
    files: list[str] = Field(default_factory=list)


class SandboxFinalizeRequest(BaseModel):
    files: list[str] = Field(default_factory=list)
    before_scores: dict[str, Any] | None = None
    after_scores: dict[str, Any] | None = None


class LhciCheckRequest(BaseModel):
    summary_json_path: str
    files_to_promote: list[str] = Field(default_factory=list)
    before_scores: dict[str, Any] | None = None


def _session(session_id: str) -> SandboxSession:
    return SandboxSession(
        project_root=PROJECT_ROOT,
        task="managed-session",
        model="local",
        session_id=session_id,
    )


@router.get("/sessions")
async def get_sessions() -> list[dict[str, Any]]:
    return list_active_sessions()


@router.post("/create", response_model=SandboxCreateResponse, status_code=201)
async def create_session(body: SandboxCreateRequest) -> SandboxCreateResponse:
    session = SandboxSession(
        project_root=PROJECT_ROOT,
        task=body.task,
        model=body.model,
        session_id=body.session_id,
    )
    session.create()
    return SandboxCreateResponse(
        session_id=session.session_id,
        path=str(session.root),
        task=body.task,
        model=body.model,
    )


@router.post("/{session_id}/promote")
async def promote_files(session_id: str, body: SandboxPromoteRequest) -> dict[str, Any]:
    session = _session(session_id)
    try:
        promoted = session.promote(body.files)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, "promoted": promoted}


@router.post("/{session_id}/finalize")
async def finalize_session(session_id: str, body: SandboxFinalizeRequest) -> dict[str, Any]:
    session = _session(session_id)
    try:
        promoted = session.promote(body.files)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    session.destroy(
        before_scores=body.before_scores,
        after_scores=body.after_scores,
        promoted_files=promoted,
    )
    return {"session_id": session_id, "status": "deleted", "promoted": promoted}


@router.post("/{session_id}/lhci-check")
async def lhci_check_and_cleanup(session_id: str, body: LhciCheckRequest) -> dict[str, Any]:
    session = _session(session_id)
    summary_path = Path(body.summary_json_path)
    if not summary_path.is_absolute():
        summary_path = session.root / summary_path
    if not summary_path.exists():
        raise HTTPException(status_code=404, detail=f"LHCI summary file not found: {summary_path}")

    after_scores = SandboxSession.parse_lhci_summary(summary_path)
    passed = SandboxSession.scores_meet_threshold(after_scores, session.threshold)
    if not passed:
        return {
            "session_id": session_id,
            "passed": False,
            "scores": after_scores,
            "threshold": {
                "performance": session.threshold.performance,
                "accessibility": session.threshold.accessibility,
                "best_practices": session.threshold.best_practices,
                "seo": session.threshold.seo,
            },
        }

    promoted = session.promote(body.files_to_promote)
    session.destroy(
        before_scores=body.before_scores,
        after_scores=after_scores,
        promoted_files=promoted,
    )
    return {
        "session_id": session_id,
        "passed": True,
        "scores": after_scores,
        "promoted": promoted,
        "status": "deleted",
    }


@router.get("/log")
async def get_sandbox_log() -> dict[str, Any]:
    log_path = PROJECT_ROOT / "docs" / "SANDBOX_LOG.md"
    if not log_path.exists():
        return {"rows": []}
    lines = log_path.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.startswith("|"):
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) != 7 or parts[0] in {"Session ID", "---"}:
            continue
        rows.append(
            {
                "session_id": parts[0],
                "task": parts[1],
                "model": parts[2],
                "before_scores": parts[3],
                "after_scores": parts[4],
                "files_promoted": parts[5],
                "deleted_at": parts[6],
            }
        )
    return {"rows": rows}
