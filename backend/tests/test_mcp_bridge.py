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

import json
from unittest.mock import patch

import pytest

from backend.mcp import MCP_TOOL_MAP, MCPBridge, is_mcp_tool

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


@pytest.mark.asyncio
async def test_mcp_bridge_graceful_degradation_lifecycle_without_docker(monkeypatch):
    """Initialise + call path should degrade cleanly when Docker CLI is absent."""
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    with patch("shutil.which", return_value=None):
        bridge = MCPBridge()
        await bridge.initialise()

    status = bridge.get_status()
    result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {})

    assert status["enabled"] is True
    assert status["initialised"] is True
    assert status["cli_available"] is False
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
        "mcp_github_",
        "mcp_filesystem_",
        "mcp_docker_",
        "mcp_time_",
        "mcp_fetch_",
        "mcp_sqlite_",
        "mcp_slack_",
    }
    present = set()
    for key in MCP_TOOL_MAP:
        for prefix in expected_prefixes:
            if key.startswith(prefix):
                present.add(prefix)
                break
    assert present == expected_prefixes, f"Missing tool groups: {expected_prefixes - present}"


def test_mcp_tool_map_total_count():
    # 26 original MCP tools + 5 GitNexus tools added in Sprint 5
    assert len(MCP_TOOL_MAP) == 31


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

    fake_output = json.dumps(
        [
            {"name": "search_repositories", "server": "github", "description": "Search repos"},
            {"name": "read_file", "server": "filesystem", "description": "Read a file"},
        ]
    )

    async def _fake_run(cmd, env, timeout):
        return {"success": True, "output": fake_output}

    with patch("backend.mcp._run_docker_mcp", new=_fake_run), patch("shutil.which", return_value="/usr/bin/docker"):
        bridge = MCPBridge()
        bridge._enabled = True  # noqa: SLF001
        bridge._cli_available = True  # noqa: SLF001
        await bridge._discover_tools()

    assert len(bridge._available_tools) == 2  # noqa: SLF001


@pytest.mark.asyncio
async def test_discover_tools_parses_dict_format(monkeypatch):
    monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

    fake_output = json.dumps(
        {
            "github": {
                "tools": [
                    {"name": "create_issue", "description": "Create a GitHub issue"},
                ]
            },
        }
    )

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

        result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {"repo": "agentop"})

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

        result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {})

    assert result["success"] is False


# ---------------------------------------------------------------------------
# Sprint 2 S2.2 — GitNexus health inspection
# ---------------------------------------------------------------------------


import importlib
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


