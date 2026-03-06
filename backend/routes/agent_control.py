from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/agents-control", tags=["agent-control"])


@router.get("/health")
async def routes_health() -> dict[str, str]:
    return {"status": "ok"}
