"""
Tests for backend.skills public API — delegation functions over SkillRegistry.

Covers:
- reload_skills() delegates to registry.reload()
- build_skills_prompt() delegates to registry.build_prompt()
- get_all_skill_ids() extracts skill_id keys from registry.list_skills()
- get_skill_summary() returns the raw list from registry.list_skills()
- load_skill() delegates to registry.get_skill()
- load_skills() filters out None results silently
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_registry(**overrides) -> MagicMock:
    """Return a MagicMock that matches the SkillRegistry interface."""
    reg = MagicMock()
    reg.reload.return_value = {"loaded": 3, "errors": []}
    reg.build_prompt.return_value = "## Skills\n- skill_a"
    reg.list_skills.return_value = [
        {"skill_id": "skill_a", "name": "Skill A"},
        {"skill_id": "skill_b", "name": "Skill B"},
    ]
    reg.get_skill.return_value = MagicMock(skill_id="skill_a")
    for k, v in overrides.items():
        setattr(reg, k, v)
    return reg


# ---------------------------------------------------------------------------
# reload_skills
# ---------------------------------------------------------------------------


def test_reload_skills_calls_registry_reload() -> None:
    from backend.skills import reload_skills

    reg = _mock_registry()
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = reload_skills()

    reg.reload.assert_called_once()
    assert result == {"loaded": 3, "errors": []}


# ---------------------------------------------------------------------------
# build_skills_prompt
# ---------------------------------------------------------------------------


def test_build_skills_prompt_delegates_to_registry() -> None:
    from backend.skills import build_skills_prompt

    reg = _mock_registry()
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = build_skills_prompt(["skill_a"], "devops_agent")

    reg.build_prompt.assert_called_once_with(skill_ids=["skill_a"], agent_id="devops_agent")
    assert "Skills" in result


def test_build_skills_prompt_passes_empty_list() -> None:
    from backend.skills import build_skills_prompt

    reg = _mock_registry()
    reg.build_prompt.return_value = ""
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = build_skills_prompt([], "cs_agent")

    reg.build_prompt.assert_called_once_with(skill_ids=[], agent_id="cs_agent")
    assert result == ""


# ---------------------------------------------------------------------------
# get_all_skill_ids
# ---------------------------------------------------------------------------


def test_get_all_skill_ids_returns_ids() -> None:
    from backend.skills import get_all_skill_ids

    reg = _mock_registry()
    with patch("backend.skills.get_skill_registry", return_value=reg):
        ids = get_all_skill_ids()

    assert ids == ["skill_a", "skill_b"]


def test_get_all_skill_ids_empty_registry() -> None:
    from backend.skills import get_all_skill_ids

    reg = _mock_registry()
    reg.list_skills.return_value = []
    with patch("backend.skills.get_skill_registry", return_value=reg):
        ids = get_all_skill_ids()

    assert ids == []


# ---------------------------------------------------------------------------
# get_skill_summary
# ---------------------------------------------------------------------------


def test_get_skill_summary_returns_raw_list() -> None:
    from backend.skills import get_skill_summary

    rows = [{"skill_id": "x", "name": "X"}, {"skill_id": "y", "name": "Y"}]
    reg = _mock_registry()
    reg.list_skills.return_value = rows
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = get_skill_summary()

    assert result is rows


# ---------------------------------------------------------------------------
# load_skill
# ---------------------------------------------------------------------------


def test_load_skill_returns_skill_when_found() -> None:
    from backend.skills import load_skill

    mock_skill = MagicMock()
    mock_skill.skill_id = "skill_a"
    reg = _mock_registry()
    reg.get_skill.return_value = mock_skill
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skill("skill_a")

    reg.get_skill.assert_called_once_with("skill_a")
    assert result is mock_skill


def test_load_skill_returns_none_when_not_found() -> None:
    from backend.skills import load_skill

    reg = _mock_registry()
    reg.get_skill.return_value = None
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skill("nonexistent")

    assert result is None


# ---------------------------------------------------------------------------
# load_skills
# ---------------------------------------------------------------------------


def test_load_skills_returns_found_skills() -> None:
    from backend.skills import load_skills

    skill_a = MagicMock()
    skill_b = MagicMock()
    reg = _mock_registry()
    reg.get_skill.side_effect = lambda sid: {"skill_a": skill_a, "skill_b": skill_b}.get(sid)

    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skills(["skill_a", "skill_b"])

    assert result == [skill_a, skill_b]


def test_load_skills_silently_drops_missing() -> None:
    """load_skills must omit skill_ids for which get_skill returns None."""
    from backend.skills import load_skills

    skill_a = MagicMock()
    reg = _mock_registry()
    reg.get_skill.side_effect = lambda sid: skill_a if sid == "skill_a" else None

    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skills(["skill_a", "skill_missing"])

    assert len(result) == 1
    assert result[0] is skill_a


def test_load_skills_empty_input_returns_empty() -> None:
    from backend.skills import load_skills

    reg = _mock_registry()
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skills([])

    assert result == []
    reg.get_skill.assert_not_called()


def test_load_skills_all_missing_returns_empty() -> None:
    from backend.skills import load_skills

    reg = _mock_registry()
    reg.get_skill.return_value = None
    with patch("backend.skills.get_skill_registry", return_value=reg):
        result = load_skills(["a", "b", "c"])

    assert result == []
