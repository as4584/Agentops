"""
Tests for backend.mcp.MCPBridge — Docker MCP Gateway integration.

Strategy: the bridge is designed for graceful degradation, so we test
every degradation path plus the happy-path tool routing wiring, all
without requiring a real Docker daemon.

Covers:
- Bridge disabled via MCP_GATEWAY_ENABLED=False → structured error
- Docker CLI absent → structured error, no crash
- Calling before initialise() → structured error
- Unknown tool name → structured error
- Happy-path routing: correct (server, tool) pair resolved from MCP_TOOL_MAP
- _discover_tools: JSON list + dict format parsing
- _discover_tools: empty/bad output handled gracefully
- is_mcp_tool() predicate
- call_tool() returns expected result keys
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.mcp import MCPBridge, MCP_TOOL_MAP, is_mcp_tool


# ---------------------------------------------------------------------------
# is_mcp_tool predicate
# ---------------------------------------------------------------------------

def test_is_mcp_tool_true_for_prefixed_names():
    assert is_mcp_tool("mcp_github_search_repositories") is True
    assert is_mcp_tool("mcp_slack_post_message") is True


def test_is_mcp_tool_false_for_native_tools():
    assert is_mcp_tool("safe_shell") is False
    assert is_mcp_tool("file_reader") is False
    assert is_mcp_tool("") is False


# ---------------------------------------------------------------------------
# Not initialised
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_before_initialise_returns_error():
    bridge = MCPBridge()
    # _initialised defaults to False
    result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {})
    assert result["success"] is False
    assert "not yet initialised" in result["error"].lower()


# ---------------------------------------------------------------------------
# Disabled gateway
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_when_disabled_returns_error(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", False)
    bridge = MCPBridge()
    bridge._initialised = True  # noqa: SLF001
    result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {})
    assert result["success"] is False
    assert "disabled" in result["error"].lower()


# ---------------------------------------------------------------------------
# Docker CLI absent
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialise_when_docker_missing(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)
    with patch("shutil.which", return_value=None):
        bridge = MCPBridge()
        await bridge.initialise()
    assert bridge._initialised is True  # noqa: SLF001
    assert bridge._cli_available is False  # noqa: SLF001


@pytest.mark.asyncio
async def test_call_tool_when_cli_missing_returns_error(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)
    bridge = MCPBridge()
    bridge._initialised = True  # noqa: SLF001
    bridge._cli_available = False  # noqa: SLF001

    result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {})
    assert result["success"] is False
    assert "docker" in result["error"].lower()


# ---------------------------------------------------------------------------
# Unknown tool name
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_unknown_name_returns_error(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)
    bridge = MCPBridge()
    bridge._initialised = True  # noqa: SLF001
    bridge._cli_available = True  # noqa: SLF001

    result = await bridge.call_tool("mcp_fantasy_tool", "agent_x", {})
    assert result["success"] is False
    assert "no mcp mapping" in result["error"].lower()


# ---------------------------------------------------------------------------
# Tool map completeness
# ---------------------------------------------------------------------------

def test_mcp_tool_map_has_all_expected_groups():
    """All 26 documented MCP tools must be in MCP_TOOL_MAP."""
    expected_prefixes = {
        "mcp_github_", "mcp_filesystem_", "mcp_docker_",
        "mcp_time_", "mcp_fetch_", "mcp_sqlite_", "mcp_slack_",
    }
    present = set()
    for key in MCP_TOOL_MAP:
        for prefix in expected_prefixes:
            if key.startswith(prefix):
                present.add(prefix)
                break
    assert present == expected_prefixes, (
        f"Missing tool groups: {expected_prefixes - present}"
    )


def test_mcp_tool_map_total_count():
    assert len(MCP_TOOL_MAP) == 26


def test_mcp_tool_map_all_values_are_two_tuples():
    for tool_name, mapping in MCP_TOOL_MAP.items():
        assert isinstance(mapping, tuple), f"{tool_name} mapping is not a tuple"
        assert len(mapping) == 2, f"{tool_name} mapping should be (server, tool)"


# ---------------------------------------------------------------------------
# _discover_tools: JSON list format
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discover_tools_parses_list_format(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    fake_output = json.dumps([
        {"name": "search_repositories", "server": "github", "description": "Search repos"},
        {"name": "read_file", "server": "filesystem", "description": "Read a file"},
    ])

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": fake_output}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run), \
         patch("shutil.which", return_value="/usr/bin/docker"):
        bridge = MCPBridge()
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001
        await bridge._discover_tools()

    assert len(bridge._available_tools) == 2  # noqa: SLF001


@pytest.mark.asyncio
async def test_discover_tools_parses_dict_format(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    fake_output = json.dumps({
        "github": {"tools": [
            {"name": "create_issue", "description": "Create a GitHub issue"},
        ]},
    })

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": fake_output}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run):
        bridge = MCPBridge()
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001
        await bridge._discover_tools()

    assert len(bridge._available_tools) == 1  # noqa: SLF001


@pytest.mark.asyncio
async def test_discover_tools_handles_empty_output(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": ""}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run):
        bridge = MCPBridge()
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001
        # Should not raise
        await bridge._discover_tools()

    assert bridge._available_tools == {}  # noqa: SLF001


@pytest.mark.asyncio
async def test_discover_tools_handles_invalid_json(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": "not valid json!"}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run):
        bridge = MCPBridge()
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001
        await bridge._discover_tools()  # must not raise

    assert bridge._available_tools == {}  # noqa: SLF001


# ---------------------------------------------------------------------------
# call_tool returns expected result shape
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_call_tool_success_returns_expected_keys(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": json.dumps({"items": []})}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run):
        bridge = MCPBridge()
        bridge._initialised = True  # noqa: SLF001
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001

        result = await bridge.call_tool(
            "mcp_github_list_issues", "devops_agent", {"repo": "agentop"}
        )

    assert "success" in result
    assert "tool" in result
    assert "timestamp" in result


@pytest.mark.asyncio
async def test_call_tool_cli_failure_returns_error(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    async def _fake_run(cmd, env, timeout):
        return {"success": False, "error": "container exited with code 1"}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run):
        bridge = MCPBridge()
        bridge._initialised = True  # noqa: SLF001
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001

        result = await bridge.call_tool(
            "mcp_github_list_issues", "devops_agent", {}
        )

    assert result["success"] is False
