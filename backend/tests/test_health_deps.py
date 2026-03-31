"""Tests for the /health/deps dependency health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture()
def _mock_server_globals():
    """Patch server-level globals so we can import the endpoint."""
    with (
        patch("backend.server._llm_client", new_callable=lambda: MagicMock) as llm,
        patch("backend.server.mcp_bridge") as mcp,
    ):
        llm.is_available = AsyncMock(return_value=True)
        mcp.get_status.return_value = {
            "enabled": True,
            "cli_available": False,
            "initialised": False,
            "discovered_tools": 0,
            "declared_tool_count": 26,
        }
        yield llm, mcp


@pytest.mark.asyncio()
async def test_health_deps_returns_all_keys(_mock_server_globals):
    """Endpoint returns status for every dependency."""
    from backend.server import health_deps

    result = await health_deps()
    assert "status" in result
    assert "dependencies" in result
    deps = result["dependencies"]
    for key in ("ollama", "mcp_bridge", "ffmpeg", "docker", "ruff"):
        assert key in deps, f"Missing dependency key: {key}"
        assert "ok" in deps[key]


@pytest.mark.asyncio()
async def test_health_deps_degraded_when_dep_missing(_mock_server_globals):
    """Status should be 'degraded' when any dependency is unavailable."""
    llm, _mcp = _mock_server_globals
    llm.is_available = AsyncMock(return_value=False)

    from backend.server import health_deps

    result = await health_deps()
    # At minimum ollama is down, so status should be degraded
    assert result["status"] == "degraded"


@pytest.mark.asyncio()
async def test_health_deps_ollama_exception(_mock_server_globals):
    """Ollama check failure should not crash the endpoint."""
    llm, _mcp = _mock_server_globals
    llm.is_available = AsyncMock(side_effect=ConnectionError("refused"))

    from backend.server import health_deps

    result = await health_deps()
    assert result["dependencies"]["ollama"]["ok"] is False
    assert "refused" in result["dependencies"]["ollama"]["detail"]
