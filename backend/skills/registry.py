from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.config import BACKEND_DIR
from backend.tools import get_tool_definitions
from backend.utils import logger

from .loader import LoadedSkill, load_legacy_json_skill, load_manifest_skill


SKILLS_ROOT = Path(__file__).resolve().parent
LEGACY_SKILLS_DIR = SKILLS_ROOT / "data"
SKILLS_STATE_PATH = BACKEND_DIR / "memory" / "skills_state.json"


class SkillRegistry:
    def __init__(
        self,
        skills_root: Path = SKILLS_ROOT,
        legacy_skills_dir: Path = LEGACY_SKILLS_DIR,
        state_path: Path = SKILLS_STATE_PATH,
    ) -> None:
        self.skills_root = skills_root
        self.legacy_skills_dir = legacy_skills_dir
        self.state_path = state_path
        self._skills: dict[str, LoadedSkill] = {}
        self._invalid: dict[str, str] = {}
        self.reload()

    def _known_tools(self) -> set[str]:
        return {tool.name for tool in get_tool_definitions()}

    def _read_state(self) -> dict[str, bool]:
        if not self.state_path.exists():
            return {}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw, dict):
            return {}
        skills = raw.get("skills")
        if not isinstance(skills, dict):
            return {}

        state: dict[str, bool] = {}
        for skill_id, payload in skills.items():
            if not isinstance(skill_id, str) or not isinstance(payload, dict):
                continue
            enabled = payload.get("enabled")
            if isinstance(enabled, bool):
                state[skill_id] = enabled
        return state

    def _write_state(self, state: dict[str, bool]) -> None:
        payload = {
            "skills": {
                skill_id: {"enabled": enabled}
                for skill_id, enabled in sorted(state.items())
            }
        }
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _apply_state_overrides(self, skills: dict[str, LoadedSkill]) -> None:
        state = self._read_state()
        for skill_id, enabled in state.items():
            if skill_id in skills:
                skills[skill_id].enabled = enabled

    def _load_manifest_skills(self) -> list[LoadedSkill]:
        skills: list[LoadedSkill] = []
        if not self.skills_root.exists():
            return skills

        dirs = [
            path for path in self.skills_root.iterdir()
            if path.is_dir() and path.name not in {"__pycache__", "data"}
        ]
        for skill_dir in sorted(dirs, key=lambda item: item.name.lower()):
            manifest_path = skill_dir / "skill.json"
            if not manifest_path.exists():
                continue
            try:
                skills.append(load_manifest_skill(skill_dir))
            except Exception as exc:
                self._invalid[skill_dir.name] = f"manifest_error: {exc}"
        return skills

    def _load_legacy_skills(self) -> list[LoadedSkill]:
        skills: list[LoadedSkill] = []
        if not self.legacy_skills_dir.exists():
            return skills
        for json_path in sorted(self.legacy_skills_dir.glob("*.json"), key=lambda item: item.name.lower()):
            try:
                skills.append(load_legacy_json_skill(json_path))
            except Exception as exc:
                self._invalid[json_path.stem] = f"legacy_error: {exc}"
        return skills

    def reload(self) -> dict[str, Any]:
        self._invalid = {}
        staged: dict[str, LoadedSkill] = {}
        known_tools = self._known_tools()

        for loaded in self._load_manifest_skills() + self._load_legacy_skills():
            if loaded.skill_id in staged:
                self._invalid[loaded.skill_id] = "duplicate_skill_id"
                continue

            unknown_tools = [tool for tool in loaded.required_tools if tool not in known_tools]
            if unknown_tools:
                loaded.valid = False
                loaded.invalid_reason = f"unknown_required_tools: {', '.join(sorted(unknown_tools))}"
                self._invalid[loaded.skill_id] = loaded.invalid_reason

            staged[loaded.skill_id] = loaded

        self._apply_state_overrides(staged)
        self._skills = dict(sorted(staged.items(), key=lambda item: item[0]))

        logger.info(
            "Skills registry reloaded",
            event_type="skills_registry_reloaded",
            loaded_count=len(self._skills),
            invalid_count=len(self._invalid),
        )
        return {
            "loaded_count": len(self._skills),
            "invalid_count": len(self._invalid),
            "invalid": dict(self._invalid),
        }

    def list_skills(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for skill in self._skills.values():
            rows.append(
                {
                    "skill_id": skill.skill_id,
                    "name": skill.name,
                    "version": skill.version,
                    "description": skill.description,
                    "allowed_agents": list(skill.allowed_agents),
                    "required_tools": list(skill.required_tools),
                    "risk_level": skill.risk_level,
                    "enabled": skill.enabled,
                    "valid": skill.valid,
                    "invalid_reason": skill.invalid_reason,
                    "source_type": skill.source_type,
                    "source_path": skill.source_path,
                }
            )
        return rows

    def get_skill(self, skill_id: str) -> LoadedSkill | None:
        return self._skills.get(skill_id)

    def set_enabled(self, skill_id: str, enabled: bool) -> LoadedSkill:
        skill = self.get_skill(skill_id)
        if skill is None:
            raise KeyError(skill_id)

        skill.enabled = enabled
        current = self._read_state()
        current[skill_id] = enabled
        self._write_state(current)

        logger.info(
            "Skill enable state updated",
            event_type="skill_toggled",
            skill_id=skill_id,
            enabled=enabled,
        )
        return skill

    @staticmethod
    def _agent_allowed(skill: LoadedSkill, agent_id: str) -> bool:
        if not skill.allowed_agents:
            return True
        if "*" in skill.allowed_agents:
            return True
        return agent_id in skill.allowed_agents

    def build_prompt(self, skill_ids: list[str], agent_id: str) -> str:
        sections: list[str] = []
        for skill_id in skill_ids:
            skill = self._skills.get(skill_id)
            if skill is None:
                continue
            if not skill.valid:
                continue
            if not skill.enabled:
                continue
            if not self._agent_allowed(skill, agent_id):
                continue
            sections.append(skill.to_prompt_section())

        if not sections:
            return ""

        return (
            "\n\n[DOMAIN KNOWLEDGE — Use this expertise to inform your responses]\n"
            + "\n\n".join(sections)
            + "\n[/DOMAIN KNOWLEDGE]"
        )


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry
