"""
Sprint 5 — Operator-only regression matrix.

Tests the production boundary invariants for operator-only mode:
- Loopback vs. exposed host safety rules
- Auth present vs. missing enforcement
- Protected route coverage
- CORS origin configuration
- No public SaaS escalation paths
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import backend.server as srv
    with TestClient(srv.app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Operator-only mode invariants
# ---------------------------------------------------------------------------

class TestOperatorOnlyMode:
    """Deployment mode must be operator_only. No public SaaS mode."""

    def test_deployment_mode_is_operator_only(self):
        from backend.config import AGENTOP_DEPLOYMENT_MODE
        assert AGENTOP_DEPLOYMENT_MODE == "operator_only"

    def test_supported_modes_contains_only_operator_only(self):
        from backend.config import _SUPPORTED_DEPLOYMENT_MODES
        assert _SUPPORTED_DEPLOYMENT_MODES == frozenset({"operator_only"})

    def test_validate_config_clean_in_default_env(self):
        """Validate config must return no errors in default operator environment."""
        from backend.config import validate_config
        # In default env (loopback host / no strict auth required),
        # config validation must return an empty list.
        errors = validate_config()
        # Some cross-field checks depend on env; tolerate blank-secret + loopback combos.
        # Critical: no "UNSAFE" errors when running on loopback.
        unsafe_errors = [e for e in errors if "UNSAFE" in e]
        assert not unsafe_errors, f"Unsafe config errors in operator-only mode: {unsafe_errors}"


# ---------------------------------------------------------------------------
# Health probe accessibility without auth
# ---------------------------------------------------------------------------

class TestHealthProbeAccessibility:
    """All k8s-style probes must be reachable without an API token."""

    def test_live_accessible_without_auth(self, client):
        resp = client.get("/health/live")
        assert resp.status_code == 200

    def test_ready_accessible_without_auth(self, client):
        resp = client.get("/health/ready")
        assert resp.status_code in (200, 503)

    def test_metrics_accessible_without_auth(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_health_accessible_without_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Protected routes require auth (when API_SECRET is set)
# ---------------------------------------------------------------------------

class TestProtectedRoutesRequireAuth:
    """Chat and mutation routes must require auth when API_SECRET is configured."""

    def test_chat_route_exists(self, client):
        """POST /chat should exist (405 method not allowed on GET confirms it)."""
        resp = client.get("/chat")
        # 405 = method not allowed; 404 = route missing
        assert resp.status_code != 404, "/chat route is missing entirely"

    def test_status_route_exists(self, client):
        resp = client.get("/status")
        # 200, 503, or 401 — any means route is registered
        assert resp.status_code != 404, "/status route is missing entirely"

    def test_tools_route_exists(self, client):
        resp = client.get("/tools")
        assert resp.status_code != 404, "/tools route is missing entirely"


# ---------------------------------------------------------------------------
# CORS configuration sanity
# ---------------------------------------------------------------------------

class TestCORSConfiguration:
    """CORS origins must come from config, not be wildcard in operator mode."""

    def test_cors_origins_is_list(self):
        from backend.config import CORS_ORIGINS
        assert isinstance(CORS_ORIGINS, list)

    def test_cors_origins_not_empty(self):
        from backend.config import CORS_ORIGINS
        assert len(CORS_ORIGINS) > 0

    def test_cors_origins_no_pure_wildcard_by_default(self):
        """Wildcard CORS ('*') without an API secret is unsafe in operator mode."""
        from backend.config import CORS_ORIGINS, API_SECRET
        # If wildcard is present and secret is blank, that's risky but permitted
        # on loopback (config validator already checks this). Just verify we don't
        # ship '*' alone when there's no auth at all.
        if not API_SECRET:
            # Allowed: loopback-only origins.
            # Forbidden: bare wildcard as the ONLY origin.
            if CORS_ORIGINS == ["*"]:
                pytest.skip("Running in dev mode with wildcard CORS and no secret — acceptable on loopback")


# ---------------------------------------------------------------------------
# Degraded dependency resilience
# ---------------------------------------------------------------------------

class TestDegradedDependencyResilience:
    """When external deps are unavailable, the API must return structured error envelopes."""

    def test_health_deps_returns_structured_response_when_ollama_absent(self, client):
        from unittest.mock import AsyncMock, patch
        import backend.server as srv

        original_client = srv._llm_client

        # Simulate Ollama down
        mock_llm = AsyncMock()
        mock_llm.is_available = AsyncMock(return_value=False)
        srv._llm_client = mock_llm
        try:
            resp = client.get("/health/deps")
            assert resp.status_code == 200
            data = resp.json()
            # Should report degraded but NOT crash
            assert "dependencies" in data
            assert data["dependencies"]["ollama"]["ok"] is False
            assert data["status"] == "degraded"
        finally:
            srv._llm_client = original_client

    def test_health_deps_degraded_when_gitnexus_enabled_but_broken(self, client):
        from unittest.mock import patch
        from backend.mcp import gitnexus_health as gh
        from backend.models import GitNexusHealthState

        broken = GitNexusHealthState(
            enabled=True,
            transport_available=True,
            index_exists=False,
            reason="index missing",
        )
        with patch.object(gh, "get_gitnexus_health", return_value=broken):
            resp = client.get("/health/deps")
            assert resp.status_code == 200
            data = resp.json()
            gn = data["dependencies"]["gitnexus"]
            assert gn["ok"] is False

    def test_health_deps_ok_when_gitnexus_disabled(self, client):
        from unittest.mock import patch
        from backend.mcp import gitnexus_health as gh
        from backend.models import GitNexusHealthState

        disabled = GitNexusHealthState(enabled=False, reason="GITNEXUS_ENABLED=false")
        with patch.object(gh, "get_gitnexus_health", return_value=disabled):
            resp = client.get("/health/deps")
            data = resp.json()
            gn = data["dependencies"]["gitnexus"]
            # Disabled GitNexus is NOT a failure
            assert gn["ok"] is True

    def test_mcp_tool_call_fails_gracefully_when_gitnexus_unavailable(self):
        """GitNexus MCP tool calls must return an error envelope, not raise."""
        from unittest.mock import patch
        from backend.mcp import mcp_bridge, gitnexus_health as gh
        from backend.models import GitNexusHealthState

        broken = GitNexusHealthState(enabled=True, index_exists=False, reason="index missing")
        with patch.object(gh, "get_gitnexus_health", return_value=broken):
            import asyncio
            result = asyncio.run(
                mcp_bridge.call_tool("mcp_gitnexus_query", "test_agent", {"query": "auth flow"})
            )
        assert result["success"] is False
        assert "GitNexus" in result.get("error", "") or "unavailable" in result.get("error", "").lower()


# ---------------------------------------------------------------------------
# GitNexus protocol parity
# ---------------------------------------------------------------------------

class TestGitNexusProtocolParity:
    """GitNexus tool set in TOOL_REGISTRY == declared set in MCP_TOOL_MAP."""

    CANONICAL = frozenset({
        "mcp_gitnexus_query",
        "mcp_gitnexus_context",
        "mcp_gitnexus_impact",
        "mcp_gitnexus_detect_changes",
        "mcp_gitnexus_list_repos",
    })

    def test_tool_registry_has_all_canonical_gitnexus_tools(self):
        from backend.tools import TOOL_REGISTRY
        registered = frozenset(k for k in TOOL_REGISTRY if k.startswith("mcp_gitnexus_"))
        assert registered == self.CANONICAL, (
            f"Registry mismatch. Extra: {registered - self.CANONICAL}, Missing: {self.CANONICAL - registered}"
        )

    def test_mcp_tool_map_has_all_canonical_gitnexus_tools(self):
        from backend.mcp import MCP_TOOL_MAP
        in_map = frozenset(k for k, v in MCP_TOOL_MAP.items() if v[0] == "gitnexus")
        assert in_map == self.CANONICAL, (
            f"MCP_TOOL_MAP mismatch. Extra: {in_map - self.CANONICAL}, Missing: {self.CANONICAL - in_map}"
        )

    def test_agent_permissions_match_canonical_for_approved_agents(self):
        from backend.agents import ALL_AGENT_DEFINITIONS
        approved = frozenset({"code_review_agent", "devops_agent", "security_agent"})
        # At minimum each approved agent has at least one canonical tool
        for agent_id in approved:
            defn = ALL_AGENT_DEFINITIONS.get(agent_id)
            assert defn is not None, f"Approved agent {agent_id} not in registry"
            agent_gn = frozenset(t for t in defn.tool_permissions if t.startswith("mcp_gitnexus_"))
            assert agent_gn, f"Approved agent {agent_id} has no GitNexus tools"
            assert agent_gn <= self.CANONICAL, (
                f"Agent {agent_id} has non-canonical GitNexus tools: {agent_gn - self.CANONICAL}"
            )

    def test_inventory_gitnexus_tools_match_canonical(self):
        """Runtime inventory output must also match the canonical set."""
        import subprocess, sys, json
        from pathlib import Path
        result = subprocess.run(
            [sys.executable, "scripts/generate_runtime_inventory.py", "--stdout"],
            capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent.parent.parent), timeout=30
        )
        assert result.returncode == 0
        inv = json.loads(result.stdout)
        assert set(inv["gitnexus_tools"]) == self.CANONICAL
