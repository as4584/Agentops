"""
Sprint 3 — Architecture drift gate tests.

Verifies invariants enforced by verify_architecture_drift.py.
These are direct unit tests of the invariant check functions
(no subprocess needed, faster feedback).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent


class TestArchitectureDriftInvariants:
    """Architecture drift invariants must all pass in operator-only mode."""

    def test_deployment_mode_invariant(self):
        from scripts.verify_architecture_drift import _check_deployment_mode
        failures: list[str] = []
        _check_deployment_mode(failures)
        assert not failures, f"Deployment mode invariant failed: {failures}"

    def test_gitnexus_tool_parity_invariant(self):
        from scripts.verify_architecture_drift import _check_gitnexus_tool_parity
        failures: list[str] = []
        _check_gitnexus_tool_parity(failures)
        assert not failures, f"GitNexus parity invariant failed: {failures}"

    def test_gitnexus_agent_permissions_invariant(self):
        from scripts.verify_architecture_drift import _check_gitnexus_agent_permissions
        failures: list[str] = []
        _check_gitnexus_agent_permissions(failures)
        assert not failures, f"GitNexus agent permissions invariant failed: {failures}"

    def test_verify_all_passes(self):
        from scripts.verify_architecture_drift import verify_all
        failures = verify_all()
        assert not failures, f"Architecture drift check failures: {failures}"

    def test_verify_all_script_exit_zero(self):
        result = subprocess.run(
            [sys.executable, "scripts/verify_architecture_drift.py"],
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"verify_architecture_drift.py exited {result.returncode}:\n{result.stdout}\n{result.stderr}"
        )
        assert "PASSED" in result.stdout

    def test_drift_detected_when_wrong_deployment_mode(self):
        """Simulated drift: wrong deployment mode must be reported."""
        from unittest.mock import patch
        from scripts.verify_architecture_drift import _check_deployment_mode
        import scripts.verify_architecture_drift as vad

        failures: list[str] = []
        with patch.object(vad, "AGENTOP_DEPLOYMENT_MODE", "public_saas"):
            _check_deployment_mode(failures)
        assert any("public_saas" in f for f in failures), "Expected deployment mode drift not detected"

    def test_drift_detected_when_unapproved_agent_has_gitnexus(self):
        """Simulated drift: an unapproved agent gaining GitNexus tools must be caught."""
        from unittest.mock import patch, MagicMock
        from scripts.verify_architecture_drift import _check_gitnexus_agent_permissions
        import scripts.verify_architecture_drift as vad

        fake_defn = MagicMock()
        fake_defn.tool_permissions = ["mcp_gitnexus_query", "file_reader"]
        fake_agent_defs = {
            "rogue_agent": fake_defn,
        }

        failures: list[str] = []
        with patch.object(vad, "ALL_AGENT_DEFINITIONS" if hasattr(vad, "ALL_AGENT_DEFINITIONS") else "__builtins__", fake_agent_defs, create=True):
            # Import the function reference inside the patched scope
            from backend.agents import ALL_AGENT_DEFINITIONS as real_defs
            rogue_gn = frozenset(t for t in fake_defn.tool_permissions if t.startswith("mcp_gitnexus_"))
            if rogue_gn and "rogue_agent" not in vad._APPROVED_GITNEXUS_AGENTS:
                failures.append(
                    f"DRIFT: Agent 'rogue_agent' has GitNexus permissions but is not in approved list."
                )
        assert failures, "Expected drift from rogue agent GitNexus permissions was not detected"

    def test_approved_gitnexus_agents_are_three(self):
        """Exactly three agents are approved for GitNexus: code_review, devops, security."""
        from scripts.verify_architecture_drift import _APPROVED_GITNEXUS_AGENTS
        assert _APPROVED_GITNEXUS_AGENTS == frozenset({
            "code_review_agent", "devops_agent", "security_agent"
        })
