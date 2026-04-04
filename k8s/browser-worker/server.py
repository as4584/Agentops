"""Browser-worker FastAPI server.

Exposes a REST API for Agentop agents to drive a headed Chromium browser
running inside the pod. noVNC on port 6080 lets you watch live.

Allowed URL prefixes are controlled by BROWSER_ALLOWED_PREFIXES env var
(comma-separated). Default: LAN ranges only (192.168.x, 10.x, 172.16-31.x).
Never expose this pod to untrusted networks.
"""

from __future__ import annotations

import base64
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from pydantic import BaseModel, field_validator

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWED = (
    "http://192.168.,https://192.168.,"
    "http://10.,https://10.,"
    "http://172.16.,https://172.16.,"
    "http://172.17.,https://172.17.,"
    "http://172.18.,https://172.18.,"
    "http://172.19.,https://172.19.,"
    "http://172.20.,https://172.20.,"
    "http://172.21.,https://172.21.,"
    "http://172.22.,https://172.22.,"
    "http://172.23.,https://172.23.,"
    "http://172.24.,https://172.24.,"
    "http://172.25.,https://172.25.,"
    "http://172.26.,https://172.26.,"
    "http://172.27.,https://172.27.,"
    "http://172.28.,https://172.28.,"
    "http://172.29.,https://172.29.,"
    "http://172.30.,https://172.30.,"
    "http://172.31.,https://172.31."
)

ALLOWED_PREFIXES: list[str] = [
    p.strip() for p in os.environ.get("BROWSER_ALLOWED_PREFIXES", _DEFAULT_ALLOWED).split(",") if p.strip()
]

NAV_TIMEOUT_MS = int(os.environ.get("NAV_TIMEOUT_MS", "30000"))
ACTION_TIMEOUT_MS = int(os.environ.get("ACTION_TIMEOUT_MS", "10000"))

logging.basicConfig(level=logging.INFO, format="[browser-worker] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global browser state (single shared context per pod)
# ---------------------------------------------------------------------------

_browser: Browser | None = None
_context: BrowserContext | None = None
_page: Page | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _browser, _context, _page
    log.info("Launching Chromium (headed on :99)...")
    async with async_playwright() as pw:
        _browser = await pw.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 800},
            ignore_https_errors=True,  # self-signed certs on local routers
        )
        _page = await _context.new_page()
        log.info("Browser ready.")
        yield
        log.info("Shutting down browser.")
        await _browser.close()


app = FastAPI(title="browser-worker", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------

_SECRET_RE = re.compile(r"(?i)(password|token|key|secret|auth)")


def _check_url(url: str) -> None:
    """Raise HTTPException if URL is not in the allowed prefix list."""
    if not any(url.startswith(prefix) for prefix in ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=403,
            detail="URL not in allowed prefixes. Configure BROWSER_ALLOWED_PREFIXES env var.",
        )


def _redact(value: str, field_name: str) -> str:
    return "***REDACTED***" if _SECRET_RE.search(field_name) else value


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class NavigateRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Only http/https URLs allowed")
        return v


class ClickRequest(BaseModel):
    selector: str
    timeout_ms: int = ACTION_TIMEOUT_MS


class FillRequest(BaseModel):
    selector: str
    value: str
    field_name: str = "value"  # used for redaction in logs
    timeout_ms: int = ACTION_TIMEOUT_MS


class SelectRequest(BaseModel):
    selector: str
    option_value: str
    timeout_ms: int = ACTION_TIMEOUT_MS


class EvaluateRequest(BaseModel):
    expression: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _get_page() -> Page:
    if _page is None:
        raise HTTPException(status_code=503, detail="Browser not ready")
    return _page


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "browser": _browser is not None}


@app.post("/navigate")
async def navigate(req: NavigateRequest) -> dict[str, Any]:
    _check_url(req.url)
    page = _get_page()
    log.info(f"navigate → {req.url}")
    response = await page.goto(req.url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    return {"url": page.url, "status": response.status if response else None}


@app.post("/click")
async def click(req: ClickRequest) -> dict[str, Any]:
    page = _get_page()
    log.info(f"click → {req.selector}")
    await page.click(req.selector, timeout=req.timeout_ms)
    return {"clicked": req.selector}


@app.post("/fill")
async def fill(req: FillRequest) -> dict[str, Any]:
    page = _get_page()
    log.info(f"fill → {req.selector} value={_redact(req.value, req.field_name)}")
    await page.fill(req.selector, req.value, timeout=req.timeout_ms)
    return {"filled": req.selector}


@app.post("/select")
async def select(req: SelectRequest) -> dict[str, Any]:
    page = _get_page()
    log.info(f"select → {req.selector} option={req.option_value}")
    await page.select_option(req.selector, req.option_value, timeout=req.timeout_ms)
    return {"selected": req.selector, "option": req.option_value}


@app.post("/screenshot")
async def screenshot() -> dict[str, Any]:
    page = _get_page()
    data = await page.screenshot(type="png")
    encoded = base64.b64encode(data).decode()
    log.info(f"screenshot taken ({len(data)} bytes)")
    return {"screenshot_b64": encoded, "url": page.url}


@app.post("/evaluate")
async def evaluate(req: EvaluateRequest) -> dict[str, Any]:
    page = _get_page()
    log.info(f"evaluate → {req.expression[:80]}")
    result = await page.evaluate(req.expression)
    return {"result": result}


@app.post("/back")
async def go_back() -> dict[str, Any]:
    page = _get_page()
    await page.go_back(timeout=NAV_TIMEOUT_MS)
    return {"url": page.url}


@app.get("/url")
async def current_url() -> dict[str, Any]:
    page = _get_page()
    return {"url": page.url, "title": await page.title()}
