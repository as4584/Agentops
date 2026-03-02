"""
Skills — Domain knowledge injection for agents.
================================================
Skills are structured JSON knowledge packs that get injected into
agent system prompts, giving agents domain expertise from external
sources (ordostudio, BSEAI curriculum, etc.).

Each skill file contains people, power_phrases, frameworks, concepts,
and context that get compressed into an injectable prompt section.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.utils import logger

SKILLS_DIR = Path(__file__).parent / "data"


class SkillDefinition:
    """A loaded skill with structured domain knowledge."""

    def __init__(self, skill_id: str, data: dict[str, Any]) -> None:
        self.skill_id = skill_id
        self.title: str = data.get("title", skill_id)
        self.domain: str = data.get("domain", "general")
        self.people: list[str] = data.get("people", [])
        self.power_phrases: list[str] = data.get("power_phrases", [])
        self.frameworks: list[str] = data.get("frameworks", [])
        self.concepts: list[str] = data.get("concepts", [])
        self.context: str = data.get("context", "")

    def to_prompt_section(self) -> str:
        """Format this skill as an injectable prompt section."""
        lines = [f"[Skill: {self.title}]"]
        if self.people:
            lines.append(f"Key People: {', '.join(self.people)}")
        if self.power_phrases:
            phrases = self.power_phrases[:20]
            lines.append(f"Power Phrases: {', '.join(phrases)}")
        if self.frameworks:
            lines.append(f"Frameworks: {', '.join(self.frameworks[:12])}")
        if self.concepts:
            lines.append(f"Core Concepts: {', '.join(self.concepts[:15])}")
        if self.context:
            lines.append(f"Domain Context: {self.context}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Skill Cache & Loader
# ---------------------------------------------------------------------------

_skill_cache: dict[str, SkillDefinition] = {}


def load_skill(skill_id: str) -> SkillDefinition | None:
    """Load a single skill from its JSON file."""
    if skill_id in _skill_cache:
        return _skill_cache[skill_id]

    path = SKILLS_DIR / f"{skill_id}.json"
    if not path.exists():
        logger.warning(f"Skill file not found: {path}")
        return None

    try:
        with open(path) as f:
            data = json.load(f)
        skill = SkillDefinition(skill_id, data)
        _skill_cache[skill_id] = skill
        logger.info(f"Loaded skill: {skill_id} ({skill.title})")
        return skill
    except Exception as e:
        logger.error(f"Failed to load skill {skill_id}: {e}")
        return None


def load_skills(skill_ids: list[str]) -> list[SkillDefinition]:
    """Load multiple skills, silently skipping missing ones."""
    return [s for sid in skill_ids if (s := load_skill(sid)) is not None]


def build_skills_prompt(skill_ids: list[str]) -> str:
    """Build a combined prompt section from multiple skills for injection."""
    skills = load_skills(skill_ids)
    if not skills:
        return ""
    sections = [s.to_prompt_section() for s in skills]
    return (
        "\n\n[DOMAIN KNOWLEDGE — Use this expertise to inform your responses]\n"
        + "\n\n".join(sections)
        + "\n[/DOMAIN KNOWLEDGE]"
    )


def get_all_skill_ids() -> list[str]:
    """Return all available skill IDs from the data directory."""
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.stem for p in SKILLS_DIR.glob("*.json"))


def get_skill_summary() -> list[dict[str, str]]:
    """Return summaries of all available skills for the API."""
    summaries = []
    for sid in get_all_skill_ids():
        skill = load_skill(sid)
        if skill:
            summaries.append({
                "skill_id": sid,
                "title": skill.title,
                "domain": skill.domain,
                "people_count": len(skill.people),
                "phrases_count": len(skill.power_phrases),
            })
    return summaries
