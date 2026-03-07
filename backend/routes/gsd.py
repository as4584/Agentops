"""
GSD Routes — /api/gsd/*

All five GSD workflow commands are exposed here.
Heavy logic lives in GSDAgent (backend/agents/gsd_agent.py);
these routes are thin wrappers that validate input, delegate, and return.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.utils import logger

router = APIRouter(prefix="/api/gsd", tags=["gsd"])


# ---------------------------------------------------------------------------
# Request / response bodies
# ---------------------------------------------------------------------------

class MapCodebaseRequest(BaseModel):
    workspace_root: str = "."


class PlanPhaseRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=2000)


class ExecutePhaseRequest(BaseModel):
    dry_run: bool = False


class QuickRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    full: bool = False


class VerifyWorkRequest(BaseModel):
    phase: int | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/map-codebase")
async def map_codebase(req: MapCodebaseRequest):
    """
    Spawn 4 parallel analysis workers and produce:
      docs/gsd/STACK.md, ARCHITECTURE.md, CONVENTIONS.md, CONCERNS.md
    """
    try:
        from backend.agents.gsd_agent import GSDAgent
        agent = GSDAgent()
        result = await agent.map_codebase(req.workspace_root)
        return {
            "status": "ok",
            "generated_at": result.generated_at.isoformat(),
            "docs": ["docs/gsd/STACK.md", "docs/gsd/ARCHITECTURE.md",
                     "docs/gsd/CONVENTIONS.md", "docs/gsd/CONCERNS.md"],
        }
    except Exception as exc:
        logger.error(f"GSD map-codebase error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/plan-phase/{phase_n}")
async def plan_phase(phase_n: int, req: PlanPhaseRequest):
    """
    Research → draft plan → verify with GatekeeperAgent (up to 2 revisions).
    Writes backend/memory/gsd/phases/{n}/PLAN.md on success.
    """
    if phase_n < 1:
        raise HTTPException(status_code=422, detail="phase_n must be >= 1")
    try:
        from backend.agents.gsd_agent import GSDAgent
        agent = GSDAgent()
        plan = await agent.plan_phase(phase_n, req.description)
        return {
            "status": "ok" if not plan.gatekeeper_violations else "planned_with_violations",
            "phase": plan.phase,
            "title": plan.title,
            "task_count": len(plan.tasks),
            "waves": max((t.wave for t in plan.tasks), default=1),
            "gatekeeper_violations": plan.gatekeeper_violations,
            "plan_path": f"backend/memory/gsd/phases/{phase_n}/PLAN.md",
        }
    except Exception as exc:
        logger.error(f"GSD plan-phase error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/execute-phase/{phase_n}")
async def execute_phase(phase_n: int, req: ExecutePhaseRequest):
    """
    Read the saved PLAN.md for phase {n}, resolve wave order, execute in parallel
    batches.  Gatekeeper runs after all waves; failure → phase status = 'failed'.
    """
    if phase_n < 1:
        raise HTTPException(status_code=422, detail="phase_n must be >= 1")
    try:
        from backend.agents.gsd_agent import GSDAgent
        agent = GSDAgent()
        result = await agent.execute_phase(phase_n, dry_run=req.dry_run)
        return {
            "status": result.status.value,
            "phase": result.phase,
            "waves_completed": result.waves_completed,
            "gatekeeper_approved": result.gatekeeper_approved,
            "gatekeeper_violations": result.gatekeeper_violations,
        }
    except Exception as exc:
        logger.error(f"GSD execute-phase error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/quick")
async def quick(req: QuickRequest):
    """
    Ad-hoc task with GSD guarantees (state tracking, optional commit).
    Skips PLAN.md ceremony — good for small changes and hot-path iterations.
    """
    try:
        from backend.agents.gsd_agent import GSDAgent
        agent = GSDAgent()
        result = await agent.quick(req.prompt, full=req.full)
        return {
            "status": "ok",
            "response": result.response,
            "committed": result.committed,
            "timestamp": result.timestamp.isoformat(),
        }
    except Exception as exc:
        logger.error(f"GSD quick error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/verify-work")
async def verify_work(req: VerifyWorkRequest):
    """
    Conversational UAT: reads last execution log, generates a checklist,
    runs health/db checks where possible, returns a gap report.
    """
    try:
        from backend.agents.gsd_agent import GSDAgent
        agent = GSDAgent()
        report = await agent.verify_work(phase_n=req.phase)
        return {
            "status": "ok",
            "phase": report.phase,
            "passed":       len(report.passed),
            "failed":       len(report.failed),
            "unverifiable": len(report.unverifiable),
            "report": {
                "passed":       [{"description": i.description, "detail": i.detail} for i in report.passed],
                "failed":       [{"description": i.description, "detail": i.detail} for i in report.failed],
                "unverifiable": [{"description": i.description, "detail": i.detail} for i in report.unverifiable],
            },
        }
    except Exception as exc:
        logger.error(f"GSD verify-work error: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


# ---- read-only helpers ----------------------------------------------------

@router.get("/state")
async def get_state():
    """Return current GSD STATE.md content as structured JSON."""
    from backend.database.gsd_store import gsd_store
    state = gsd_store.load_state()
    return state.model_dump()


@router.get("/map-docs")
async def get_map_docs():
    """Return cached map-codebase docs (if they exist)."""
    from backend.database.gsd_store import gsd_store
    result = gsd_store.load_map_docs()
    if result is None:
        return {"status": "not_generated", "docs": None}
    return {"status": "ok", "generated_at": result.generated_at.isoformat(),
            "stack": result.stack, "architecture": result.architecture,
            "conventions": result.conventions, "concerns": result.concerns}


@router.get("/phases")
async def list_phases():
    """List all phases with their plans."""
    from backend.database.gsd_store import gsd_store
    phases = gsd_store.list_phases()
    plans = []
    for n in phases:
        plan = gsd_store.load_plan(n)
        if plan:
            plans.append({
                "phase": plan.phase,
                "title": plan.title,
                "status": plan.status.value,
                "task_count": len(plan.tasks),
            })
    return {"phases": plans}
