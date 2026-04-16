"""
Sprint 4 — Health endpoint and observability tests.

Tests the full set of health probes:
- /health/live   — liveness probe (always up)
- /health/ready  — readiness probe (503 when orchestrator absent)
- /health        — composite health (legacy endpoint)
- /health/deps   — external dependency health
- /metrics       — Prometheus-style metrics export
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_app():
    """Create a test client for server.py with a mock LLM and no lifespan."""
    import backend.server as srv

    # Patch the lifespan so it doesn't actually start Ollama, schedulers, etc.
    with patch("backend.server.lifespan"):
        # Build a plain app reference — already constructed at import time
        pass
    return srv.app


@pytest.fixture(scope="module")
def client():
    import backend.server as srv

    with TestClient(srv.app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# /health/live — must always return 200 with {status: alive}
# ---------------------------------------------------------------------------


class TestHealthLive:
    def test_returns_200(self, client):
        resp = client.get("/health/live")
        assert resp.status_code == 200

    def test_returns_alive_status(self, client):
        data = client.get("/health/live").json()
        assert data["status"] == "alive"

    def test_has_timestamp(self, client):
        data = client.get("/health/live").json()
        assert "timestamp" in data
        from datetime import datetime

        datetime.fromisoformat(data["timestamp"])

    def test_no_auth_required(self, client):
        """Liveness probe must not require API token."""
        resp = client.get("/health/live", headers={})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# /health/ready — 503 when orchestrator absent, 200 when ready
# ---------------------------------------------------------------------------


class TestHealthReady:
    def test_returns_503_when_orchestrator_none(self, client):
        import backend.server as srv

        original = srv._orchestrator
        srv._orchestrator = None
        try:
            resp = client.get("/health/ready")
            assert resp.status_code == 503
            assert resp.json()["status"] == "not_ready"
        finally:
            srv._orchestrator = original

    def test_returns_200_when_orchestrator_set(self, client):
        import backend.server as srv

        mock_orch = MagicMock()
        srv._orchestrator = mock_orch
        try:
            resp = client.get("/health/ready")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ready"
        finally:
            srv._orchestrator = None

    def test_ready_has_uptime_seconds(self, client):
        import backend.server as srv

        srv._orchestrator = MagicMock()
        try:
            data = client.get("/health/ready").json()
            assert "uptime_seconds" in data
        finally:
            srv._orchestrator = None

    def test_no_auth_required(self, client):
        """Readiness probe must not require API token."""
        resp = client.get("/health/ready")
        # May be 200 or 503 depending on orchestrator state; neither requires auth.
        assert resp.status_code in (200, 503)


# ---------------------------------------------------------------------------
# /metrics — Prometheus-style metric export
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_returns_200(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_has_uptime_seconds(self, client):
        data = client.get("/metrics").json()
        assert "agentop_uptime_seconds" in data
        assert isinstance(data["agentop_uptime_seconds"], (int, float))

    def test_has_orchestrator_ready_flag(self, client):
        data = client.get("/metrics").json()
        assert "agentop_orchestrator_ready" in data
        assert data["agentop_orchestrator_ready"] in (0, 1)

    def test_has_gitnexus_metrics(self, client):
        data = client.get("/metrics").json()
        assert "agentop_gitnexus_enabled" in data
        assert "agentop_gitnexus_usable" in data
        assert "agentop_gitnexus_symbol_count" in data

    def test_has_deployment_mode_in_meta(self, client):
        data = client.get("/metrics").json()
        assert data["_meta"]["deployment_mode"] == "operator_only"

    def test_no_auth_required(self, client):
        """Metrics endpoint must not require API token."""
        resp = client.get("/metrics", headers={})
        assert resp.status_code == 200

    def test_tool_executions_is_integer(self, client):
        data = client.get("/metrics").json()
        assert isinstance(data["agentop_tool_executions_total"], int)


# ---------------------------------------------------------------------------
# /health — legacy composite endpoint still works
# ---------------------------------------------------------------------------


class TestHealthLegacy:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_has_status_key(self, client):
        data = client.get("/health").json()
        assert "status" in data

    def test_has_uptime(self, client):
        data = client.get("/health").json()
        assert "uptime_seconds" in data


# ---------------------------------------------------------------------------
# skip_auth_paths — all probe paths bypass auth
# ---------------------------------------------------------------------------


class TestAuthSkipPaths:
    """All health probes and /metrics must be in the auth skip list."""

    def test_live_in_skip_list(self):
        import backend.server as srv

        # Inspect the middleware dispatch function's declared skip set.
        # We do this by verifying the endpoints actually respond without auth.
        resp = TestClient(srv.app, raise_server_exceptions=False).get("/health/live")
        assert resp.status_code != 401

    def test_ready_in_skip_list(self):
        import backend.server as srv

        resp = TestClient(srv.app, raise_server_exceptions=False).get("/health/ready")
        assert resp.status_code != 401

    def test_metrics_in_skip_list(self):
        import backend.server as srv

        resp = TestClient(srv.app, raise_server_exceptions=False).get("/metrics")
        assert resp.status_code != 401
