"""OAuth callback routes for social media platform authorization.

TikTok Sandbox Setup:
  Website URL (app setting):  http://localhost:3007/social
  Redirect URI (app setting): http://localhost:8000/auth/tiktok/callback

Flow:
  1. Visit http://localhost:8000/auth/tiktok/login  → redirects to TikTok OAuth page
  2. User approves → TikTok redirects to /auth/tiktok/callback?code=...
  3. Backend exchanges code for access_token + open_id
  4. Tokens stored in backend/memory/social_media/tiktok_tokens.json
  5. Copy token values into .env: TIKTOK_ACCESS_TOKEN + TIKTOK_OPEN_ID
"""

from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter(prefix="/auth", tags=["oauth"])

TIKTOK_TOKENS_PATH = Path("backend/memory/social_media/tiktok_tokens.json")

# In-memory CSRF state store (single-process, dev use only)
_csrf_states: dict[str, float] = {}
_CSRF_TTL = 600  # 10 minutes


def _ensure_dir() -> None:
    Path("backend/memory/social_media").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# TikTok OAuth
# ---------------------------------------------------------------------------


@router.get("/tiktok/login")
async def tiktok_login() -> RedirectResponse:
    """Initiate TikTok OAuth flow. Visit this URL in a browser to authorize."""
    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    if not client_key:
        raise HTTPException(
            status_code=500,
            detail="TIKTOK_CLIENT_KEY not set in .env — add it before starting OAuth",
        )

    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8000/auth/tiktok/callback")
    state = secrets.token_urlsafe(16)
    _csrf_states[state] = time.time()

    # Purge expired states
    expired = [k for k, ts in _csrf_states.items() if time.time() - ts > _CSRF_TTL]
    for k in expired:
        del _csrf_states[k]

    url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        "&response_type=code"
        "&scope=video.publish,video.list"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )
    return RedirectResponse(url=url)


@router.get("/tiktok/callback")
async def tiktok_callback(
    code: str = Query(...),
    state: str = Query(...),
    scopes: str = Query(default=""),
    error: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
) -> HTMLResponse:
    """TikTok OAuth callback. Exchanges auth code for access token and saves it."""
    if error:
        return HTMLResponse(
            content=_html_result(
                success=False,
                title="TikTok Authorization Failed",
                message=f"Error: {error}<br>{error_description or ''}",
            ),
            status_code=400,
        )

    # CSRF check
    if state not in _csrf_states:
        return HTMLResponse(
            content=_html_result(
                success=False,
                title="Invalid State",
                message="CSRF state mismatch or session expired. Try <a href='/auth/tiktok/login'>logging in again</a>.",
            ),
            status_code=400,
        )
    del _csrf_states[state]

    client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
    client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
    redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8000/auth/tiktok/callback")

    if not client_key or not client_secret:
        return HTMLResponse(
            content=_html_result(
                success=False,
                title="Missing Credentials",
                message="TIKTOK_CLIENT_KEY or TIKTOK_CLIENT_SECRET not set in .env",
            ),
            status_code=500,
        )

    # Exchange code for token
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://open.tiktokapis.com/v2/oauth/token/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )

    if resp.status_code != 200:
        return HTMLResponse(
            content=_html_result(
                success=False,
                title="Token Exchange Failed",
                message=f"TikTok returned HTTP {resp.status_code}: {resp.text}",
            ),
            status_code=502,
        )

    data = resp.json()
    if data.get("error"):
        return HTMLResponse(
            content=_html_result(
                success=False,
                title="Token Exchange Error",
                message=f"{data.get('error')}: {data.get('error_description', '')}",
            ),
            status_code=400,
        )

    access_token = data.get("access_token", "")
    refresh_token = data.get("refresh_token", "")
    open_id = data.get("open_id", "")
    expires_in = data.get("expires_in", 0)
    scope = data.get("scope", "")

    # Persist tokens
    _ensure_dir()
    token_data = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "open_id": open_id,
        "scope": scope,
        "expires_in": expires_in,
        "obtained_at": int(time.time()),
        "expires_at": int(time.time()) + expires_in,
    }
    TIKTOK_TOKENS_PATH.write_text(json.dumps(token_data, indent=2))

    return HTMLResponse(
        content=_html_result(
            success=True,
            title="TikTok Authorization Successful",
            message=f"""
            <p>Access token obtained and saved to <code>backend/memory/social_media/tiktok_tokens.json</code></p>
            <p><strong>Now add these to your <code>.env</code> file:</strong></p>
            <pre style="background:#1a1a2e;padding:16px;border-radius:8px;text-align:left;overflow-x:auto">
TIKTOK_ACCESS_TOKEN={access_token}
TIKTOK_OPEN_ID={open_id}
TIKTOK_REFRESH_TOKEN={refresh_token}</pre>
            <p>Scopes granted: <code>{scope}</code></p>
            <p>Token expires in: <code>{expires_in}s</code> ({expires_in // 3600}h)</p>
            <p><a href="http://localhost:3007/social" style="color:#a78bfa">→ Open Social Media Dashboard</a></p>
            """,
        )
    )


@router.get("/tiktok/status")
async def tiktok_token_status() -> dict:
    """Check saved TikTok token status without exposing the token value."""
    if not TIKTOK_TOKENS_PATH.exists():
        return {"status": "no_token", "message": "No token saved yet. Visit /auth/tiktok/login"}

    data = json.loads(TIKTOK_TOKENS_PATH.read_text())
    now = int(time.time())
    expires_at = data.get("expires_at", 0)
    remaining = expires_at - now

    return {
        "status": "valid" if remaining > 0 else "expired",
        "open_id": data.get("open_id", ""),
        "scope": data.get("scope", ""),
        "expires_in_seconds": remaining,
        "expires_in_hours": round(remaining / 3600, 1),
        "obtained_at": data.get("obtained_at"),
        "has_env_token": bool(os.getenv("TIKTOK_ACCESS_TOKEN")),
    }


# ---------------------------------------------------------------------------
# HTML helper
# ---------------------------------------------------------------------------


def _html_result(success: bool, title: str, message: str) -> str:
    color = "#22c55e" if success else "#ef4444"
    icon = "✅" if success else "❌"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — Agentop</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f0f1a;
      color: #e2e8f0;
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .card {{
      background: #1a1a2e;
      border: 1px solid #2d2d4e;
      border-radius: 12px;
      padding: 40px;
      max-width: 600px;
      width: 100%;
      text-align: center;
    }}
    .icon {{ font-size: 48px; margin-bottom: 16px; }}
    h1 {{ font-size: 24px; font-weight: 700; color: {color}; margin-bottom: 16px; }}
    p {{ color: #94a3b8; line-height: 1.6; margin-bottom: 12px; }}
    pre {{ font-size: 13px; line-height: 1.5; white-space: pre-wrap; word-break: break-all; }}
    code {{ background: #2d2d4e; padding: 2px 6px; border-radius: 4px; font-size: 13px; }}
    a {{ color: #a78bfa; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">{icon}</div>
    <h1>{title}</h1>
    {message}
  </div>
</body>
</html>"""
