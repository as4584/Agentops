"""Skills package public interface."""

from __future__ import annotations

from typing import Any

from .loader import LoadedSkill, SkillManifest
from .registry import SkillRegistry, get_skill_registry


def reload_skills() -> dict[str, Any]:
    return get_skill_registry().reload()


def build_skills_prompt(skill_ids: list[str], agent_id: str) -> str:
    return get_skill_registry().build_prompt(skill_ids=skill_ids, agent_id=agent_id)


def get_all_skill_ids() -> list[str]:
    return [row["skill_id"] for row in get_skill_registry().list_skills()]


def get_skill_summary() -> list[dict[str, Any]]:
    return get_skill_registry().list_skills()


def load_skill(skill_id: str) -> LoadedSkill | None:
    return get_skill_registry().get_skill(skill_id)


def load_skills(skill_ids: list[str]) -> list[LoadedSkill]:
    loaded: list[LoadedSkill] = []
    registry = get_skill_registry()
    for skill_id in skill_ids:
        skill = registry.get_skill(skill_id)
        if skill is not None:
            loaded.append(skill)
    return loaded


__all__ = [
    "LoadedSkill",
    "SkillManifest",
    "SkillRegistry",
    "build_skills_prompt",
    "get_all_skill_ids",
    "get_skill_registry",
    "get_skill_summary",
    "load_skill",
    "load_skills",
    "reload_skills",
]
