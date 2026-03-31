"""
Tests for backend/skills/loader.py — SkillManifest, LoadedSkill, load_manifest_skill,
load_legacy_json_skill.

Uses tmp_path for filesystem isolation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.skills.loader import (
    LoadedSkill,
    SkillManifest,
    load_legacy_json_skill,
    load_manifest_skill,
)

# ---------------------------------------------------------------------------
# SkillManifest validation
# ---------------------------------------------------------------------------


class TestSkillManifest:
    def test_minimal_valid_manifest(self):
        m = SkillManifest(id="test_skill", name="Test", version="1.0.0")
        assert m.allowed_agents == []
        assert m.required_tools == []
        assert m.risk_level == "medium"
        assert m.enabled is True

    def test_full_manifest(self):
        m = SkillManifest(
            id="newsletter",
            name="Newsletter",
            version="2.1.0",
            description="Weekly newsletter",
            allowed_agents=["gsd", "content"],
            required_tools=["file_reader"],
            risk_level="low",
            enabled=False,
        )
        assert m.enabled is False
        assert "gsd" in m.allowed_agents

    def test_empty_id_raises(self):
        with pytest.raises(Exception):
            SkillManifest(id="", name="X", version="1.0")

    def test_empty_name_raises(self):
        with pytest.raises(Exception):
            SkillManifest(id="x", name="", version="1.0")

    def test_invalid_risk_level_raises(self):
        with pytest.raises(Exception):
            SkillManifest(id="x", name="X", version="1.0", risk_level="extreme")


# ---------------------------------------------------------------------------
# LoadedSkill
# ---------------------------------------------------------------------------


class TestLoadedSkill:
    def _make(self, **kwargs) -> LoadedSkill:
        defaults = {
            "skill_id": "my_skill",
            "name": "My Skill",
            "version": "1.0.0",
            "description": "A test skill",
            "allowed_agents": ["gsd"],
            "required_tools": [],
            "risk_level": "low",
            "enabled": True,
            "source_path": "/tmp/my_skill",
            "source_type": "manifest",
        }
        defaults.update(kwargs)
        return LoadedSkill(**defaults)  # type: ignore[arg-type]

    def test_defaults(self):
        skill = self._make()
        assert skill.valid is True
        assert skill.invalid_reason is None
        assert skill.skill_md == ""
        assert skill.tools_md == ""
        assert skill.soul_md == ""

    def test_to_prompt_section_description_only(self):
        skill = self._make()
        section = skill.to_prompt_section()
        assert "[Skill: My Skill]" in section
        assert "A test skill" in section

    def test_to_prompt_section_with_skill_md(self):
        skill = self._make(skill_md="## Instructions\nDo the thing.")
        section = skill.to_prompt_section()
        assert "SKILL:" in section
        assert "Do the thing." in section

    def test_to_prompt_section_with_tools_md(self):
        skill = self._make(tools_md="file_reader: reads files")
        section = skill.to_prompt_section()
        assert "TOOLS:" in section
        assert "file_reader" in section

    def test_to_prompt_section_with_soul_md(self):
        skill = self._make(soul_md="Be helpful.")
        section = skill.to_prompt_section()
        assert "SOUL:" in section
        assert "Be helpful." in section

    def test_to_prompt_section_whitespace_only_md_not_included(self):
        skill = self._make(skill_md="   \n  ", tools_md="")
        section = skill.to_prompt_section()
        assert "SKILL:" not in section
        assert "TOOLS:" not in section

    def test_invalid_skill(self):
        skill = self._make(valid=False, invalid_reason="Missing required field")
        assert skill.valid is False
        assert skill.invalid_reason == "Missing required field"

    def test_legacy_source_type(self):
        skill = self._make(source_type="legacy_json")
        assert skill.source_type == "legacy_json"


# ---------------------------------------------------------------------------
# load_manifest_skill
# ---------------------------------------------------------------------------


class TestLoadManifestSkill:
    def _write_manifest(self, skill_dir: Path, data: dict) -> None:
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "skill.json").write_text(json.dumps(data), encoding="utf-8")

    def test_loads_minimal_manifest(self, tmp_path):
        skill_dir = tmp_path / "my_skill"
        self._write_manifest(
            skill_dir,
            {
                "id": "my_skill",
                "name": "My Skill",
                "version": "1.0.0",
            },
        )
        skill = load_manifest_skill(skill_dir)
        assert skill.skill_id == "my_skill"
        assert skill.source_type == "manifest"
        assert skill.valid is True
        assert skill.skill_md == ""

    def test_loads_skill_md_if_present(self, tmp_path):
        skill_dir = tmp_path / "rich_skill"
        self._write_manifest(
            skill_dir,
            {
                "id": "rich_skill",
                "name": "Rich",
                "version": "1.0",
            },
        )
        (skill_dir / "SKILL.md").write_text("## How to use\nStep 1.", encoding="utf-8")
        skill = load_manifest_skill(skill_dir)
        assert "Step 1." in skill.skill_md

    def test_loads_tools_md_if_present(self, tmp_path):
        skill_dir = tmp_path / "tools_skill"
        self._write_manifest(skill_dir, {"id": "tools_skill", "name": "T", "version": "1.0"})
        (skill_dir / "TOOLS.md").write_text("tool1: does x", encoding="utf-8")
        skill = load_manifest_skill(skill_dir)
        assert "tool1" in skill.tools_md

    def test_loads_soul_md_if_present(self, tmp_path):
        skill_dir = tmp_path / "soul_skill"
        self._write_manifest(skill_dir, {"id": "soul_skill", "name": "S", "version": "1.0"})
        (skill_dir / "SOUL.md").write_text("Be ethical.", encoding="utf-8")
        skill = load_manifest_skill(skill_dir)
        assert "ethical" in skill.soul_md

    def test_respects_manifest_allowed_agents(self, tmp_path):
        skill_dir = tmp_path / "agents_skill"
        self._write_manifest(
            skill_dir,
            {
                "id": "agents_skill",
                "name": "Agents",
                "version": "1.0",
                "allowed_agents": ["gsd", "monitor"],
            },
        )
        skill = load_manifest_skill(skill_dir)
        assert "gsd" in skill.allowed_agents
        assert "monitor" in skill.allowed_agents

    def test_respects_enabled_flag(self, tmp_path):
        skill_dir = tmp_path / "disabled_skill"
        self._write_manifest(
            skill_dir,
            {
                "id": "disabled_skill",
                "name": "Disabled",
                "version": "1.0",
                "enabled": False,
            },
        )
        skill = load_manifest_skill(skill_dir)
        assert skill.enabled is False

    def test_respects_risk_level(self, tmp_path):
        skill_dir = tmp_path / "risky_skill"
        self._write_manifest(
            skill_dir,
            {
                "id": "risky_skill",
                "name": "Risky",
                "version": "1.0",
                "risk_level": "critical",
            },
        )
        skill = load_manifest_skill(skill_dir)
        assert skill.risk_level == "critical"

    def test_raises_on_missing_manifest(self, tmp_path):
        skill_dir = tmp_path / "no_manifest"
        skill_dir.mkdir()
        with pytest.raises(Exception):
            load_manifest_skill(skill_dir)

    def test_raises_on_invalid_json(self, tmp_path):
        skill_dir = tmp_path / "bad_json"
        skill_dir.mkdir()
        (skill_dir / "skill.json").write_text("not valid json", encoding="utf-8")
        with pytest.raises(Exception):
            load_manifest_skill(skill_dir)


# ---------------------------------------------------------------------------
# load_legacy_json_skill
# ---------------------------------------------------------------------------


class TestLoadLegacyJsonSkill:
    def _make_legacy(self, tmp_path: Path, stem: str, data: dict) -> Path:
        p = tmp_path / f"{stem}.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_loads_minimal_legacy(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "business_analysis",
            {
                "title": "Business Analysis",
                "domain": "Business strategy",
            },
        )
        skill = load_legacy_json_skill(p)
        assert skill.skill_id == "business_analysis"
        assert skill.source_type == "legacy_json"
        assert skill.version == "legacy"
        assert skill.enabled is True
        assert skill.allowed_agents == []
        assert skill.required_tools == []

    def test_uses_stem_as_id(self, tmp_path):
        p = self._make_legacy(tmp_path, "my_domain", {"title": "My Domain"})
        skill = load_legacy_json_skill(p)
        assert skill.skill_id == "my_domain"

    def test_uses_title_as_name(self, tmp_path):
        p = self._make_legacy(tmp_path, "x", {"title": "Special Title", "domain": "Testing"})
        skill = load_legacy_json_skill(p)
        assert skill.name == "Special Title"

    def test_falls_back_to_stem_when_no_title(self, tmp_path):
        p = self._make_legacy(tmp_path, "fallback_skill", {"domain": "Testing"})
        skill = load_legacy_json_skill(p)
        assert skill.name == "fallback_skill"

    def test_populates_skill_md_from_people_and_frameworks(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "expert_skill",
            {
                "title": "Expert Skill",
                "people": ["Alice", "Bob"],
                "frameworks": ["DDD", "CQRS"],
            },
        )
        skill = load_legacy_json_skill(p)
        assert "Alice" in skill.skill_md
        assert "DDD" in skill.skill_md

    def test_populates_tools_md_from_power_phrases(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "phrase_skill",
            {
                "title": "Phrase Skill",
                "power_phrases": ["Ship it.", "Done is better than perfect."],
            },
        )
        skill = load_legacy_json_skill(p)
        assert "Ship it." in skill.tools_md

    def test_populates_soul_md_from_context(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "soul_skill",
            {
                "title": "Soul Skill",
                "context": "Always be helpful.",
            },
        )
        skill = load_legacy_json_skill(p)
        assert "helpful" in skill.soul_md

    def test_handles_empty_lists(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "empty_skill",
            {
                "title": "Empty",
                "people": [],
                "frameworks": [],
                "concepts": [],
                "power_phrases": [],
            },
        )
        skill = load_legacy_json_skill(p)
        assert skill.skill_md  # at least the title line
        assert skill.tools_md == ""

    def test_concepts_included_in_skill_md(self, tmp_path):
        p = self._make_legacy(
            tmp_path,
            "concepts_skill",
            {
                "title": "Concepts",
                "concepts": ["event sourcing", "CQRS"],
            },
        )
        skill = load_legacy_json_skill(p)
        assert "event sourcing" in skill.skill_md

    def test_raises_on_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        with pytest.raises(Exception):
            load_legacy_json_skill(p)
