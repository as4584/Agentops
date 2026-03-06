"""
Gateway Auth Middleware — Bearer token validation for agp_* keys.
=================================================================
Extracts the Authorization header, validates the key against hashed
storage, and attaches gateway_context to request.state.

Returns 401 for missing/malformed credentials without revealing
key validity (timing-safe).
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from backend.gateway.auth import APIKey, get_key_manager, SCOPE_ADMIN


class GatewayContext:
    """Attached to request.state.gateway_context after successful auth."""

    __slots__ = ("key_id", "key_prefix", "owner", "scopes", "quota_rpm",
                 "quota_tpm", "quota_tpd", "quota_daily_usd", "quota_monthly_usd")

    def __init__(self, api_key: APIKey) -> None:
        self.key_id = api_key.key_id
        self.key_prefix = api_key.key_prefix
        self.owner = api_key.owner
        self.scopes = api_key.scopes
        self.quota_rpm = api_key.quota_rpm
        self.quota_tpm = api_key.quota_tpm
        self.quota_tpd = api_key.quota_tpd
        self.quota_daily_usd = api_key.quota_daily_usd
        self.quota_monthly_usd = api_key.quota_monthly_usd


# Paths that bypass gateway auth (health, admin has its own auth)
_PUBLIC_PATHS = frozenset({"/health", "/v1/health"})
_ADMIN_PREFIX = "/admin/"


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 7:
        return auth[7:].strip()
    return None


class GatewayAuthMiddleware(BaseHTTPMiddleware):
    """Validate agp_* API keys on all /v1/* and /admin/* paths."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path

        # Skip auth for public paths
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Only apply to gateway paths
        if not (path.startswith("/v1/") or path.startswith("/admin/")):
            return await call_next(request)

        raw_key = _extract_bearer(request)
        if raw_key is None:
            return _unauthorized("Missing Authorization header")

        api_key = get_key_manager().validate_key(raw_key)
        if api_key is None:
            return _unauthorized("Invalid or expired API key")

        # Admin routes require admin scope
        if path.startswith(_ADMIN_PREFIX) and SCOPE_ADMIN not in api_key.scopes:
            return _forbidden("Insufficient scope for admin endpoint")

        # Attach context
        request.state.gateway_context = GatewayContext(api_key)
        return await call_next(request)


def _unauthorized(detail: str) -> Response:
    import json

    return Response(
        content=json.dumps({"error": {"message": detail, "type": "authentication_error", "code": 401}}),
        status_code=401,
        media_type="application/json",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> Response:
    import json

    return Response(
        content=json.dumps({"error": {"message": detail, "type": "authorization_error", "code": 403}}),
        status_code=403,
        media_type="application/json",
    )


# ---------------------------------------------------------------------------
# FastAPI dependency (alternative to middleware — for explicit injection)
# ---------------------------------------------------------------------------

from fastapi import HTTPException, Request as FRequest


async def require_gateway_auth(request: FRequest) -> GatewayContext:
    """FastAPI dependency: returns GatewayContext or raises 401."""
    ctx = getattr(request.state, "gateway_context", None)
    if ctx is None:
        raw_key = _extract_bearer(request)
        if not raw_key:
            raise HTTPException(status_code=401, detail="Missing Authorization header")
        api_key = get_key_manager().validate_key(raw_key)
        if api_key is None:
            raise HTTPException(status_code=401, detail="Invalid or expired API key")
        ctx = GatewayContext(api_key)
        request.state.gateway_context = ctx
    return ctx


async def require_admin_auth(request: FRequest) -> GatewayContext:
    """FastAPI dependency: requires admin scope."""
    from backend.config_gateway import GATEWAY_ADMIN_SECRET

    # Support a dedicated admin secret header as well
    admin_secret = request.headers.get("X-Admin-Secret", "")
    if GATEWAY_ADMIN_SECRET and admin_secret == GATEWAY_ADMIN_SECRET:
        # Create a synthetic admin context
        from backend.gateway.auth import APIKey, ALL_SCOPES
        import time

        synthetic = APIKey(
            key_id="admin-bootstrap",
            name="Admin Secret",
            owner="system",
            key_hash="",
            key_prefix="admin",
            created_at=time.time(),
            expires_at=0.0,
            disabled=False,
            scopes=ALL_SCOPES,
            quota_rpm=0,
            quota_tpm=0,
            quota_tpd=0,
            quota_daily_usd=0.0,
            quota_monthly_usd=0.0,
        )
        ctx = GatewayContext(synthetic)
        request.state.gateway_context = ctx
        return ctx

    ctx = await require_gateway_auth(request)
    if SCOPE_ADMIN not in ctx.scopes:
        raise HTTPException(status_code=403, detail="Admin scope required")
    return ctx
