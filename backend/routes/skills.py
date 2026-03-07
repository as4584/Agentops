from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.skills import get_skill_registry

router = APIRouter(prefix="/skills", tags=["skills"])


class SkillToggleRequest(BaseModel):
    enabled: bool


@router.get("")
async def list_skills() -> list[dict[str, Any]]:
    return get_skill_registry().list_skills()


@router.get("/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, Any]:
    skill = get_skill_registry().get_skill(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {
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
        "skill_md": skill.skill_md,
        "tools_md": skill.tools_md,
        "soul_md": skill.soul_md,
    }


@router.patch("/{skill_id}")
async def toggle_skill(skill_id: str, payload: SkillToggleRequest) -> dict[str, Any]:
    registry = get_skill_registry()
    try:
        updated = registry.set_enabled(skill_id=skill_id, enabled=payload.enabled)
    except KeyError:
        raise HTTPException(status_code=404, detail="Skill not found")

    return {
        "skill_id": updated.skill_id,
        "enabled": updated.enabled,
        "valid": updated.valid,
        "invalid_reason": updated.invalid_reason,
    }


@router.post("/reload")
async def reload_skills() -> dict[str, Any]:
    return get_skill_registry().reload()