def _make_meta(
    symbols: int = 11724,
    relationships: int = 31310,
    embeddings: int = 0,
    hours_ago: float = 1.0,
) -> dict:
    analyzed_at = (datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    return {
        "analyzedAt": analyzed_at,
        "stats": {
            "symbols": symbols,
            "relationships": relationships,
            "embeddings": embeddings,
        },
    }


class TestGitNexusHealth:
    def _get_health(self, **patch_cfg):
        import backend.mcp.gitnexus_health as gh
        importlib.reload(gh)
        for k, v in patch_cfg.items():
            setattr(gh, k, v)
        return gh.get_gitnexus_health

    def test_disabled_returns_disabled_state(self):
        from backend.mcp import gitnexus_health as gh
        with patch.object(gh, "GITNEXUS_ENABLED", False):
            state = gh.get_gitnexus_health()
        assert state.enabled is False
        assert state.usable is False
        assert "disabled" in state.reason.lower()

    def test_missing_meta_returns_index_not_found(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", tmp_path / "nonexistent.json"):
            state = gh.get_gitnexus_health()
        assert state.enabled is True
        assert state.index_exists is False
        assert state.usable is False
        assert "missing" in state.reason.lower() or "not found" in state.reason.lower()

    def test_malformed_meta_returns_index_not_found(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        bad_file = tmp_path / "meta.json"
        bad_file.write_text("{ not valid json }", encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", bad_file):
            state = gh.get_gitnexus_health()
        assert state.index_exists is False

    def test_meta_non_object_returns_not_found(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        bad_file = tmp_path / "meta.json"
        bad_file.write_text("[1, 2, 3]", encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", bad_file):
            state = gh.get_gitnexus_health()
        assert state.index_exists is False

    def test_fresh_meta_is_not_stale(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(hours_ago=0.5)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 24):
            state = gh.get_gitnexus_health()
        assert state.index_exists is True
        assert state.stale is False

    def test_old_meta_is_stale(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(hours_ago=30.0)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 24):
            state = gh.get_gitnexus_health()
        assert state.stale is True
        assert state.usable is False
        assert "stale" in state.reason.lower()

    def test_zero_stale_hours_never_stale(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(hours_ago=9999.0)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 0):
            state = gh.get_gitnexus_health()
        assert state.stale is False

    def test_symbol_and_relationship_counts_populated(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(symbols=100, relationships=200)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 0):
            state = gh.get_gitnexus_health()
        assert state.symbol_count == 100
        assert state.relationship_count == 200

    def test_zero_embeddings_state(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(embeddings=0)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 0), \
             patch.object(gh, "GITNEXUS_EXPECT_EMBEDDINGS", True):
            state = gh.get_gitnexus_health()
        assert state.embeddings_present is False
        assert "embeddings" in state.reason.lower()

    def test_embeddings_present_state(self, tmp_path):
        from backend.mcp import gitnexus_health as gh
        meta_file = tmp_path / "meta.json"
        meta_file.write_text(json.dumps(_make_meta(embeddings=5000)), encoding="utf-8")
        with patch.object(gh, "GITNEXUS_ENABLED", True), \
             patch.object(gh, "_META_PATH", meta_file), \
             patch.object(gh, "GITNEXUS_STALE_HOURS", 0), \
             patch.object(gh, "GITNEXUS_EXPECT_EMBEDDINGS", True):
            state = gh.get_gitnexus_health()
        assert state.embeddings_present is True
        assert "embeddings" not in state.reason.lower()


# ---------------------------------------------------------------------------
# Sprint 2 S2.5 — GitNexus fail-closed dispatch
# ---------------------------------------------------------------------------


class TestGitNexusFailClosed:
    """GitNexus calls must fail closed when the subsystem is not usable."""

    @pytest.mark.asyncio
    async def test_gitnexus_call_blocked_when_disabled(self, monkeypatch):
        monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)
        from backend.mcp import gitnexus_health as gh
        from backend.models import GitNexusHealthState

        disabled_state = GitNexusHealthState(enabled=False, reason="GitNexus is disabled.")
        with patch.object(gh, "get_gitnexus_health", return_value=disabled_state):
            bridge = MCPBridge()
            bridge._initialised = True  # noqa: SLF001
            bridge._enabled = True  # noqa: SLF001
            bridge._cli_available = True  # noqa: SLF001

            result = await bridge.call_tool("mcp_gitnexus_query", "code_review_agent", {"query": "auth"})

        assert result["success"] is False
        assert "GitNexus" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_gitnexus_call_blocked_when_stale(self, monkeypatch):
        monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)
        from backend.mcp import gitnexus_health as gh
        from backend.models import GitNexusHealthState

        stale_state = GitNexusHealthState(
            enabled=True,
            transport_available=True,
            index_exists=True,
            stale=True,
            reason="Index is stale (48h).",
        )
        with patch.object(gh, "get_gitnexus_health", return_value=stale_state):
            bridge = MCPBridge()
            bridge._initialised = True  # noqa: SLF001
            bridge._enabled = True  # noqa: SLF001
            bridge._cli_available = True  # noqa: SLF001

            result = await bridge.call_tool("mcp_gitnexus_context", "devops_agent", {"name": "foo"})

        assert result["success"] is False
        assert "GitNexus" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_non_gitnexus_tool_unaffected_by_gitnexus_health(self, monkeypatch):
        """A non-GitNexus MCP tool must NOT be blocked by GitNexus health checks."""
        monkeypatch.setattr("backend.mcp.MCP_GATEWAY_ENABLED", True)

        async def _fake_run(cmd, env, timeout):
            return {"success": True, "output": json.dumps({"items": []})}

        with patch("backend.mcp._run_docker_mcp", new=_fake_run):
            bridge = MCPBridge()
            bridge._initialised = True  # noqa: SLF001
            bridge._enabled = True  # noqa: SLF001
            bridge._cli_available = True  # noqa: SLF001

            result = await bridge.call_tool("mcp_github_list_issues", "devops_agent", {"repo": "test"})

        assert result["success"] is True


# ---------------------------------------------------------------------------
# Sprint 2 S2.7 — Parity: declared GitNexus tools vs runtime MCP_TOOL_MAP
# ---------------------------------------------------------------------------


class TestGitNexusToolInventoryParity:
    """GitNexus tool declarations must remain aligned between MCP_TOOL_MAP and agent permissions."""

    EXPECTED_GITNEXUS_TOOLS = {
        "mcp_gitnexus_query",
        "mcp_gitnexus_context",
        "mcp_gitnexus_impact",
        "mcp_gitnexus_detect_changes",
        "mcp_gitnexus_list_repos",
    }

    def test_all_expected_gitnexus_tools_in_mcp_map(self):
        for tool_name in self.EXPECTED_GITNEXUS_TOOLS:
            assert tool_name in MCP_TOOL_MAP, f"{tool_name} missing from MCP_TOOL_MAP"

    def test_gitnexus_tools_map_to_gitnexus_server(self):
        for tool_name in self.EXPECTED_GITNEXUS_TOOLS:
            server, _ = MCP_TOOL_MAP[tool_name]
            assert server == "gitnexus", f"{tool_name} mapped to wrong server: {server}"

    def test_no_public_gitnexus_route_by_arbitrary_name(self):
        """GitNexus tools must only be in MCP_TOOL_MAP under the 'gitnexus' server.
        No ad-hoc keys should introduce new public gitnexus surfaces."""
        gitnexus_in_map = [k for k, v in MCP_TOOL_MAP.items() if v[0] == "gitnexus"]
        assert set(gitnexus_in_map) == self.EXPECTED_GITNEXUS_TOOLS, (
            f"Unexpected GitNexus tools in MCP_TOOL_MAP: {set(gitnexus_in_map) - self.EXPECTED_GITNEXUS_TOOLS}"
        )
