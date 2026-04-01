from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _write_manifest_skill(
    root: Path,
    folder: str,
    skill_id: str,
    name: str,
    *,
    allowed_agents: list[str] | None = None,
    required_tools: list[str] | None = None,
    enabled: bool = True,
) -> None:
    skill_dir = root / folder
    skill_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "id": skill_id,
        "name": name,
        "version": "1.0.0",
        "description": f"{name} skill",
        "allowed_agents": allowed_agents or [],
        "required_tools": required_tools or [],
        "risk_level": "medium",
        "enabled": enabled,
    }
    (skill_dir / "skill.json").write_text(json.dumps(payload), encoding="utf-8")
    (skill_dir / "SKILL.md").write_text(f"Use {name} strategy", encoding="utf-8")


def test_registry_rejects_duplicate_skill_ids(tmp_path: Path):
    from backend.skills.registry import SkillRegistry

    skills_root = tmp_path / "skills"
    legacy_dir = tmp_path / "legacy"
    state_path = tmp_path / "skills_state.json"

    _write_manifest_skill(skills_root, "alpha", "duplicate_id", "Alpha")
    _write_manifest_skill(skills_root, "beta", "duplicate_id", "Beta")

    registry = SkillRegistry(skills_root=skills_root, legacy_skills_dir=legacy_dir, state_path=state_path)
    result = registry.reload()

    listed = registry.list_skills()
    ids = [row["skill_id"] for row in listed]
    assert ids == ["duplicate_id"]
    assert result["invalid_count"] >= 1
    assert "duplicate_id" in result["invalid"]


def test_prompt_gating_and_disabled_omission(tmp_path: Path):
    from backend.skills.registry import SkillRegistry

    skills_root = tmp_path / "skills"
    legacy_dir = tmp_path / "legacy"
    state_path = tmp_path / "skills_state.json"

    _write_manifest_skill(
        skills_root,
        "allowed",
        "allowed_skill",
        "Allowed",
        allowed_agents=["knowledge_agent"],
    )
    _write_manifest_skill(
        skills_root,
        "blocked",
        "blocked_skill",
        "Blocked",
        allowed_agents=["other_agent"],
    )

    registry = SkillRegistry(skills_root=skills_root, legacy_skills_dir=legacy_dir, state_path=state_path)
    prompt = registry.build_prompt(["allowed_skill", "blocked_skill"], agent_id="knowledge_agent")

    assert "Allowed" in prompt
    assert "Blocked" not in prompt

    registry.set_enabled("allowed_skill", False)
    prompt_after_disable = registry.build_prompt(["allowed_skill"], agent_id="knowledge_agent")
    assert prompt_after_disable == ""


def test_unknown_required_tool_flagged_and_skipped(tmp_path: Path):
    from backend.skills.registry import SkillRegistry

    skills_root = tmp_path / "skills"
    legacy_dir = tmp_path / "legacy"
    state_path = tmp_path / "skills_state.json"

    _write_manifest_skill(
        skills_root,
        "toolcheck",
        "tool_skill",
        "Tool Check",
        required_tools=["definitely_missing_tool"],
    )

    registry = SkillRegistry(skills_root=skills_root, legacy_skills_dir=legacy_dir, state_path=state_path)
    skill = registry.get_skill("tool_skill")

    assert skill is not None
    assert skill.valid is False
    assert skill.invalid_reason is not None

    prompt = registry.build_prompt(["tool_skill"], agent_id="knowledge_agent")
    assert prompt == ""


def test_skills_api_toggle_and_reload(tmp_path: Path, monkeypatch):
    from backend.routes import skills as skills_routes
    from backend.skills.registry import SkillRegistry

    skills_root = tmp_path / "skills"
    legacy_dir = tmp_path / "legacy"
    state_path = tmp_path / "skills_state.json"

    _write_manifest_skill(skills_root, "api", "api_skill", "API Skill")
    registry = SkillRegistry(skills_root=skills_root, legacy_skills_dir=legacy_dir, state_path=state_path)

    monkeypatch.setattr(skills_routes, "get_skill_registry", lambda: registry)

    app = FastAPI()
    app.include_router(skills_routes.router)
    client = TestClient(app)

    listed = client.get("/skills")
    assert listed.status_code == 200
    assert any(row["skill_id"] == "api_skill" for row in listed.json())

    toggled = client.patch("/skills/api_skill", json={"enabled": False})
    assert toggled.status_code == 200
    assert toggled.json()["enabled"] is False

    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["skills"]["api_skill"]["enabled"] is False

    reloaded = client.post("/skills/reload")
    assert reloaded.status_code == 200
    assert "loaded_count" in reloaded.json()


def test_manifest_skill_overrides_same_id_legacy_skill(tmp_path: Path):
    from backend.skills.registry import SkillRegistry

    skills_root = tmp_path / "skills"
    legacy_dir = tmp_path / "legacy"
    state_path = tmp_path / "skills_state.json"

    _write_manifest_skill(
        skills_root,
        "business_analysis_manifest",
        "business_analysis",
        "Business Analysis Manifest",
    )

    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "business_analysis.json").write_text(
        json.dumps(
            {
                "title": "Business Analysis Legacy",
                "domain": "Legacy business domain",
            }
        ),
        encoding="utf-8",
    )

    registry = SkillRegistry(skills_root=skills_root, legacy_skills_dir=legacy_dir, state_path=state_path)
    skill = registry.get_skill("business_analysis")

    assert skill is not None
    assert skill.source_type == "manifest"
    assert skill.name == "Business Analysis Manifest"
