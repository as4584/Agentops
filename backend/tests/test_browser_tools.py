"""Tests for Feature 4 — Browser Control (Playwright/CDP).

All tests mock Playwright so no browser binary is required.

Covers:
- Sprint 4.1: session start/close, TTL helpers
- Sprint 4.2: URL scheme allowlist, SSRF blocking, retry on transient error
- Sprint 4.3: screenshot artifact path, action redaction
- Sprint 4.4: agent permissioning via BROWSER_ALLOWED_AGENTS
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_page() -> MagicMock:
    page = AsyncMock()
    page.title = AsyncMock(return_value="Test Page")
    page.goto = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.select_option = AsyncMock()
    page.screenshot = AsyncMock()
    page.set_input_files = AsyncMock()
    acc = AsyncMock()
    acc.snapshot = AsyncMock(return_value={"role": "WebArea"})
    page.accessibility = acc
    return page


def _make_playwright_stack(page: MagicMock | None = None) -> tuple:
    """Return (mock_pw, mock_browser, mock_context, mock_page) async mocks."""
    if page is None:
        page = _make_mock_page()

    context = AsyncMock()
    context.new_page = AsyncMock(return_value=page)
    context.set_default_timeout = MagicMock()
    context.set_default_navigation_timeout = MagicMock()

    browser = AsyncMock()
    browser.new_context = AsyncMock(return_value=context)

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = AsyncMock()
    pw.chromium = chromium

    pw_cm = AsyncMock()
    pw_cm.__aenter__ = AsyncMock(return_value=pw)
    pw_cm.__aexit__ = AsyncMock(return_value=False)

    return pw, browser, context, page


# ---------------------------------------------------------------------------
# Sprint 4.1 — Session Lifecycle
# ---------------------------------------------------------------------------


def test_browser_session_start_close(tmp_path: Path) -> None:
    """close() should clear _started and not raise."""
    from backend.browser.session import BrowserSession

    _, browser, context, page = _make_playwright_stack()

    async def _run():
        session = BrowserSession(agent_id="agent-1")
        session._screenshots_dir = tmp_path / "shots"
        session._screenshots_dir.mkdir(parents=True)
        # Inject mocked Playwright objects without actually launching
        session._pw = AsyncMock()
        session._browser = browser
        session._context = context
        session._page = page
        session._started = True

        assert session._started
        await session.close()
        assert not session._started

    asyncio.run(_run())


def test_browser_session_is_idle_false_when_fresh() -> None:
    from backend.browser.session import BrowserSession

    session = BrowserSession(agent_id="freshie")
    assert not session.is_idle()


def test_browser_session_is_idle_true_when_stale() -> None:
    from backend.browser.session import BrowserSession

    session = BrowserSession(agent_id="stale")
    session.last_action_at = time.monotonic() - 700  # past 600s TTL
    assert session.is_idle()


# ---------------------------------------------------------------------------
# Sprint 4.2 — URL allowlist + SSRF blocking
# ---------------------------------------------------------------------------


def test_validate_url_allows_http() -> None:
    from backend.browser.session import _validate_url

    _validate_url("http://example.com/page")  # should not raise


def test_validate_url_allows_https() -> None:
    from backend.browser.session import _validate_url

    _validate_url("https://example.com/page")


def test_validate_url_rejects_ftp() -> None:
    import pytest

    from backend.browser.session import _validate_url

    with pytest.raises(ValueError, match="scheme"):
        _validate_url("ftp://example.com/file")


def test_validate_url_rejects_javascript() -> None:
    import pytest

    from backend.browser.session import _validate_url

    with pytest.raises(ValueError, match="scheme"):
        _validate_url("javascript:alert(1)")


def test_validate_url_rejects_ssrf_blocked_prefix() -> None:
    import pytest

    from backend.browser.session import _validate_url

    # 169.254.x.x is in SSRF_BLOCKED_PREFIXES
    with pytest.raises(ValueError, match="SSRF"):
        _validate_url("http://169.254.169.254/latest/meta-data/")


def test_validate_url_rejects_localhost() -> None:
    import pytest

    from backend.browser.session import _validate_url

    with pytest.raises(ValueError, match="SSRF"):
        _validate_url("http://localhost:8080/admin")


# ---------------------------------------------------------------------------
# Sprint 4.2 — navigate and interactions
# ---------------------------------------------------------------------------


def test_browser_navigate_validates_url(tmp_path: Path) -> None:
    import pytest

    from backend.browser.session import BrowserSession

    async def _run():
        session = BrowserSession(agent_id="nav-agent")
        session._screenshots_dir = tmp_path / "shots"
        session._screenshots_dir.mkdir(parents=True)
        with pytest.raises(ValueError, match="scheme"):
            await session.navigate("ftp://bad.example.com")

    asyncio.run(_run())


def test_browser_navigate_happy_path(tmp_path: Path) -> None:
    from backend.browser.session import BrowserSession

    page = _make_mock_page()
    _, browser, context, _ = _make_playwright_stack(page)

    async def _run():
        session = BrowserSession(agent_id="nav-ok")
        session._screenshots_dir = tmp_path / "shots"
        session._screenshots_dir.mkdir(parents=True)
        session._page = page
        session._started = True

        result = await session.navigate("https://example.com/")
        assert result["ok"] is True
        assert result["title"] == "Test Page"

    asyncio.run(_run())


def test_browser_click_retries_on_transient_error(tmp_path: Path) -> None:
    """click() should retry up to MAX_RETRIES before raising."""
    from backend.browser.session import BrowserSession

    page = _make_mock_page()
    call_count = {"n": 0}

    async def _flaky_click(selector):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise Exception("timeout")

    page.click = _flaky_click

    async def _run():
        session = BrowserSession(agent_id="clicker")
        session._screenshots_dir = tmp_path / "shots"
        session._screenshots_dir.mkdir(parents=True)
        session._page = page
        session._started = True
        result = await session.click("button#submit")
        return result, call_count["n"]

    result, n = asyncio.run(_run())
    assert result["ok"] is True
    assert n == 2  # one retry


# ---------------------------------------------------------------------------
# Sprint 4.3 — Redaction of secret fields
# ---------------------------------------------------------------------------


def test_redact_text_for_password_selector() -> None:
    from backend.browser.session import _redact_text

    assert _redact_text("#password", "supersecret") == "[REDACTED]"


def test_redact_text_for_token_selector() -> None:
    from backend.browser.session import _redact_text

    assert _redact_text("input[name='api_token']", "tok-123") == "[REDACTED]"


def test_redact_text_for_normal_selector() -> None:
    from backend.browser.session import _redact_text

    assert _redact_text("#username", "alice") == "alice"


def test_browser_screenshot_saves_to_session_dir(tmp_path: Path) -> None:
    from backend.browser.session import BrowserSession

    page = _make_mock_page()
    captured: list[str] = []

    async def _fake_screenshot(path: str):
        captured.append(path)

    page.screenshot = _fake_screenshot

    async def _run():
        session = BrowserSession(agent_id="screenie")
        session._screenshots_dir = tmp_path / "browser" / session.session_id
        session._screenshots_dir.mkdir(parents=True)
        session._page = page
        session._started = True
        result = await session.screenshot("test.png")
        return result, captured

    result, paths = asyncio.run(_run())
    assert result["ok"] is True
    assert len(paths) == 1
    assert "test.png" in paths[0]


# ---------------------------------------------------------------------------
# Sprint 4.4 — Agent permissioning
# ---------------------------------------------------------------------------


def test_browser_tool_blocked_for_unauthorised_agent(tmp_path: Path) -> None:
    """When BROWSER_ALLOWED_AGENTS is set, unlisted agents are rejected."""
    import pytest

    from backend.browser import tooling as browser_tooling

    async def _run():
        with patch.object(browser_tooling, "BROWSER_ALLOWED_AGENTS", ["allowed-agent"]):
            with pytest.raises(PermissionError, match="BROWSER_ALLOWED_AGENTS"):
                browser_tooling._check_browser_permission("evil-agent")

    asyncio.run(_run())


def test_browser_tool_allowed_when_agent_in_list() -> None:
    from backend.browser import tooling as browser_tooling

    with patch.object(browser_tooling, "BROWSER_ALLOWED_AGENTS", ["agent-x"]):
        browser_tooling._check_browser_permission("agent-x")  # should not raise


def test_browser_tool_allowed_when_list_empty() -> None:
    """Empty BROWSER_ALLOWED_AGENTS means all agents are allowed."""
    from backend.browser import tooling as browser_tooling

    with patch.object(browser_tooling, "BROWSER_ALLOWED_AGENTS", []):
        browser_tooling._check_browser_permission("any-agent")  # no raise


# ---------------------------------------------------------------------------
# Tool registry integration
# ---------------------------------------------------------------------------


def test_browser_tools_registered_in_tool_registry() -> None:
    from backend.tools import get_tool_definitions

    names = {t.name for t in get_tool_definitions()}
    expected = {
        "browser_open",
        "browser_click",
        "browser_type",
        "browser_select",
        "browser_snapshot",
        "browser_screenshot",
        "browser_upload",
        "browser_close",
    }
    assert expected.issubset(names)


def test_browser_tools_are_state_modify_except_snapshot() -> None:
    from backend.models import ModificationType
    from backend.tools import TOOL_REGISTRY

    assert TOOL_REGISTRY["browser_snapshot"].modification_type == ModificationType.READ_ONLY
    assert TOOL_REGISTRY["browser_open"].modification_type == ModificationType.STATE_MODIFY
