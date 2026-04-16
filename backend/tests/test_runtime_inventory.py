"""
Sprint 3 — Runtime inventory tests.

Verifies that generate_runtime_inventory.py produces a structurally
correct, consistent inventory artifact.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent


def _generate_inventory() -> dict:
    """Run the inventory script and return parsed JSON."""
    result = subprocess.run(
        [sys.executable, "scripts/generate_runtime_inventory.py", "--stdout"],
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
        timeout=30,
    )
    assert result.returncode == 0, f"Inventory script failed:\n{result.stderr}"
    return json.loads(result.stdout)


class TestRuntimeInventory:
    """Runtime inventory must contain required sections with valid shapes."""

    @pytest.fixture(scope="class")
    def inv(self):
        return _generate_inventory()

    def test_has_deployment_mode(self, inv):
        assert "deployment_mode" in inv
        assert inv["deployment_mode"] == "operator_only"

    def test_has_native_tools(self, inv):
        assert "native_tools" in inv
        assert isinstance(inv["native_tools"], list)
        assert inv["native_tool_count"] == len(inv["native_tools"])
        assert inv["native_tool_count"] > 0

    def test_has_mcp_tools(self, inv):
        assert "mcp_tools" in inv
        assert isinstance(inv["mcp_tools"], list)
        assert inv["mcp_tool_count"] > 0

    def test_has_gitnexus_tools(self, inv):
        assert "gitnexus_tools" in inv
        gn = set(inv["gitnexus_tools"])
        expected = {
            "mcp_gitnexus_query",
            "mcp_gitnexus_context",
            "mcp_gitnexus_impact",
            "mcp_gitnexus_detect_changes",
            "mcp_gitnexus_list_repos",
        }
        assert gn == expected

    def test_has_agent_permissions(self, inv):
        assert "agent_tool_permissions" in inv
        perms = inv["agent_tool_permissions"]
        assert isinstance(perms, dict)
        assert len(perms) > 0

    def test_approved_agents_have_gitnexus_tools(self, inv):
        perms = inv["agent_tool_permissions"]
        approved = {"code_review_agent", "devops_agent", "security_agent"}
        gitnexus_tools = set(inv["gitnexus_tools"])
        for agent in approved:
            assert agent in perms, f"Approved agent '{agent}' missing from permissions"
            agent_tools = set(perms[agent])
            assert agent_tools & gitnexus_tools, (
                f"Approved agent '{agent}' has no GitNexus tools in permissions"
            )

    def test_gitnexus_health_present(self, inv):
        assert "gitnexus_health" in inv
        gn = inv["gitnexus_health"]
        for key in ("enabled", "usable", "index_exists", "symbol_count", "stale", "reason"):
            assert key in gn, f"gitnexus_health missing key: {key}"

    def test_mcp_tools_grouped_by_server(self, inv):
        by_server = inv["mcp_tools_by_server"]
        assert "gitnexus" in by_server
        assert isinstance(by_server["gitnexus"], list)

    def test_generated_at_is_iso(self, inv):
        from datetime import datetime
        ts = inv["generated_at"]
        # Must parse as ISO timestamp without raising
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_no_extra_gitnexus_tools_in_permissions(self, inv):
        """Unapproved agents must not hold GitNexus tool permissions."""
        approved = frozenset({"code_review_agent", "devops_agent", "security_agent"})
        gitnexus_prefix = "mcp_gitnexus_"
        perms = inv["agent_tool_permissions"]
        for agent, tools in perms.items():
            if agent in approved:
                continue
            agent_gn = [t for t in tools if t.startswith(gitnexus_prefix)]
            assert not agent_gn, (
                f"Unapproved agent '{agent}' holds GitNexus tools: {agent_gn}"
            )
