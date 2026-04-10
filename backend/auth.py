from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from backend.config import API_SECRET


def build_auth_headers() -> dict[str, str]:
    """Return bearer auth headers for internal backend clients."""
    if not API_SECRET:
        return {}
    return {"Authorization": f"Bearer {API_SECRET}"}


async def verify_api_request(request: Request) -> None:
    """
    Verify Bearer token when API_SECRET is configured.
    EventSource clients cannot send custom headers, so a ?token= query
    parameter is accepted for streaming endpoints only.
    """
    if not API_SECRET:
        return

    auth = request.headers.get("Authorization", "")
    raw_key: str | None = None
    if auth.startswith("Bearer ") and len(auth) > 7:
        raw_key = auth[7:].strip()
    elif request.url.path in ("/stream/activity",):
        raw_key = request.query_params.get("token")

    if not raw_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if not hmac.compare_digest(raw_key, API_SECRET):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


async def require_api_auth(request: Request) -> None:
    """FastAPI dependency wrapper for route-level auth."""
    await verify_api_request(request)
