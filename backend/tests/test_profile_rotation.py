from __future__ import annotations

import sys
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _clear_profile_env(monkeypatch: MonkeyPatch) -> None:
    keys = [
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "LLM_PROFILE_MONTHLY_BUDGET_USD",
    ]
    for base in ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
        for idx in range(1, 10):
            keys.append(f"{base}_{idx}")

    for key in keys:
        monkeypatch.delenv(key, raising=False)


def test_single_key_backward_compatibility(monkeypatch: MonkeyPatch, tmp_path: Path):
    from backend.llm.profiles import ProfileRotator

    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY", "single-key")

    rotator = ProfileRotator(storage_path=tmp_path / "profiles.json")
    rotator.load_from_env()

    profiles = rotator.get_profiles("openrouter")
    assert len(profiles) == 1
    assert profiles[0].profile_id == "openrouter-1"
    assert profiles[0].api_key == "single-key"


def test_round_robin_across_three_profiles(monkeypatch: MonkeyPatch, tmp_path: Path):
    from backend.llm.profiles import ProfileRotator

    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "key-1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key-2")
    monkeypatch.setenv("OPENROUTER_API_KEY_3", "key-3")

    rotator = ProfileRotator(storage_path=tmp_path / "profiles.json")
    rotator.load_from_env()

    seq = [
        rotator.get_profile("openrouter").profile_id,
        rotator.get_profile("openrouter").profile_id,
        rotator.get_profile("openrouter").profile_id,
        rotator.get_profile("openrouter").profile_id,
    ]

    assert seq == ["openrouter-1", "openrouter-2", "openrouter-3", "openrouter-1"]


def test_over_budget_profile_deactivated_and_skipped(monkeypatch: MonkeyPatch, tmp_path: Path):
    from backend.llm.profiles import ProfileRotator

    _clear_profile_env(monkeypatch)
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "key-1")
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "key-2")
    monkeypatch.setenv("OPENROUTER_API_KEY_3", "key-3")
    monkeypatch.setenv("LLM_PROFILE_MONTHLY_BUDGET_USD", "10")

    rotator = ProfileRotator(storage_path=tmp_path / "profiles.json")
    rotator.load_from_env()

    rotator.record_spend("openrouter-2", 11.0)

    active_ids = [profile.profile_id for profile in rotator.get_active_profiles("openrouter")]
    assert "openrouter-2" not in active_ids
    assert len(active_ids) == 2

    picks = [
        rotator.get_profile("openrouter").profile_id,
        rotator.get_profile("openrouter").profile_id,
        rotator.get_profile("openrouter").profile_id,
    ]
    assert picks == ["openrouter-1", "openrouter-3", "openrouter-1"]
