"""Browser Session Registry and tool-surface wrappers.

The registry holds at most one :class:`BrowserSession` per agent and evicts
sessions that have been idle beyond their TTL.

Tool functions defined here are registered in ``backend/tools/__init__.py``
under the ``browser_*`` namespace.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.browser.session import BrowserSession
from backend.config import BROWSER_ALLOWED_AGENTS  # type: ignore[reportUnusedImport]  # used in _check_browser_permission
from backend.utils import logger


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class BrowserSessionRegistry:
    """Per-agent browser session store with TTL eviction."""

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, agent_id: str) -> BrowserSession:
        async with self._lock:
            session = self._sessions.get(agent_id)
            if session is None or not session.is_started:
                session = BrowserSession(agent_id=agent_id)
                await session.start()
                self._sessions[agent_id] = session
        return session

    async def close_session(self, agent_id: str) -> bool:
        async with self._lock:
            session = self._sessions.pop(agent_id, None)
        if session:
            await session.close()
            return True
        return False

    async def evict_idle(self) -> list[str]:
        """Close and remove sessions whose TTL has expired."""
        async with self._lock:
            idle = [aid for aid, sess in self._sessions.items() if sess.is_idle()]

        evicted: list[str] = []
        for aid in idle:
            if await self.close_session(aid):
                evicted.append(aid)
        return evicted

    def session_count(self) -> int:
        return len(self._sessions)

    def has_session(self, agent_id: str) -> bool:
        return agent_id in self._sessions


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: BrowserSessionRegistry | None = None


def get_browser_registry() -> BrowserSessionRegistry:
    """Lazy singleton factory — injectable for testing."""
    global _registry
    if _registry is None:
        _registry = BrowserSessionRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Agent permission check (Sprint 4.4)
# ---------------------------------------------------------------------------

def _check_browser_permission(agent_id: str) -> None:
    """Raise ``PermissionError`` if the agent is not allowed to use browser tools."""
    if BROWSER_ALLOWED_AGENTS and agent_id not in BROWSER_ALLOWED_AGENTS:
        raise PermissionError(
            f"Agent '{agent_id}' is not in BROWSER_ALLOWED_AGENTS. "
            "Add the agent ID to the BROWSER_ALLOWED_AGENTS env var."
        )


# ---------------------------------------------------------------------------
# Tool-surface functions
# ---------------------------------------------------------------------------

async def browser_open(url: str, agent_id: str) -> dict[str, Any]:
    """Open a URL in the agent's browser session."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.navigate(url)


async def browser_click(selector: str, agent_id: str) -> dict[str, Any]:
    """Click a page element identified by *selector*."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.click(selector)


async def browser_type(selector: str, text: str, agent_id: str) -> dict[str, Any]:
    """Type *text* into the element matching *selector*."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.type_text(selector, text)


async def browser_select(selector: str, value: str, agent_id: str) -> dict[str, Any]:
    """Select *value* from a ``<select>`` element."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.select_option(selector, value)


async def browser_snapshot(agent_id: str) -> dict[str, Any]:
    """Return the accessibility tree snapshot of the current page."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.snapshot()


async def browser_screenshot(path: str, agent_id: str) -> dict[str, Any]:
    """Capture a screenshot and save it under ``output/browser/<session_id>/``."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.screenshot(relative_path=path or None)


async def browser_upload(selector: str, file_path: str, agent_id: str) -> dict[str, Any]:
    """Set files on a file-input element."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    session = await registry.get_or_create(agent_id)
    return await session.upload_file(selector, file_path)


async def browser_close(agent_id: str) -> dict[str, Any]:
    """Close the agent's browser session."""
    _check_browser_permission(agent_id)
    registry = get_browser_registry()
    closed = await registry.close_session(agent_id)
    return {"ok": closed, "agent_id": agent_id}
