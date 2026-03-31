"""
Integration tests for FastAPI route handlers — skills + memory management.

Covers:
  /skills     GET (list), GET /{id}, PATCH /{id} (toggle), POST /reload
  /memory     GET (overview), GET /{namespace}

Uses TestClient so the full request/response cycle (pydantic, routing,
dependency injection) is exercised without a real HTTP server.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routes.memory_management import router as memory_router
from backend.routes.skills import router as skills_router
from backend.skills.loader import LoadedSkill
from backend.skills.registry import SkillRegistry

# ---------------------------------------------------------------------------
# Minimal skill factory
# ---------------------------------------------------------------------------


def _make_skill(skill_id: str, enabled: bool = True) -> LoadedSkill:
    return LoadedSkill(
        skill_id=skill_id,
        name=f"Skill {skill_id}",
        version="1.0.0",
        description="Test skill",
        allowed_agents=["gsd_agent"],
        required_tools=[],
        risk_level="low",
        enabled=enabled,
        valid=True,
        invalid_reason=None,
        source_type="manifest",
        source_path=f"backend/skills/{skill_id}",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_registry(monkeypatch, tmp_path):
    """
    Replace the global SkillRegistry singleton with a test-controlled one
    that starts with two skills.
    """
    registry = SkillRegistry.__new__(SkillRegistry)
    registry._skills: dict[str, LoadedSkill] = {
        "skill_alpha": _make_skill("skill_alpha", enabled=True),
        "skill_beta": _make_skill("skill_beta", enabled=False),
    }
    # set_enabled writes state — give it a real path so it doesn't error
    registry.state_path = tmp_path / "skills_state.json"

    # Patch at the point-of-use in the route module
    monkeypatch.setattr("backend.routes.skills.get_skill_registry", lambda: registry)
    return registry


@pytest.fixture()
def app(mock_registry):
    application = FastAPI()
    application.include_router(skills_router)
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /skills
# ---------------------------------------------------------------------------


def test_list_skills_returns_all(client, mock_registry):
    response = client.get("/skills")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    ids = {s["skill_id"] for s in body}
    assert "skill_alpha" in ids
    assert "skill_beta" in ids


def test_list_skills_returns_empty_list_when_no_skills(monkeypatch):
    registry = SkillRegistry.__new__(SkillRegistry)
    registry._skills = {}
    monkeypatch.setattr("backend.routes.skills.get_skill_registry", lambda: registry)

    application = FastAPI()
    application.include_router(skills_router)
    c = TestClient(application)
    assert c.get("/skills").json() == []


# ---------------------------------------------------------------------------
# GET /skills/{skill_id}
# ---------------------------------------------------------------------------


def test_get_skill_returns_correct_record(client):
    response = client.get("/skills/skill_alpha")
    assert response.status_code == 200
    body = response.json()
    assert body["skill_id"] == "skill_alpha"
    assert body["enabled"] is True
    assert body["valid"] is True


def test_get_skill_not_found(client):
    response = client.get("/skills/nonexistent_skill")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# PATCH /skills/{skill_id}
# ---------------------------------------------------------------------------


def test_toggle_skill_enable(client, mock_registry):
    # skill_beta starts disabled
    response = client.patch("/skills/skill_beta", json={"enabled": True})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    # Verify the registry was actually updated
    assert mock_registry._skills["skill_beta"].enabled is True


def test_toggle_skill_disable(client, mock_registry):
    # skill_alpha starts enabled
    response = client.patch("/skills/skill_alpha", json={"enabled": False})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert mock_registry._skills["skill_alpha"].enabled is False


def test_toggle_skill_not_found(client):
    response = client.patch("/skills/ghost_skill", json={"enabled": True})
    assert response.status_code == 404


def test_toggle_skill_invalid_body(client):
    # missing required 'enabled' field
    response = client.patch("/skills/skill_alpha", json={"wrong_field": "oops"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# POST /skills/reload
# ---------------------------------------------------------------------------


def test_reload_skills_returns_dict(client, mock_registry, monkeypatch):
    monkeypatch.setattr(mock_registry, "reload", lambda: {"reloaded": 2})
    response = client.post("/skills/reload")
    assert response.status_code == 200
    assert response.json() == {"reloaded": 2}


# ---------------------------------------------------------------------------
# Memory management routes
# ---------------------------------------------------------------------------


@pytest.fixture()
def memory_app(tmp_path, monkeypatch):
    import backend.config as cfg
    import backend.memory as mem_module
    from backend.memory import MemoryStore

    mem_dir = tmp_path / "memory"
    monkeypatch.setattr(cfg, "MEMORY_DIR", mem_dir)
    # Patch the module-level binding used by MemoryStore methods
    monkeypatch.setattr(mem_module, "MEMORY_DIR", mem_dir)
    new_store = MemoryStore()
    monkeypatch.setattr(mem_module, "memory_store", new_store)
    # Also patch the import inside the route module
    import backend.routes.memory_management as mm_routes

    monkeypatch.setattr(mm_routes, "memory_store", new_store)

    application = FastAPI()
    application.include_router(memory_router)
    return application, new_store


def test_memory_overview_empty(memory_app):
    app, _store = memory_app
    c = TestClient(app)
    response = c.get("/memory")
    assert response.status_code == 200
    body = response.json()
    assert "namespaces" in body
    assert "shared_events_count" in body
    assert body["shared_events_count"] == 0


def test_memory_overview_with_data(memory_app):
    app, store = memory_app
    store.write("test_agent", "key1", "value1")
    c = TestClient(app)
    body = c.get("/memory").json()
    assert "test_agent" in body["namespaces"]


def test_memory_namespace_returns_data(memory_app):
    app, store = memory_app
    store.write("soul_core", "trust_score", 0.95)
    c = TestClient(app)
    response = c.get("/memory/soul_core")
    assert response.status_code == 200
    body = response.json()
    assert body["namespace"] == "soul_core"
    assert body["data"]["trust_score"] == 0.95
    assert body["size_bytes"] > 0


def test_memory_namespace_not_found(memory_app):
    app, _store = memory_app
    c = TestClient(app)
    response = c.get("/memory/does_not_exist")
    assert response.status_code == 404
