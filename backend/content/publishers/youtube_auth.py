"""
backend/content/publishers/youtube_auth.py
──────────────────────────────────────────
YouTube OAuth2 authentication flow using Playwright browser automation.

The agent opens the Google OAuth consent screen, the user signs in manually,
and on redirect the auth code is captured and exchanged for tokens which are
saved to disk. From then on PublisherAgent can upload without interaction.

Usage:
  Called via POST /content/auth/youtube — opens a browser window.
  No API keys in code. All credentials read from environment.

Required env vars:
  YOUTUBE_CLIENT_ID       — from Google Cloud Console
  YOUTUBE_CLIENT_SECRET   — from Google Cloud Console

Token stored at:
  data/agents/content_publish/youtube_token.json
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from backend.config import MEMORY_DIR
from backend.utils import logger

TOKEN_PATH = MEMORY_DIR / "content_publish" / "youtube_token.json"
TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)

SCOPES = "https://www.googleapis.com/auth/youtube.upload"
REDIRECT_URI = "http://localhost:8765"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def is_authenticated() -> bool:
    """Return True if a valid token file exists."""
    if not TOKEN_PATH.exists():
        return False
    try:
        token = json.loads(TOKEN_PATH.read_text())
        return bool(token.get("access_token") or token.get("refresh_token"))
    except Exception:
        return False


async def run_auth_flow() -> dict:
    """
    Launch Playwright browser for the user to complete OAuth.
    Captures the auth code from the redirect URL and exchanges it for tokens.
    Returns the token dict on success.
    """
    client_id = os.getenv("YOUTUBE_CLIENT_ID")
    client_secret = os.getenv("YOUTUBE_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise RuntimeError(
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET must be set in .env\n"
            "Get them from: https://console.cloud.google.com/apis/credentials"
        )

    # Build the OAuth URL
    params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",  # get refresh_token
        "prompt": "consent",
    }
    auth_url = AUTH_URL + "?" + urllib.parse.urlencode(params)

    logger.info("[YouTubeAuth] Opening browser for OAuth consent...")
    logger.info(f"[YouTubeAuth] Auth URL: {auth_url}")

    # Launch browser — user signs in, we wait for redirect
    auth_code = await _wait_for_auth_code(auth_url)

    if not auth_code:
        raise RuntimeError("OAuth flow cancelled or timed out")

    # Exchange code for tokens
    tokens = _exchange_code(auth_code, client_id, client_secret)

    # Save to disk
    TOKEN_PATH.write_text(json.dumps(tokens, indent=2))
    logger.info(f"[YouTubeAuth] Tokens saved to {TOKEN_PATH}")

    return tokens


async def _wait_for_auth_code(auth_url: str) -> str | None:
    """
    Start a temporary local HTTP server on port 8765 to catch the OAuth redirect.
    Launch Playwright browser pointed at the auth URL.
    Returns the extracted auth code when the user completes login.
    """
    import asyncio
    from http.server import BaseHTTPRequestHandler, HTTPServer

    captured_code: list[str] = []

    class _RedirectHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [None])[0]
            if code:
                captured_code.append(code)
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<html><body><h2>Authenticated! You can close this window.</h2>"
                    b"<p>Return to Agentop.</p></body></html>"
                )
            else:
                self.send_response(400)
                self.end_headers()

        def log_message(self, *args) -> None:  # silence HTTP logs
            pass

    server = HTTPServer(("localhost", 8765), _RedirectHandler)
    server.timeout = 300  # 5 minute window

    # Launch browser in background
    browser_task = asyncio.create_task(_open_browser(auth_url))

    # Poll for redirect (blocking but with timeout)
    loop = asyncio.get_event_loop()
    start = loop.time()
    while not captured_code:
        await loop.run_in_executor(None, server.handle_request)
        if loop.time() - start > 300:
            break

    server.server_close()
    browser_task.cancel()

    return captured_code[0] if captured_code else None


async def _open_browser(url: str) -> None:
    """Open a Playwright Chromium window at the given URL."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()
            await page.goto(url)
            # Keep browser open until task is cancelled
            import asyncio
            await asyncio.sleep(360)
            await browser.close()
    except ImportError:
        # Playwright not installed — fallback to system browser
        import subprocess
        subprocess.Popen(["xdg-open", url])
        logger.info(f"[YouTubeAuth] Opened system browser: {url}")
    except Exception as e:
        logger.warning(f"[YouTubeAuth] Browser open error: {e}")


def _exchange_code(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange OAuth authorization code for access + refresh tokens."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=15) as resp:
        tokens = json.loads(resp.read().decode())

    if "error" in tokens:
        raise RuntimeError(f"Token exchange failed: {tokens['error']} — {tokens.get('error_description', '')}")

    return tokens
