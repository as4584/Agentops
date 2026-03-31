"""
Higgsfield Playwright MCP Server
=================================
Provides 6 browser tools that let agents operate Higgsfield.ai through a headed
(visible) Chromium browser.  Runs as a standalone FastAPI service on port 8812.

Tools:
  hf_login          — Restore or establish a Higgsfield session from saved cookies
  hf_navigate       — Navigate to a Higgsfield page (safety: blocks purchase URLs)
  hf_create_soul_id — Upload a character reference image and create a Soul ID
  hf_submit_video   — Configure and queue a video generation job
  hf_poll_result    — Poll until a video job completes (or times out)
  hf_log_evidence   — Capture a screenshot + structured log entry

Security invariants enforced here:
  - PurchaseBlockedError raised + alert_dispatch called for any billing URL
  - Only higgsfield.ai URLs are accepted by hf_navigate
  - Cookies are stored in data/higgsfield/.session_cookies.json (gitignored)
  - HIGGSFIELD_HEADLESS=true env var enables future headless mode
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Optional Playwright import — degrade gracefully if not installed
# ---------------------------------------------------------------------------
try:
    from playwright.async_api import Browser, BrowserContext, Page, async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    from typing import Any as _Any

    async_playwright: _Any = None  # type: ignore[no-redef]  # noqa: N816 — runtime fallback only
    PLAYWRIGHT_AVAILABLE = False
    Browser = Any  # type: ignore[misc,assignment]
    Page = Any  # type: ignore[misc,assignment]
    BrowserContext = Any  # type: ignore[misc,assignment]

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PORT = int(os.getenv("HF_MCP_PORT", "8812"))
HEADLESS = os.getenv("HIGGSFIELD_HEADLESS", "false").lower() == "true"
HF_BASE_URL = "https://higgsfield.ai"
COOKIE_FILE = Path("data/higgsfield/.session_cookies.json")
EVIDENCE_DIR = Path("data/higgsfield/evidence")
POLL_INTERVAL_S = 10
POLL_TIMEOUT_S = 900  # 15 min max wait

# Purchase/billing URLs that agents must NEVER navigate to
_BLOCKED_PATH_FRAGMENTS = [
    "/pricing",
    "/checkout",
    "/billing",
    "/upgrade",
    "/subscribe",
    "/payment",
    "/plans",
    "/credit",
    "/buy",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PurchaseBlockedError(RuntimeError):
    """Raised when an agent attempts to navigate to a purchase/billing URL."""


# ---------------------------------------------------------------------------
# Shared browser state (single global context per server process)
# ---------------------------------------------------------------------------

_playwright_handle: Any = None
_browser: Any = None
_context: Any = None
_page: Any = None


async def _get_page() -> Any:
    """Return the active page, launching browser if needed."""
    global _playwright_handle, _browser, _context, _page

    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed. Run: pip install playwright && playwright install chromium")

    if _page is None:
        _playwright_handle = await async_playwright().start()
        _browser = await _playwright_handle.chromium.launch(
            headless=HEADLESS,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        _context = await _browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        _page = await _context.new_page()

    return _page


async def _load_cookies() -> bool:
    """Load saved cookies into the browser context. Returns True if cookies loaded."""
    global _context
    if _context is None:
        return False
    if not COOKIE_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text())
        await _context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def _save_cookies() -> None:
    """Persist current browser cookies to disk."""
    global _context
    if _context is None:
        return
    cookies = await _context.cookies()
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_FILE.write_text(json.dumps(cookies, indent=2))


def _check_purchase_block(url: str) -> None:
    """Raise PurchaseBlockedError if the URL matches a blocked billing path."""
    url_lower = url.lower()
    for fragment in _BLOCKED_PATH_FRAGMENTS:
        if fragment in url_lower:
            raise PurchaseBlockedError(
                f"PURCHASE BLOCKED — agents may not navigate to: {url!r} "
                f"(matched blocked fragment: {fragment!r}). "
                "Contact a human to handle billing."
            )


async def _dispatch_alert(message: str) -> None:
    """Write a structured alert to the shared events log (mirrors alert_dispatch tool)."""
    try:
        events_path = Path("data/shared_events.jsonl")
        events_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": "CRITICAL",
            "source": "hf_mcp_server",
            "message": message,
        }
        with events_path.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Never let alert failure crash the main flow


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Higgsfield MCP Server", version="1.0.0")


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    force_relogin: bool = False


class NavigateRequest(BaseModel):
    path: str  # relative path on higgsfield.ai, e.g. "/characters"


class CreateSoulIdRequest(BaseModel):
    character_id: str  # e.g. "char_xpel"
    character_name: str  # display name in Higgsfield UI
    image_folder: str = ""  # project-root-relative folder path — uploads ALL images inside
    image_path: str = ""  # single image path (fallback if image_folder not set)
    model_preference: str = "soul_2"  # "soul_2", "soul_1", "auto" (first available non-Soul-2)


class SubmitVideoRequest(BaseModel):
    character_id: str
    soul_id_url: str  # Higgsfield character URL to use
    model: str  # e.g. "kling_3_0", "veo_3_1", "hailuo_02"
    prompt: str
    duration_s: int = 5
    campaign: str = "untagged"
    scene_id: str = ""


class PollResultRequest(BaseModel):
    job_url: str  # Higgsfield URL of the queued job
    timeout_s: int = POLL_TIMEOUT_S


class LogEvidenceRequest(BaseModel):
    run_id: str
    label: str = "evidence"  # short label for the screenshot filename
    notes: str = ""


class ClickRequest(BaseModel):
    selector: str  # CSS selector or text selector e.g. "button:has-text('Continue with Google')"
    timeout_ms: int = 5000
    force: bool = False  # bypass visibility/stability checks (use when element is found but "not visible")
    js: bool = False  # use JS dispatchEvent click instead of Playwright action


# ---------------------------------------------------------------------------
# Tool: hf_click  (utility — click any visible element)
# ---------------------------------------------------------------------------


@app.post("/tools/hf_click")
async def hf_click(req: ClickRequest) -> JSONResponse:
    """Click an element on the current page by CSS selector."""
    try:
        page = await _get_page()
        if req.js:
            el = await page.query_selector(req.selector)
            if not el:
                raise RuntimeError(f"No element matched: {req.selector}")
            await el.dispatch_event("click")
        else:
            await page.click(req.selector, timeout=req.timeout_ms, force=req.force)
        await asyncio.sleep(1)
        await _save_cookies()
        return JSONResponse({"status": "ok", "clicked": req.selector, "url": page.url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_click failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_eval  (run JS on the page and return the result)
# ---------------------------------------------------------------------------


class EvalRequest(BaseModel):
    script: str  # JS expression — evaluated as: await page.evaluate(script)
    truncate: int = 4000  # max chars of result to return


@app.post("/tools/hf_eval")
async def hf_eval(req: EvalRequest) -> JSONResponse:
    """Evaluate arbitrary JavaScript in the browser context and return the result."""
    try:
        page = await _get_page()
        result = await page.evaluate(req.script)
        text = json.dumps(result) if not isinstance(result, str) else result
        return JSONResponse({"status": "ok", "result": text[: req.truncate]})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_eval failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_set_files  (set files on a file input)
# ---------------------------------------------------------------------------


class SetFilesRequest(BaseModel):
    selector: str = "input[type='file']"
    file_paths: list[str]  # absolute or project-root-relative paths


@app.post("/tools/hf_set_files")
async def hf_set_files(req: SetFilesRequest) -> JSONResponse:
    """Set one or more files on a hidden file input."""
    root = Path(__file__).parent.parent.parent
    resolved = []
    for p in req.file_paths:
        fp = Path(p)
        if not fp.is_absolute():
            fp = root / p
        if not fp.exists():
            raise HTTPException(status_code=400, detail=f"File not found: {fp}")
        resolved.append(str(fp))
    try:
        page = await _get_page()
        await page.set_input_files(req.selector, resolved)
        await asyncio.sleep(2)
        return JSONResponse({"status": "ok", "files_set": len(resolved), "url": page.url})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_set_files failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_fill  (fill a text input)
# ---------------------------------------------------------------------------


class FillRequest(BaseModel):
    selector: str
    value: str
    timeout_ms: int = 5000


@app.post("/tools/hf_fill")
async def hf_fill(req: FillRequest) -> JSONResponse:
    """Fill a text input with a value."""
    try:
        page = await _get_page()
        await page.fill(req.selector, req.value, timeout=req.timeout_ms)
        return JSONResponse({"status": "ok", "selector": req.selector, "value": req.value})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_fill failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_save_session  (save cookies after manual login)
# ---------------------------------------------------------------------------


@app.post("/tools/hf_save_session")
async def hf_save_session() -> JSONResponse:
    """
    Save the current browser cookies to disk.  Call this after completing
    manual Google OAuth so future runs can restore the authenticated session.
    """
    try:
        page = await _get_page()
        await _save_cookies()
        # Check if truly logged in now
        login_btn = await page.query_selector("a:has-text('Login'), button:has-text('Login')")
        logged_in = login_btn is None
        return JSONResponse(
            {
                "status": "ok",
                "logged_in": logged_in,
                "url": page.url,
                "message": "Session saved"
                if logged_in
                else "Cookies saved but Login button still visible — may not be authenticated",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_save_session failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_login
# ---------------------------------------------------------------------------


async def _dismiss_popup(page: Any) -> bool:
    """Dismiss any modal/popup overlays on the page. Returns True if one was closed."""
    selectors = [
        "button[aria-label='Close']",
        "button[aria-label='close']",
        "[data-testid='modal-close']",
        ".modal button svg",  # icon-only close buttons inside modals
        "dialog button:has(svg)",
        # Generic: any X/close button inside an overlay
        "div[role='dialog'] button",
        ".fixed button:has(svg)",
        # Last resort: look for an element visually inside a modal overlay
        "button.absolute",
    ]
    for sel in selectors:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await asyncio.sleep(0.5)
                return True
        except Exception:
            continue
    return False


@app.post("/tools/hf_login")
async def hf_login(req: LoginRequest) -> JSONResponse:
    """
    Restore a Higgsfield session from saved cookies, or navigate to the login
    page if no valid session exists.

    Flow:
    1. Load browser + cookies
    2. Check if truly authenticated (not just nav present)
    3. If not, dismiss any popup, then click the Login button
    4. User completes Google OAuth in the visible browser window
    """
    try:
        page = await _get_page()

        if not req.force_relogin:
            loaded = await _load_cookies()
            if loaded:
                await page.goto(HF_BASE_URL, wait_until="domcontentloaded", timeout=30_000)
                await asyncio.sleep(1)
                # Truly authenticated = no Login/Sign up buttons visible
                login_btn = await page.query_selector(
                    "a:has-text('Login'), button:has-text('Login'), a[href*='/login']"
                )
                if login_btn is None:
                    return JSONResponse({"status": "ok", "session": "restored", "url": page.url})

        # Not logged in — dismiss popup then navigate to login page
        await page.goto(HF_BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1)

        # Dismiss any welcome / promo modal
        await _dismiss_popup(page)
        await asyncio.sleep(0.5)

        # Click the Login button in the nav
        login_nav = await page.query_selector("a:has-text('Login'), button:has-text('Login'), a[href*='/login']")
        if login_nav:
            await login_nav.click()
            await asyncio.sleep(2)

        await _save_cookies()

        return JSONResponse(
            {
                "status": "ok",
                "session": "login_page",
                "url": page.url,
                "message": "Login page is open — click 'Continue with Google' in the browser window to authenticate",
            }
        )

    except PurchaseBlockedError as e:
        await _dispatch_alert(str(e))
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_login failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_navigate
# ---------------------------------------------------------------------------


@app.post("/tools/hf_navigate")
async def hf_navigate(req: NavigateRequest) -> JSONResponse:
    """
    Navigate to a path on higgsfield.ai.
    Raises 403 if the path matches any purchase/billing URL fragment.
    """
    # Safety: ensure path starts with /
    path = req.path if req.path.startswith("/") else f"/{req.path}"
    full_url = f"{HF_BASE_URL}{path}"

    try:
        _check_purchase_block(full_url)
    except PurchaseBlockedError as e:
        await _dispatch_alert(str(e))
        raise HTTPException(status_code=403, detail=str(e))

    try:
        page = await _get_page()
        await page.goto(full_url, wait_until="domcontentloaded", timeout=30_000)
        title = await page.title()
        await _save_cookies()
        return JSONResponse({"status": "ok", "url": page.url, "title": title})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_navigate failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_create_soul_id
# ---------------------------------------------------------------------------


@app.post("/tools/hf_create_soul_id")
async def hf_create_soul_id(req: CreateSoulIdRequest) -> JSONResponse:
    """
    Create a Higgsfield Soul ID for a character.

    Flow:
      1. Navigate to /character/upload
      2. Upload images (from image_folder or image_path)
      3. Accept media upload agreement if it appears
      4. Fill character name
      5. Click Create
      6. Detect subscription paywall → raise 403 if hit
      7. Poll for resulting character URL
      8. Save URL to DB

    IMPORTANT: Requires a paid Higgsfield subscription (Soul 2.0 plan).
    Call this ONCE per character.
    """
    root = Path(__file__).parent.parent.parent

    # Resolve image files
    image_files: list[str] = []
    if req.image_folder:
        folder = Path(req.image_folder) if Path(req.image_folder).is_absolute() else root / req.image_folder
        if not folder.is_dir():
            raise HTTPException(status_code=400, detail=f"image_folder not found: {folder}")
        image_files = [
            str(p) for p in sorted(folder.iterdir()) if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".heic"}
        ]
        if not image_files:
            raise HTTPException(status_code=400, detail=f"No image files found in: {folder}")
    elif req.image_path:
        ip = Path(req.image_path) if Path(req.image_path).is_absolute() else root / req.image_path
        if not ip.exists():
            raise HTTPException(status_code=400, detail=f"image_path not found: {ip}")
        image_files = [str(ip)]
    else:
        raise HTTPException(status_code=400, detail="Must provide image_folder or image_path")

    upload_url = f"{HF_BASE_URL}/character/upload"

    try:
        page = await _get_page()

        # Navigate to upload page
        await page.goto(upload_url, wait_until="domcontentloaded", timeout=30_000)
        await asyncio.sleep(1)

        # Dismiss any promo popup first
        await _dismiss_popup(page)

        # Wait for file input
        await page.wait_for_selector("input[type='file']", timeout=15_000)

        # Upload images
        await page.set_input_files("input[type='file']", image_files)
        await asyncio.sleep(2)

        # Handle TOS agreement modal (appears after selecting files)
        agree_btn = await page.query_selector("button:has-text('I agree, continue')")
        if agree_btn:
            await agree_btn.click()
            await asyncio.sleep(2)

        # Fill character name
        name_input = await page.query_selector("input[placeholder='Name'], input[placeholder*='name' i]")
        if name_input:
            await name_input.fill(req.character_name)
            await asyncio.sleep(0.5)

        # Select model — try to pick a non-premium model when model_preference != "soul_2"
        if req.model_preference != "soul_2":
            model_trigger = await page.query_selector(
                "button:has-text('Soul 2.0'), button:has-text('Soul 1.0'), "
                "[aria-label*='model' i], button[class*='model' i]"
            )
            if model_trigger:
                await model_trigger.click()
                await asyncio.sleep(1)
                if req.model_preference == "auto":
                    # Grab all visible options, prefer anything that isn't Soul 2.0
                    options = await page.query_selector_all("[role='option'], [role='menuitem'], li[class*='option' i]")
                    selected = False
                    for opt in options:
                        text = await opt.inner_text()
                        text_norm = text.strip().lower()
                        if "2.0" not in text_norm and "pro" not in text_norm:
                            await opt.click()
                            selected = True
                            break
                    if not selected and options:
                        await options[0].click()  # fall back to first option
                else:
                    # Match by slug: "soul_1" → "Soul 1.0", "soul_1_5" → "Soul 1.5", etc.
                    label_map = {"soul_1": "Soul 1.0", "soul_1_5": "Soul 1.5", "basic": "Basic"}
                    target_label = label_map.get(req.model_preference, req.model_preference)
                    opt = await page.query_selector(
                        f"[role='option']:has-text('{target_label}'), [role='menuitem']:has-text('{target_label}')"
                    )
                    if opt:
                        await opt.click()
                await asyncio.sleep(0.5)

        # Screenshot evidence before submit
        evidence_dir = EVIDENCE_DIR / req.character_id
        evidence_dir.mkdir(parents=True, exist_ok=True)
        before_path = evidence_dir / "before_create.png"
        await page.screenshot(path=str(before_path), full_page=False)

        # Click Create
        create_btn = await page.query_selector("button:has-text('Create')")
        if not create_btn:
            raise RuntimeError("Could not find Create button on upload page")
        await create_btn.click()
        await asyncio.sleep(2)

        # Check for subscription paywall modal
        paywall = await page.query_selector(
            "h2:has-text('FULL IDENTITY CONTROL'), h1:has-text('Soul ID'), "
            "button:has-text('Get Starter Annual'), button:has-text('Get Plus')"
        )
        if paywall:
            # Close modal before raising
            close_x = await page.query_selector("button[class*='absolute top-4 right-4']")
            if close_x:
                await close_x.dispatch_event("click")
            await asyncio.sleep(1)
            await _dispatch_alert(
                "PURCHASE BLOCKED — Soul ID creation requires a paid Higgsfield subscription. "
                "Plans start at $15/month (Starter). Subscribe at https://higgsfield.ai/pricing "
                "then re-run hf_create_soul_id."
            )
            raise PurchaseBlockedError(
                "Soul ID creation requires a paid Higgsfield subscription (Starter $15/mo or higher). "
                "Subscribe at https://higgsfield.ai/pricing then retry."
            )

        # Poll for resulting character URL (URL changes from /character/upload to /character/<id>)
        start = time.time()
        soul_id_url: str | None = None
        while time.time() - start < 120:
            await asyncio.sleep(4)
            current_url = page.url
            if "/character/" in current_url and current_url != upload_url:
                soul_id_url = current_url
                break
            if "/characters/" in current_url:
                soul_id_url = current_url
                break

        # Final screenshot
        after_path = evidence_dir / "after_create.png"
        await page.screenshot(path=str(after_path), full_page=False)
        await _save_cookies()

        final_url = soul_id_url or page.url
        status = "active" if soul_id_url else "pending_review"

        # Update DB
        from backend.database.higgsfield_store import HighgsfieldStore

        store = HighgsfieldStore()
        store.set_soul_id(
            character_id=req.character_id,
            soul_id_url=final_url,
            status=status,
        )

        return JSONResponse(
            {
                "status": "ok",
                "character_id": req.character_id,
                "soul_id_url": final_url,
                "images_uploaded": len(image_files),
                "soul_id_status": status,
                "evidence_before": str(before_path),
                "evidence_after": str(after_path),
            }
        )

    except PurchaseBlockedError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_create_soul_id failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_submit_video
# ---------------------------------------------------------------------------


@app.post("/tools/hf_submit_video")
async def hf_submit_video(req: SubmitVideoRequest) -> JSONResponse:
    """
    Navigate to Higgsfield video generation, select the character's Soul ID,
    fill in the prompt + model + duration, and submit.
    Returns the job URL to poll with hf_poll_result.

    The character's Soul ID must already exist (soul_id_status = 'active').
    """
    # Verify Soul ID is ready
    from backend.database.higgsfield_store import HighgsfieldStore

    store = HighgsfieldStore()
    char = store.get_character(req.character_id)
    if char is None:
        raise HTTPException(status_code=404, detail=f"Character '{req.character_id}' not found in registry")
    if char["soul_id_status"] != "active":
        raise HTTPException(
            status_code=400,
            detail=(
                f"Character '{req.character_id}' Soul ID is not active "
                f"(status={char['soul_id_status']!r}). "
                "Run hf_create_soul_id first."
            ),
        )

    try:
        page = await _get_page()

        # Navigate to video creation
        create_url = f"{HF_BASE_URL}/create"
        _check_purchase_block(create_url)
        await page.goto(create_url, wait_until="domcontentloaded", timeout=30_000)

        # Select model
        # Model selector varies — try several common selectors
        model_selectors = [
            f"[data-model='{req.model}']",
            f"button:has-text('{req.model}')",
            f"[aria-label*='{req.model}']",
        ]
        for sel in model_selectors:
            el = await page.query_selector(sel)
            if el:
                await el.click()
                break

        # Select Soul ID character
        if char["soul_id_url"]:
            # Navigate to character in the sidebar/picker
            char_picker = await page.query_selector(
                "[data-testid='character-picker'], .character-select, button:has-text('Character')"
            )
            if char_picker:
                await char_picker.click()
                await asyncio.sleep(1)
                # Find the character card by name
                char_name = char["name"]
                char_card = await page.query_selector(
                    f"[aria-label*='{char_name}'], .character-card:has-text('{char_name}')"
                )
                if char_card:
                    await char_card.click()

        # Fill prompt
        prompt_input = await page.query_selector(
            "textarea[placeholder*='prompt'], textarea[name='prompt'], .prompt-input"
        )
        if prompt_input:
            await prompt_input.fill(req.prompt)

        # Set duration if control exists
        duration_input = await page.query_selector(
            "input[name='duration'], select[name='duration'], [data-testid='duration']"
        )
        if duration_input:
            tag = await duration_input.evaluate("el => el.tagName.toLowerCase()")
            if tag == "select":
                await duration_input.select_option(str(req.duration_s))
            else:
                await duration_input.fill(str(req.duration_s))

        # Screenshot before submit
        evidence_path = (
            EVIDENCE_DIR / req.character_id / f"pre_submit_{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}.png"
        )
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(evidence_path))

        # Submit
        submit_btn = await page.query_selector(
            "button[type='submit'], button:has-text('Generate'), button:has-text('Create Video')"
        )
        if submit_btn:
            await submit_btn.click()
        else:
            raise HTTPException(status_code=500, detail="Could not find Generate button")

        # Wait for job URL to appear
        await asyncio.sleep(3)
        job_url = page.url
        await _save_cookies()

        # Log generation run in DB
        from backend.database.higgsfield_store import HighgsfieldStore

        store = HighgsfieldStore()
        run_id = store.create_run(
            character_id=req.character_id,
            model=req.model,
            prompt=req.prompt,
            campaign=req.campaign,
            tags=[req.scene_id] if req.scene_id else [],
        )

        return JSONResponse(
            {
                "status": "ok",
                "run_id": run_id,
                "job_url": job_url,
                "evidence_screenshot": str(evidence_path),
            }
        )

    except PurchaseBlockedError as e:
        await _dispatch_alert(str(e))
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_submit_video failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_poll_result
# ---------------------------------------------------------------------------


@app.post("/tools/hf_poll_result")
async def hf_poll_result(req: PollResultRequest) -> JSONResponse:
    """
    Poll a Higgsfield job URL until the video is complete (or timeout reached).
    Returns the download URL and completion status.
    """
    try:
        page = await _get_page()
        _check_purchase_block(req.job_url)

        await page.goto(req.job_url, wait_until="domcontentloaded", timeout=30_000)

        start = time.time()
        result_url = None
        status = "pending"

        while time.time() - start < req.timeout_s:
            # Look for completed video element
            video_el = await page.query_selector("video[src], [data-testid='video-result'] video")
            if video_el:
                result_url = await video_el.get_attribute("src")
                status = "complete"
                break

            # Look for download link
            dl_link = await page.query_selector("a[download], a:has-text('Download')")
            if dl_link:
                result_url = await dl_link.get_attribute("href")
                status = "complete"
                break

            # Check for failure indicators
            failed_el = await page.query_selector(".error, [data-status='failed'], :has-text('Generation failed')")
            if failed_el:
                status = "failed"
                break

            await asyncio.sleep(POLL_INTERVAL_S)
            await page.reload(wait_until="domcontentloaded", timeout=15_000)

        # Final screenshot
        screenshot_b64 = await page.screenshot()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        screenshot_path = EVIDENCE_DIR / f"poll_{ts}.png"
        screenshot_path.parent.mkdir(parents=True, exist_ok=True)
        screenshot_path.write_bytes(screenshot_b64)

        return JSONResponse(
            {
                "status": status,
                "result_url": result_url,
                "job_url": req.job_url,
                "elapsed_s": round(time.time() - start),
                "screenshot": str(screenshot_path),
            }
        )

    except PurchaseBlockedError as e:
        await _dispatch_alert(str(e))
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_poll_result failed: {e}")


# ---------------------------------------------------------------------------
# Tool: hf_log_evidence
# ---------------------------------------------------------------------------


@app.post("/tools/hf_log_evidence")
async def hf_log_evidence(req: LogEvidenceRequest) -> JSONResponse:
    """
    Take a screenshot of the current browser state and write a structured
    log entry to data/higgsfield/rag_corpus/ for the RAG improvement loop.
    """
    try:
        page = await _get_page()
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")

        # Screenshot
        screenshot_bytes = await page.screenshot(full_page=False)
        shot_path = EVIDENCE_DIR / req.run_id / f"{req.label}_{ts}.png"
        shot_path.parent.mkdir(parents=True, exist_ok=True)
        shot_path.write_bytes(screenshot_bytes)

        # Also save base64 inline for JSON log
        base64.b64encode(screenshot_bytes).decode()

        # RAG corpus entry
        rag_dir = Path("data/higgsfield/rag_corpus")
        rag_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "run_id": req.run_id,
            "label": req.label,
            "notes": req.notes,
            "current_url": page.url,
            "screenshot_path": str(shot_path),
        }
        rag_file = rag_dir / f"{req.run_id}_{req.label}_{ts}.json"
        rag_file.write_text(json.dumps(entry, indent=2))

        return JSONResponse(
            {
                "status": "ok",
                "screenshot_path": str(shot_path),
                "rag_entry_path": str(rag_file),
                "url_at_capture": page.url,
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"hf_log_evidence failed: {e}")


# ---------------------------------------------------------------------------
# Health + status
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "status": "ok",
            "playwright_available": PLAYWRIGHT_AVAILABLE,
            "headless": HEADLESS,
            "browser_active": _page is not None,
            "port": PORT,
        }
    )


@app.get("/status")
async def status() -> JSONResponse:
    page = _page
    return JSONResponse(
        {
            "browser_open": page is not None,
            "current_url": page.url if page else None,
            "cookie_file_exists": COOKIE_FILE.exists(),
            "headless": HEADLESS,
        }
    )


# ---------------------------------------------------------------------------
# Teardown
# ---------------------------------------------------------------------------


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global _playwright_handle, _browser, _context, _page
    if _page:
        await _save_cookies()
    if _browser:
        await _browser.close()
    if _playwright_handle:
        await _playwright_handle.stop()
    _page = _context = _browser = _playwright_handle = None


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run("backend.mcp.higgsfield_playwright_server:app", host="127.0.0.1", port=PORT, reload=False)
