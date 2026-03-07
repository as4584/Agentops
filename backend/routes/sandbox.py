from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.agents.gatekeeper_agent import GatekeeperAgent
from backend.config import (
    LOCAL_LLM_REQUIRED_CHECKS,
    PROJECT_ROOT,
    SANDBOX_ENFORCEMENT_ENABLED,
)
from sandbox.session_manager import SandboxSession, list_active_sessions

router = APIRouter(prefix="/sandbox", tags=["sandbox"])
_gatekeeper = GatekeeperAgent()


class SandboxCreateRequest(BaseModel):
    task: str
    model: str = "local"
    session_id: str | None = None


class SandboxCreateResponse(BaseModel):
    session_id: str
    path: str
    task: str
    model: str
    container_id: str | None = None
    container_name: str | None = None
    container_status: str | None = None


class SandboxPromoteRequest(BaseModel):
    files: list[str] = Field(default_factory=list)


class SandboxFinalizeRequest(BaseModel):
    files: list[str] = Field(default_factory=list)
    before_scores: dict[str, Any] | None = None
    after_scores: dict[str, Any] | None = None


class QualityChecks(BaseModel):
    tests_ok: bool = False
    playwright_ok: bool = False
    lighthouse_mobile_ok: bool = False


class SandboxStageRequest(BaseModel):
    files: list[str] = Field(default_factory=list)


class SandboxReleaseRequest(BaseModel):
    files: list[str] = Field(default_factory=list)
    checks: QualityChecks
    before_scores: dict[str, Any] | None = None
    after_scores: dict[str, Any] | None = None


class LhciCheckRequest(BaseModel):
    summary_json_path: str
    files_to_promote: list[str] = Field(default_factory=list)
    before_scores: dict[str, Any] | None = None


def _session(session_id: str) -> SandboxSession:
    session = SandboxSession(
        project_root=PROJECT_ROOT,
        task="managed-session",
        model="local",
        session_id=session_id,
    )
    try:
        meta = session.read_meta()
        session.task = str(meta.get("task", session.task))
        session.model = str(meta.get("model", session.model))
    except FileNotFoundError:
        pass
    return session


def _missing_required_checks(checks: QualityChecks) -> list[str]:
    missing: list[str] = []
    checks_map = checks.model_dump()
    for check_name in LOCAL_LLM_REQUIRED_CHECKS:
        if checks_map.get(check_name) is not True:
            missing.append(check_name)
    return missing


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
    meta = session.create()
    return SandboxCreateResponse(
        session_id=session.session_id,
        path=str(session.root),
        task=body.task,
        model=body.model,
        container_id=meta.get("container_id"),
        container_name=meta.get("container_name"),
        container_status=meta.get("container_status"),
    )


@router.post("/{session_id}/promote")
async def promote_files(session_id: str, body: SandboxPromoteRequest) -> dict[str, Any]:
    session = _session(session_id)
    if SANDBOX_ENFORCEMENT_ENABLED and session.is_local_model:
        raise HTTPException(
            status_code=403,
            detail="Local-model sessions must use /sandbox/{session_id}/stage and /sandbox/{session_id}/release",
        )
    try:
        promoted = session.promote(body.files)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, "promoted": promoted}


@router.post("/{session_id}/stage")
async def stage_files(session_id: str, body: SandboxStageRequest) -> dict[str, Any]:
    session = _session(session_id)
    try:
        staged = session.stage_to_playbox(body.files)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"session_id": session_id, "staged": staged, "playbox": str(session.playbox)}


@router.post("/{session_id}/release")
async def release_files(session_id: str, body: SandboxReleaseRequest) -> dict[str, Any]:
    session = _session(session_id)
    if SANDBOX_ENFORCEMENT_ENABLED and not session.is_local_model:
        raise HTTPException(status_code=400, detail="Release endpoint is reserved for local-model sandbox sessions")

    missing_checks = _missing_required_checks(body.checks)
    if missing_checks:
        raise HTTPException(
            status_code=412,
            detail={
                "message": "Release blocked: required quality checks failed or missing",
                "missing_checks": missing_checks,
            },
        )

    payload: dict[str, Any] = {
        "files_changed": body.files,
        "source_model": session.model,
        "sandbox_session_id": session_id,
        "staged_in_playbox": True,
        "tests_ok": body.checks.tests_ok,
        "playwright_ok": body.checks.playwright_ok,
        "lighthouse_mobile_ok": body.checks.lighthouse_mobile_ok,
        "syntax_ok": body.checks.tests_ok,
        "lighthouse_ok": body.checks.lighthouse_mobile_ok,
        "secrets_ok": True,
    }
    review = _gatekeeper.review_mutation(payload)
    if not review.approved:
        raise HTTPException(
            status_code=412,
            detail={"message": "Release blocked by gatekeeper", "violations": review.violations},
        )

    try:
        released = session.release_from_playbox(body.files)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    session.destroy(
        before_scores=body.before_scores,
        after_scores=body.after_scores,
        promoted_files=released,
    )
    return {
        "session_id": session_id,
        "released": released,
        "status": "deleted",
        "checks_required": list(LOCAL_LLM_REQUIRED_CHECKS),
    }


@router.post("/{session_id}/finalize")
async def finalize_session(session_id: str, body: SandboxFinalizeRequest) -> dict[str, Any]:
    session = _session(session_id)
    if SANDBOX_ENFORCEMENT_ENABLED and session.is_local_model:
        raise HTTPException(
            status_code=403,
            detail="Local-model sessions must finalize through /sandbox/{session_id}/release",
        )
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


class SandboxExecRequest(BaseModel):
    command: list[str]
    timeout: int = Field(default=30, ge=1, le=300)


@router.post("/{session_id}/exec")
async def exec_in_session(session_id: str, body: SandboxExecRequest) -> dict[str, Any]:
    """Execute a command inside the session container (or locally if not containerised)."""
    if not body.command:
        raise HTTPException(status_code=422, detail="command must be a non-empty list")

    session = _session(session_id)
    try:
        result = session.exec_in_container(body.command, timeout=body.timeout)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {"session_id": session_id, **result}


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
