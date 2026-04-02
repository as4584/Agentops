"""Deterministic tests for route handlers using FastAPI TestClient.

Covers: skills routes, memory routes, agent control routes.
All backends mocked — no SQLite, no Ollama, no filesystem side effects.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.agent_control import a2a_router, set_orchestrator
from backend.routes.agent_control import router as agent_control_router
from backend.routes.memory_management import router as memory_router
from backend.routes.skills import router as skills_router


def _app_with(*routers):
    app = FastAPI()
    for r in routers:
        app.include_router(r)
    return app


# ── Skills Routes ────────────────────────────────────────────────────


class TestSkillsRoutes:
    @patch("backend.routes.skills.get_skill_registry")
    def test_list_skills_empty(self, mock_registry):
        mock_registry.return_value.list_skills.return_value = []
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.get("/skills")
        assert resp.status_code == 200
        assert resp.json() == []

    @patch("backend.routes.skills.get_skill_registry")
    def test_list_skills_returns_data(self, mock_registry):
        mock_registry.return_value.list_skills.return_value = [
            {"skill_id": "test_skill", "name": "Test", "enabled": True}
        ]
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.get("/skills")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["skill_id"] == "test_skill"

    @patch("backend.routes.skills.get_skill_registry")
    def test_get_skill_found(self, mock_registry):
        mock_skill = MagicMock()
        mock_skill.skill_id = "test_skill"
        mock_skill.name = "Test"
        mock_skill.version = "1.0.0"
        mock_skill.description = "A test skill"
        mock_skill.allowed_agents = ["gsd"]
        mock_skill.required_tools = ["file_reader"]
        mock_skill.risk_level = "low"
        mock_skill.enabled = True
        mock_skill.valid = True
        mock_skill.invalid_reason = None
        mock_skill.source_type = "manifest"
        mock_skill.source_path = "/skills/test_skill"
        mock_skill.skill_md = None
        mock_skill.tools_md = None
        mock_skill.soul_md = None
        mock_registry.return_value.get_skill.return_value = mock_skill
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.get("/skills/test_skill")
        assert resp.status_code == 200
        body = resp.json()
        assert body["skill_id"] == "test_skill"
        assert body["allowed_agents"] == ["gsd"]

    @patch("backend.routes.skills.get_skill_registry")
    def test_get_skill_not_found(self, mock_registry):
        mock_registry.return_value.get_skill.return_value = None
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.get("/skills/nonexistent")
        assert resp.status_code == 404

    @patch("backend.routes.skills.get_skill_registry")
    def test_toggle_skill_enable(self, mock_registry):
        updated = MagicMock()
        updated.skill_id = "test_skill"
        updated.enabled = True
        updated.valid = True
        updated.invalid_reason = None
        mock_registry.return_value.set_enabled.return_value = updated
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.patch("/skills/test_skill", json={"enabled": True})
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    @patch("backend.routes.skills.get_skill_registry")
    def test_toggle_skill_not_found(self, mock_registry):
        mock_registry.return_value.set_enabled.side_effect = KeyError("not found")
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.patch("/skills/nonexistent", json={"enabled": False})
        assert resp.status_code == 404

    @patch("backend.routes.skills.get_skill_registry")
    def test_reload_skills(self, mock_registry):
        mock_registry.return_value.reload.return_value = {"loaded": 3, "errors": 0}
        app = _app_with(skills_router)
        client = TestClient(app)
        resp = client.post("/skills/reload")
        assert resp.status_code == 200
        assert resp.json()["loaded"] == 3


# ── Memory Routes ────────────────────────────────────────────────────


class TestMemoryRoutes:
    @patch("backend.routes.memory_management.memory_store")
    def test_get_memory_overview(self, mock_store):
        mock_store.list_namespaces.return_value = ["soul_core", "devops_agent"]
        mock_store.get_namespace_size.side_effect = lambda ns: 1024 if ns == "soul_core" else 2048
        mock_store.get_shared_events.return_value = [{"event": "test"}]
        app = _app_with(memory_router)
        client = TestClient(app)
        resp = client.get("/memory")
        assert resp.status_code == 200
        body = resp.json()
        assert "soul_core" in body["namespaces"]
        assert body["namespaces"]["soul_core"]["size_bytes"] == 1024
        assert body["shared_events_count"] == 1

    @patch("backend.routes.memory_management.memory_store")
    def test_get_memory_namespace_found(self, mock_store):
        mock_store.list_namespaces.return_value = ["soul_core"]
        mock_store.read_all.return_value = {"goals": ["be reliable"]}
        mock_store.get_namespace_size.return_value = 512
        app = _app_with(memory_router)
        client = TestClient(app)
        resp = client.get("/memory/soul_core")
        assert resp.status_code == 200
        assert resp.json()["namespace"] == "soul_core"
        assert "goals" in resp.json()["data"]

    @patch("backend.routes.memory_management.memory_store")
    def test_get_memory_namespace_not_found(self, mock_store):
        mock_store.list_namespaces.return_value = ["soul_core"]
        app = _app_with(memory_router)
        client = TestClient(app)
        resp = client.get("/memory/nonexistent")
        assert resp.status_code == 404


# ── Agent Control Routes ─────────────────────────────────────────────


class TestAgentControlRoutes:
    def test_health(self):
        app = _app_with(agent_control_router)
        client = TestClient(app)
        resp = client.get("/agents-control/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_orchestrator_unavailable_returns_503(self):
        set_orchestrator(None)
        app = _app_with(a2a_router)
        client = TestClient(app)
        resp = client.get("/agents/messages", params={"agent_id": "soul_core"})
        assert resp.status_code == 503

    def test_list_messages_with_orchestrator(self):
        mock_orch = MagicMock()
        mock_orch.list_agent_messages.return_value = [{"id": "msg1", "from": "devops_agent"}]
        set_orchestrator(mock_orch)
        try:
            app = _app_with(a2a_router)
            client = TestClient(app)
            resp = client.get("/agents/messages", params={"agent_id": "soul_core"})
            assert resp.status_code == 200
            assert len(resp.json()) == 1
        finally:
            set_orchestrator(None)

    def test_send_message_success(self):
        mock_orch = MagicMock()
        mock_orch.send_agent_message.return_value = {"message_id": "msg-new", "status": "delivered"}
        set_orchestrator(mock_orch)
        try:
            app = _app_with(a2a_router)
            client = TestClient(app)
            resp = client.post(
                "/agents/messages/send",
                json={
                    "from_agent": "soul_core",
                    "to_agent": "devops_agent",
                    "purpose": "deploy",
                    "payload": {"branch": "dev"},
                },
            )
            assert resp.status_code == 200
            assert resp.json()["message_id"] == "msg-new"
        finally:
            set_orchestrator(None)

    def test_send_message_validation_error(self):
        mock_orch = MagicMock()
        mock_orch.send_agent_message.side_effect = ValueError("invalid agent")
        set_orchestrator(mock_orch)
        try:
            app = _app_with(a2a_router)
            client = TestClient(app)
            resp = client.post(
                "/agents/messages/send",
                json={
                    "from_agent": "soul_core",
                    "to_agent": "bad_agent",
                    "purpose": "test",
                },
            )
            assert resp.status_code == 400
        finally:
            set_orchestrator(None)

    def test_send_message_missing_required_fields(self):
        app = _app_with(a2a_router)
        client = TestClient(app)
        resp = client.post("/agents/messages/send", json={})
        assert resp.status_code == 422  # Pydantic validation

    def test_get_message_history(self):
        mock_orch = MagicMock()
        mock_orch.get_message_history.return_value = [
            {"id": "msg1", "from": "soul_core", "to": "devops_agent"},
        ]
        set_orchestrator(mock_orch)
        try:
            app = _app_with(a2a_router)
            client = TestClient(app)
            resp = client.get("/agents/messages/thread/thread-123")
            assert resp.status_code == 200
            assert len(resp.json()) == 1
        finally:
            set_orchestrator(None)
