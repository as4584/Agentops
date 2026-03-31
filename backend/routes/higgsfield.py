"""
Higgsfield Routes — /api/higgsfield/*

REST endpoints for the Higgsfield video production system.
Heavy logic lives in the higgsfield_playwright_server (port 8812) and
higgsfield_agent; these routes are thin wrappers for dashboard/API consumers.
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.config import HF_MCP_PORT  # type: ignore[attr-defined]
from backend.database.higgsfield_store import HighgsfieldStore
from backend.utils import logger

router = APIRouter(prefix="/api/higgsfield", tags=["higgsfield"])

_store = HighgsfieldStore()
_HF_MCP = f"http://127.0.0.1:{HF_MCP_PORT}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _call_mcp(tool: str, body: dict) -> dict:
    """Forward a tool call to the Higgsfield MCP server."""
    try:
        async with httpx.AsyncClient(timeout=960) as client:
            resp = await client.post(f"{_HF_MCP}/tools/{tool}", json=body)
            resp.raise_for_status()
            return resp.json()
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=(
                "Higgsfield MCP server is not running. "
                "Start it with: python -m backend.mcp.higgsfield_playwright_server"
            ),
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)


# ---------------------------------------------------------------------------
# Character endpoints
# ---------------------------------------------------------------------------


@router.get("/characters")
async def list_characters():
    """List all registered characters."""
    return _store.list_characters()


@router.get("/characters/{character_id}")
async def get_character(character_id: str):
    char = _store.get_character(character_id)
    if char is None:
        raise HTTPException(status_code=404, detail=f"Character '{character_id}' not found")
    return char


class CreateSoulIdRequest(BaseModel):
    character_id: str
    image_path: str
    character_name: str


@router.post("/characters/{character_id}/soul-id")
async def create_soul_id(character_id: str, req: CreateSoulIdRequest):
    """Navigate to Higgsfield and create a Soul ID for the character."""
    logger.info(f"[higgsfield] Creating Soul ID for character={character_id}")
    result = await _call_mcp(
        "hf_create_soul_id",
        {
            "character_id": character_id,
            "image_path": req.image_path,
            "character_name": req.character_name,
        },
    )
    return result


# ---------------------------------------------------------------------------
# Video generation endpoints
# ---------------------------------------------------------------------------


class SubmitVideoRequest(BaseModel):
    character_id: str
    soul_id_url: str
    model: str = Field(..., description="e.g. kling_3_0, veo_3_1, hailuo_02")
    prompt: str = Field(..., min_length=10, max_length=1000)
    duration_s: int = Field(5, ge=2, le=30)
    campaign: str = "untagged"
    scene_id: str = ""


@router.post("/generate")
async def generate_video(req: SubmitVideoRequest):
    """Queue a video generation job on Higgsfield."""
    logger.info(f"[higgsfield] Submitting video: character={req.character_id} model={req.model}")
    result = await _call_mcp("hf_submit_video", req.model_dump())
    return result


class PollRequest(BaseModel):
    job_url: str
    timeout_s: int = 900


@router.post("/poll")
async def poll_job(req: PollRequest):
    """Poll a queued video job until complete."""
    result = await _call_mcp("hf_poll_result", req.model_dump())
    return result


# ---------------------------------------------------------------------------
# Run history endpoints
# ---------------------------------------------------------------------------


@router.get("/runs")
async def list_runs(character_id: str | None = None, limit: int = 50):
    """List generation runs, optionally filtered by character."""
    return _store.list_runs(character_id=character_id, limit=limit)


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = _store.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return run


# ---------------------------------------------------------------------------
# MCP server health
# ---------------------------------------------------------------------------


@router.get("/mcp/health")
async def mcp_health():
    """Check if the Higgsfield MCP Playwright server is alive."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{_HF_MCP}/health")
            return resp.json()
    except httpx.ConnectError:
        return {"status": "offline", "message": "MCP server not running on port " + str(HF_MCP_PORT)}


@router.post("/session/login")
async def login(force: bool = False):
    """Restore or establish the Higgsfield browser session."""
    result = await _call_mcp("hf_login", {"force_relogin": force})
    return result


@router.post("/session/navigate")
async def navigate(path: str):
    """Navigate to a path on app.higgsfield.ai (billing URLs are blocked)."""
    result = await _call_mcp("hf_navigate", {"path": path})
    return result
