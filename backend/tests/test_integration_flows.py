"""
Integration tests — GSD, Content Pipeline, Gateway.
=====================================================
Uses FastAPI TestClient with mocked backends so no live Ollama needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# 1. GSD route tests
# ---------------------------------------------------------------------------


class TestGSDRoutes:
    """Integration tests for /api/gsd endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from backend.routes.gsd import router

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_get_state(self):
        """GET /api/gsd/state returns current GSD state."""
        mock_state = MagicMock()
        mock_state.model_dump.return_value = {"phase": 0, "status": "idle"}
        mock_store = MagicMock()
        mock_store.load_state.return_value = mock_state

        with patch("backend.database.gsd_store.gsd_store", mock_store):
            resp = self.client.get("/api/gsd/state")
            assert resp.status_code == 200
            data = resp.json()
            assert data["phase"] == 0

    def test_get_phases(self):
        """GET /api/gsd/phases returns list of phases."""
        mock_store = MagicMock()
        mock_store.list_phases.return_value = []

        with patch("backend.database.gsd_store.gsd_store", mock_store):
            resp = self.client.get("/api/gsd/phases")
            assert resp.status_code == 200
            assert isinstance(resp.json().get("phases", resp.json()), list)

    def test_quick_task(self):
        """POST /api/gsd/quick triggers a quick GSD task."""
        from backend.models.gsd import GSDQuickResult

        mock_result = GSDQuickResult(
            prompt="fix the README",
            response="Done — updated README.md",
            committed=False,
            timestamp=datetime.now(UTC),
        )
        mock_agent = MagicMock()
        mock_agent.quick = AsyncMock(return_value=mock_result)

        with patch("backend.agents.gsd_agent.GSDAgent", return_value=mock_agent):
            resp = self.client.post(
                "/api/gsd/quick",
                json={"prompt": "fix the README", "full": False},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert "response" in data


# ---------------------------------------------------------------------------
# 2. Content pipeline route tests
# ---------------------------------------------------------------------------


class TestContentPipelineRoutes:
    """Integration tests for /content endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from backend.routes.content_pipeline import router

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_content_health(self):
        """GET /content/health returns ok."""
        resp = self.client.get("/content/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_content_status(self):
        """GET /content/status returns job summary."""
        mock_pipeline = MagicMock()
        mock_pipeline.get_status_summary.return_value = {
            "total": 0,
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }
        with patch(
            "backend.routes.content_pipeline.get_pipeline",
            return_value=mock_pipeline,
        ):
            resp = self.client.get("/content/status")
            assert resp.status_code == 200
            data = resp.json()
            assert "total" in data

    def test_list_jobs_empty(self):
        """GET /content/jobs returns empty list when no jobs exist."""
        with patch("backend.routes.content_pipeline.job_store") as mock_store:
            mock_store.list_all.return_value = []
            resp = self.client.get("/content/jobs")
            assert resp.status_code == 200
            assert resp.json() == []

    def test_list_ideas_empty(self):
        """GET /content/ideas returns empty list when no ideas pending."""
        mock_pipeline = MagicMock()
        mock_pipeline.get_pending_ideas.return_value = []
        with patch(
            "backend.routes.content_pipeline.get_pipeline",
            return_value=mock_pipeline,
        ):
            resp = self.client.get("/content/ideas")
            assert resp.status_code == 200
            assert resp.json() == []


# ---------------------------------------------------------------------------
# 3. Chat gateway route tests
# ---------------------------------------------------------------------------


class TestGatewayRoutes:
    """Integration tests for /v1 gateway endpoints."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from backend.routes.gateway import router

        self.app = FastAPI()
        self.app.include_router(router)
        self.client = TestClient(self.app)

    def test_gateway_health(self):
        """GET /v1/health returns gateway status."""
        mock_monitor = MagicMock()
        mock_monitor.get_status.return_value = {
            "status": "healthy",
            "models_loaded": 1,
        }
        with patch(
            "backend.routes.gateway.get_health_monitor",
            return_value=mock_monitor,
        ):
            resp = self.client.get("/v1/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "healthy"
