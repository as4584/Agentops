from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    description: str = Field(default="")
    allowed_agents: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high", "critical"] = "medium"
    enabled: bool = True


class LoadedSkill(BaseModel):
    skill_id: str
    name: str
    version: str
    description: str
    allowed_agents: list[str]
    required_tools: list[str]
    risk_level: str
    enabled: bool
    source_path: str
    source_type: Literal["manifest", "legacy_json"]
    valid: bool = True
    invalid_reason: str | None = None
    skill_md: str = ""
    tools_md: str = ""
    soul_md: str = ""

    def to_prompt_section(self) -> str:
        blocks: list[str] = [f"[Skill: {self.name}]", f"Description: {self.description}"]
        if self.skill_md.strip():
            blocks.append(f"SKILL:\n{self.skill_md.strip()}")
        if self.tools_md.strip():
            blocks.append(f"TOOLS:\n{self.tools_md.strip()}")
        if self.soul_md.strip():
            blocks.append(f"SOUL:\n{self.soul_md.strip()}")
        return "\n\n".join(blocks)


def _read_json(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("JSON root must be an object")
    return result


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def load_manifest_skill(skill_dir: Path) -> LoadedSkill:
    manifest_path = skill_dir / "skill.json"
    manifest_data = _read_json(manifest_path)
    manifest = SkillManifest.model_validate(manifest_data)

    return LoadedSkill(
        skill_id=manifest.id,
        name=manifest.name,
        version=manifest.version,
        description=manifest.description,
        allowed_agents=manifest.allowed_agents,
        required_tools=manifest.required_tools,
        risk_level=manifest.risk_level,
        enabled=manifest.enabled,
        source_path=str(skill_dir),
        source_type="manifest",
        skill_md=_read_text_if_exists(skill_dir / "SKILL.md"),
        tools_md=_read_text_if_exists(skill_dir / "TOOLS.md"),
        soul_md=_read_text_if_exists(skill_dir / "SOUL.md"),
    )


def _legacy_prompt_fields(payload: dict[str, Any]) -> tuple[str, str, str]:
    title = str(payload.get("title") or "Legacy Skill")
    context = str(payload.get("context") or "")

    people = payload.get("people")
    phrases = payload.get("power_phrases")
    frameworks = payload.get("frameworks")
    concepts = payload.get("concepts")

    def _csv(value: Any, limit: int) -> str:
        if not isinstance(value, list):
            return ""
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return ", ".join(cleaned[:limit])

    skill_lines: list[str] = [f"Legacy title: {title}"]
    people_csv = _csv(people, 24)
    phrases_csv = _csv(phrases, 30)
    frameworks_csv = _csv(frameworks, 20)
    concepts_csv = _csv(concepts, 24)

    if people_csv:
        skill_lines.append(f"Key people: {people_csv}")
    if frameworks_csv:
        skill_lines.append(f"Frameworks: {frameworks_csv}")
    if concepts_csv:
        skill_lines.append(f"Concepts: {concepts_csv}")

    tools_lines: list[str] = []
    if phrases_csv:
        tools_lines.append(f"Power phrases: {phrases_csv}")

    return "\n".join(skill_lines), "\n".join(tools_lines), context


def load_legacy_json_skill(path: Path) -> LoadedSkill:
    payload = _read_json(path)
    skill_id = path.stem
    title = str(payload.get("title") or skill_id)
    skill_md, tools_md, soul_md = _legacy_prompt_fields(payload)

    return LoadedSkill(
        skill_id=skill_id,
        name=title,
        version="legacy",
        description=str(payload.get("domain") or "Legacy JSON skill"),
        allowed_agents=[],
        required_tools=[],
        risk_level="medium",
        enabled=True,
        source_path=str(path),
        source_type="legacy_json",
        skill_md=skill_md,
        tools_md=tools_md,
        soul_md=soul_md,
    )
