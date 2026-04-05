"""Browser session manager backed by Playwright Async API.

Each agent gets one isolated `BrowserSession`. Sessions are created lazily on
first use and shut down after `TTL_SECONDS` of inactivity (default 10 min).

Security controls
-----------------
- Only ``http`` and ``https`` URL schemes are accepted.
- Private-/local-network targets are blocked via ``SSRF_BLOCKED_PREFIXES``.
- Secrets typed into fields are redacted in logs.
- Screenshots are stored under ``output/browser/<session_id>/``.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path
from typing import Any

from backend.config import OUTPUT_DIR, SSRF_BLOCKED_PREFIXES
from backend.utils import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TTL_SECONDS: int = 600  # 10-minute idle eviction
NAV_TIMEOUT_MS: int = 30_000  # max navigation wait
ACTION_TIMEOUT_MS: int = 10_000  # max click / fill / select wait
MAX_RETRIES: int = 2  # retries for transient action failures

# URL scheme allowlist
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)

# Simple secret-pattern redactor (passwords, tokens, keys)
_SECRET_RE = re.compile(r"(?i)(password|token|key|secret|auth)", re.IGNORECASE)

_SCREENSHOTS_BASE = OUTPUT_DIR / "browser"


def _validate_url(url: str) -> None:
    """Raise ``ValueError`` if the URL is disallowed."""
    if not _SCHEME_RE.match(url):
        raise ValueError(f"Disallowed URL scheme — only http/https are permitted: {url!r}")

    url_lower = url.lower()
    for blocked in SSRF_BLOCKED_PREFIXES:
        if url_lower.startswith(blocked.lower()):
            raise ValueError(f"SSRF policy blocks target URL: {url!r}")


def _redact_text(selector: str, text: str) -> str:
    """Return ``[REDACTED]`` if the selector name looks like a secret field."""
    if _SECRET_RE.search(selector):
        return "[REDACTED]"
    return text


class BrowserSession:
    """Playwright-backed browser session with TTL and safety controls."""

    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.session_id = str(uuid.uuid4())
        self._pw: Any = None  # playwright instance
        self._browser: Any = None  # Browser
        self._context: Any = None  # BrowserContext (isolated)
        self._page: Any = None  # current Page
        self._started = False
        self.created_at = time.monotonic()
        self.last_action_at = time.monotonic()
        self._screenshots_dir = _SCREENSHOTS_BASE / self.session_id
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)
        self._action_count = 0

    @property
    def is_started(self) -> bool:
        """True after :meth:`start` has completed successfully."""
        return self._started

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch Playwright and create an isolated browser context."""
        if self._started:
            return

        from playwright.async_api import async_playwright

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        state_dir = self._screenshots_dir / "storage_state.json"
        self._context = await self._browser.new_context(
            storage_state=str(state_dir) if state_dir.exists() else None,
            viewport={"width": 1280, "height": 800},
        )
        self._context.set_default_timeout(ACTION_TIMEOUT_MS)
        self._context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._page = await self._context.new_page()
        self._started = True
        self._touch()
        logger.info(
            "browser_session_started",
            extra={
                "event_type": "browser_session_started",
                "agent_id": self.agent_id,
                "session_id": self.session_id,
            },
        )

    async def close(self) -> None:
        """Close the browser context and Playwright instance."""
        if not self._started:
            return
        try:
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._pw:
                await self._pw.stop()
        except Exception as exc:
            logger.warning(
                f"browser_session_close_error: {exc}",
                extra={"event_type": "browser_session_close_error", "agent_id": self.agent_id},
            )
        finally:
            self._started = False
        logger.info(
            "browser_session_closed",
            extra={
                "event_type": "browser_session_closed",
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                "actions": self._action_count,
            },
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    async def navigate(self, url: str) -> dict[str, Any]:
        """Navigate to *url*. Validates scheme and SSRF policy first."""
        _validate_url(url)
        await self._ensure_started()
        self._touch()
        self._log_action("browser_open", {"url": url})
        await self._page.goto(url, wait_until="domcontentloaded")
        # Re-validate final URL after redirects to prevent redirect-chain SSRF
        final_url = self._page.url
        if final_url and final_url != url:
            try:
                _validate_url(final_url)
            except ValueError:
                await self._page.goto("about:blank")
                raise ValueError(f"SSRF policy blocked redirect target: {url!r} → {final_url!r}")
        title = await self._page.title()
        return {"ok": True, "url": final_url or url, "title": title}

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    async def click(self, selector: str) -> dict[str, Any]:
        await self._ensure_started()
        self._touch()
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                await self._page.click(selector)
                self._log_action("browser_click", {"selector": selector})
                return {"ok": True, "selector": selector}
            except Exception as exc:
                if attempt > MAX_RETRIES:
                    raise
                logger.info(
                    f"browser_click retry {attempt}: {exc}",
                    extra={"event_type": "browser_click_retry", "agent_id": self.agent_id},
                )
        return {"ok": False, "selector": selector}

    async def type_text(self, selector: str, text: str) -> dict[str, Any]:
        await self._ensure_started()
        self._touch()
        redacted = _redact_text(selector, text)
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                await self._page.fill(selector, text)
                self._log_action("browser_type", {"selector": selector, "text": redacted})
                return {"ok": True, "selector": selector, "text_length": len(text)}
            except Exception as exc:
                if attempt > MAX_RETRIES:
                    raise
                logger.info(
                    f"browser_type retry {attempt}: {exc}",
                    extra={"event_type": "browser_type_retry", "agent_id": self.agent_id},
                )
        return {"ok": False, "selector": selector}

    async def select_option(self, selector: str, value: str) -> dict[str, Any]:
        await self._ensure_started()
        self._touch()
        for attempt in range(1, MAX_RETRIES + 2):
            try:
                await self._page.select_option(selector, value)
                self._log_action("browser_select", {"selector": selector, "value": value})
                return {"ok": True, "selector": selector, "value": value}
            except Exception as exc:
                if attempt > MAX_RETRIES:
                    raise
                logger.info(
                    f"browser_select retry {attempt}: {exc}",
                    extra={"event_type": "browser_select_retry", "agent_id": self.agent_id},
                )
        return {"ok": False, "selector": selector}

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    async def snapshot(self) -> dict[str, Any]:
        """Return the page's accessibility tree snapshot."""
        await self._ensure_started()
        self._touch()
        tree = await self._page.accessibility.snapshot()
        self._log_action("browser_snapshot", {})
        return {"ok": True, "snapshot": tree}

    async def screenshot(self, relative_path: str | None = None) -> dict[str, Any]:
        """Save a PNG screenshot and return the path."""
        await self._ensure_started()
        self._touch()
        fname = relative_path or f"shot_{int(time.time())}.png"
        dest = self._screenshots_dir / fname
        dest.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(dest))
        self._log_action("browser_screenshot", {"path": str(dest)})
        return {"ok": True, "path": str(dest)}

    async def upload_file(self, selector: str, file_path: str) -> dict[str, Any]:
        """Set files on a file input element."""
        await self._ensure_started()
        self._touch()
        fp = Path(file_path)
        if not fp.exists():
            raise FileNotFoundError(f"Upload file not found: {file_path}")
        await self._page.set_input_files(selector, str(fp))
        self._log_action("browser_upload", {"selector": selector, "file": fp.name})
        return {"ok": True, "selector": selector, "file": fp.name}

    # ------------------------------------------------------------------
    # TTL helpers
    # ------------------------------------------------------------------

    def is_idle(self) -> bool:
        return (time.monotonic() - self.last_action_at) > TTL_SECONDS

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_started(self) -> None:
        if not self._started:
            await self.start()

    def _touch(self) -> None:
        self.last_action_at = time.monotonic()
        self._action_count += 1

    def _log_action(self, event_type: str, extra_fields: dict[str, Any]) -> None:
        logger.info(
            event_type,
            extra={
                "event_type": event_type,
                "agent_id": self.agent_id,
                "session_id": self.session_id,
                **extra_fields,
            },
        )
