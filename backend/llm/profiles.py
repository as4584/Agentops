from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT


@dataclass
class CredentialProfile:
    profile_id: str
    provider: str
    api_key: str
    auth_type: str
    monthly_budget_usd: float = 10.0
    spend_this_month: float = 0.0
    last_reset_epoch: float = 0.0
    active: bool = True


class ProfileRotator:
    def __init__(self, storage_path: Path | None = None) -> None:
        self.storage_path = storage_path or (PROJECT_ROOT / "backend" / "memory" / "llm_profiles.json")
        self.profiles: list[CredentialProfile] = []
        self._round_robin_index: dict[str, int] = {}

    def load_from_env(self) -> None:
        loaded_profiles: list[CredentialProfile] = []
        loaded_profiles.extend(self._provider_profiles("openrouter", "OPENROUTER_API_KEY"))
        loaded_profiles.extend(self._provider_profiles("openai", "OPENAI_API_KEY"))
        loaded_profiles.extend(self._provider_profiles("anthropic", "ANTHROPIC_API_KEY"))

        self.profiles = loaded_profiles
        self._apply_persisted_state()
        self.deactivate_over_budget()

    def _provider_profiles(self, provider: str, base_var: str) -> list[CredentialProfile]:
        keys: list[str] = []

        bare = os.getenv(base_var, "").strip()
        if bare:
            keys.append(bare)

        for idx in range(1, 10):
            value = os.getenv(f"{base_var}_{idx}", "").strip()
            if value:
                keys.append(value)

        monthly_budget = float(os.getenv("LLM_PROFILE_MONTHLY_BUDGET_USD", "10.0"))
        now_epoch = datetime.now(timezone.utc).timestamp()

        profiles: list[CredentialProfile] = []
        for idx, key in enumerate(keys, start=1):
            profiles.append(
                CredentialProfile(
                    profile_id=f"{provider}-{idx}",
                    provider=provider,
                    api_key=key,
                    auth_type="api_key",
                    monthly_budget_usd=monthly_budget,
                    spend_this_month=0.0,
                    last_reset_epoch=now_epoch,
                    active=True,
                )
            )
        return profiles

    def _current_month_token(self) -> tuple[int, int]:
        now = datetime.now(timezone.utc)
        return now.year, now.month

    def _month_token_from_epoch(self, epoch_seconds: float) -> tuple[int, int]:
        dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
        return dt.year, dt.month

    def _ensure_month_reset(self, profile: CredentialProfile) -> None:
        if profile.last_reset_epoch <= 0:
            profile.last_reset_epoch = datetime.now(timezone.utc).timestamp()
            return

        if self._month_token_from_epoch(profile.last_reset_epoch) != self._current_month_token():
            profile.spend_this_month = 0.0
            profile.last_reset_epoch = datetime.now(timezone.utc).timestamp()
            profile.active = True

    def _apply_persisted_state(self) -> None:
        if not self.storage_path.exists():
            return

        try:
            raw: dict[str, Any] = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return

        persisted_profiles: list[Any] = list(raw.get("profiles", []))
        by_id: dict[str, dict[str, Any]] = {}
        for _item in persisted_profiles:
            item: dict[str, Any] = _item if isinstance(_item, dict) else {}
            if item and isinstance(item.get("profile_id"), str):
                profile_id: str = str(item["profile_id"])
                by_id[profile_id] = item

        for profile in self.profiles:
            saved = by_id.get(profile.profile_id)
            if not saved:
                continue

            if isinstance(saved.get("spend_this_month"), (int, float)):
                profile.spend_this_month = float(saved["spend_this_month"])
            if isinstance(saved.get("monthly_budget_usd"), (int, float)):
                profile.monthly_budget_usd = float(saved["monthly_budget_usd"])
            if isinstance(saved.get("last_reset_epoch"), (int, float)):
                profile.last_reset_epoch = float(saved["last_reset_epoch"])
            if isinstance(saved.get("active"), bool):
                profile.active = saved["active"]

            self._ensure_month_reset(profile)

    def save_state(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profiles": [asdict(profile) for profile in self.profiles],
        }
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def get_profiles(self, provider: str) -> list[CredentialProfile]:
        return [profile for profile in self.profiles if profile.provider == provider]

    def get_active_profiles(self, provider: str) -> list[CredentialProfile]:
        active_profiles: list[CredentialProfile] = []
        for profile in self.get_profiles(provider):
            self._ensure_month_reset(profile)
            if profile.active and profile.api_key:
                active_profiles.append(profile)
        return active_profiles

    def get_profile(self, provider: str) -> CredentialProfile:
        active_profiles = self.get_active_profiles(provider)
        if not active_profiles:
            raise ValueError(f"No active credential profiles for provider '{provider}'")

        idx = self._round_robin_index.get(provider, 0)
        selected = active_profiles[idx % len(active_profiles)]
        self._round_robin_index[provider] = (idx + 1) % len(active_profiles)
        return selected

    def get_key(self, provider: str) -> str:
        return self.get_profile(provider).api_key

    def record_spend(self, profile_id: str, usd: float) -> None:
        if usd <= 0:
            return

        target: CredentialProfile | None = None
        for profile in self.profiles:
            if profile.profile_id == profile_id:
                target = profile
                break

        if target is None:
            return

        self._ensure_month_reset(target)
        target.spend_this_month = round(target.spend_this_month + usd, 6)
        self.deactivate_over_budget()
        self.save_state()

    def deactivate_over_budget(self) -> None:
        for profile in self.profiles:
            self._ensure_month_reset(profile)
            if profile.monthly_budget_usd > 0 and profile.spend_this_month >= profile.monthly_budget_usd:
                profile.active = False
