from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from backend.config import OLLAMA_MODEL, PROJECT_ROOT

UTC_TZ = timezone.utc  # noqa: UP017

MODEL_OVERRIDES_PATH = PROJECT_ROOT / "data" / "agents" / "model_overrides.json"
MODEL_PREFERENCES_PATH = PROJECT_ROOT / "data" / "agents" / "model_preferences.json"

EDITABLE_TEAM_AGENT_MAP: dict[str, tuple[str, ...]] = {
    "orchad": ("soul_core",),
    "dev": ("code_review_agent", "devops_agent", "coding_agent"),
    "social": ("comms_agent", "cs_agent"),
}

READ_ONLY_TEAM_AGENT_MAP: dict[str, tuple[str, ...]] = {
    "ops": (
        "monitor_agent",
        "self_healer_agent",
        "security_agent",
        "data_agent",
        "it_agent",
        "ocr_agent",
        "knowledge_agent",
    ),
}

TEAM_DEFAULT_MODELS: dict[str, str] = {
    "orchad": "qwen2.5-coder:7b",
    "dev": "mistral:7b",
    "social": "llama3.2",
}

TEAM_LABELS: dict[str, str] = {
    "orchad": "Orchad",
    "dev": "Dev Team",
    "social": "Social & Support",
    "ops": "Ops & Intelligence",
}

TEAM_HELP_TEXT: dict[str, str] = {
    "orchad": "Applies to soul_core",
    "dev": "Applies to 3 agents",
    "social": "Applies to comms + support",
    "ops": "Read-only in this pass",
}

AGENT_TEAM_MAP: dict[str, str] = {
    agent_id: team_id
    for team_id, agent_ids in {**EDITABLE_TEAM_AGENT_MAP, **READ_ONLY_TEAM_AGENT_MAP}.items()
    for agent_id in agent_ids
}


def _load_json(path) -> dict[str, Any]:
    try:
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


def _save_json(path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def load_agent_model_overrides() -> dict[str, str]:
    raw = _load_json(MODEL_OVERRIDES_PATH)
    return {
        str(agent_id): str(model_id).strip()
        for agent_id, model_id in raw.items()
        if str(agent_id).strip() and str(model_id).strip()
    }


def save_agent_model_overrides(overrides: dict[str, str]) -> None:
    _save_json(MODEL_OVERRIDES_PATH, overrides)


def _seed_team_preferences(
    raw_team_models: dict[str, Any],
    agent_overrides: dict[str, str],
) -> tuple[dict[str, str], bool]:
    team_models = {
        str(team_id): str(model_id).strip()
        for team_id, model_id in raw_team_models.items()
        if str(team_id).strip() and str(model_id).strip()
    }
    changed = False

    if not team_models.get("orchad"):
        team_models["orchad"] = agent_overrides.get("soul_core") or TEAM_DEFAULT_MODELS["orchad"]
        changed = True
    if not team_models.get("social"):
        team_models["social"] = agent_overrides.get("comms_agent") or TEAM_DEFAULT_MODELS["social"]
        changed = True
    if not team_models.get("dev"):
        team_models["dev"] = TEAM_DEFAULT_MODELS["dev"]
        changed = True

    return team_models, changed


def load_team_model_preferences(agent_overrides: dict[str, str]) -> dict[str, str]:
    payload = _load_json(MODEL_PREFERENCES_PATH)
    raw_team_models = payload.get("team_models", payload)
    if not isinstance(raw_team_models, dict):
        raw_team_models = {}
    team_models, changed = _seed_team_preferences(raw_team_models, agent_overrides)
    if changed or payload.get("team_models") != team_models:
        save_team_model_preferences(team_models)
    return team_models


def save_team_model_preferences(team_models: dict[str, str]) -> None:
    _save_json(
        MODEL_PREFERENCES_PATH,
        {
            "team_models": team_models,
            "updated_at": datetime.now(UTC_TZ).isoformat(),
        },
    )


def get_team_id_for_agent(agent_id: str) -> str | None:
    return AGENT_TEAM_MAP.get(agent_id)


def resolve_model_selection(
    agent_id: str,
    request_model: str | None,
    team_models: dict[str, str],
    agent_overrides: dict[str, str],
    fallback_model: str | None = None,
) -> dict[str, Any]:
    team_id = get_team_id_for_agent(agent_id)
    fallback = (
        TEAM_DEFAULT_MODELS.get(team_id or "")
        or agent_overrides.get(agent_id)
        or fallback_model
        or OLLAMA_MODEL
    )

    if request_model:
        selected_model = str(request_model).strip()
        model_source = "request"
    elif team_id in EDITABLE_TEAM_AGENT_MAP and team_models.get(team_id or ""):
        selected_model = str(team_models[team_id]).strip()
        model_source = "team_default"
    elif agent_overrides.get(agent_id):
        selected_model = str(agent_overrides[agent_id]).strip()
        model_source = "agent_override"
    else:
        selected_model = fallback
        model_source = "fallback"

    return {
        "team_id": team_id,
        "selected_model": selected_model,
        "requested_model": selected_model,
        "model_source": model_source,
    }


def build_model_preferences_response(
    team_models: dict[str, str],
    agent_overrides: dict[str, str],
    fallback_model: str | None = None,
) -> dict[str, Any]:
    teams: dict[str, Any] = {}
    ordered_team_ids = ("orchad", "dev", "social", "ops")

    for team_id in ordered_team_ids:
        agent_ids = EDITABLE_TEAM_AGENT_MAP.get(team_id) or READ_ONLY_TEAM_AGENT_MAP.get(team_id, ())
        read_only = team_id not in EDITABLE_TEAM_AGENT_MAP
        selected_model = team_models.get(team_id) if not read_only else None
        resolved_agent_models = {
            agent_id: resolve_model_selection(
                agent_id=agent_id,
                request_model=None,
                team_models=team_models,
                agent_overrides=agent_overrides,
                fallback_model=fallback_model,
            )["selected_model"]
            for agent_id in agent_ids
        }
        teams[team_id] = {
            "team_id": team_id,
            "label": TEAM_LABELS.get(team_id, team_id.title()),
            "selected_model": selected_model,
            "default_model": TEAM_DEFAULT_MODELS.get(team_id),
            "agent_ids": list(agent_ids),
            "resolved_agent_models": resolved_agent_models,
            "read_only": read_only,
            "help_text": TEAM_HELP_TEXT.get(team_id, ""),
        }

    return {
        "teams": teams,
        "agent_overrides": agent_overrides,
    }

