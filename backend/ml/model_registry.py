from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT

DEFAULT_MODEL_REGISTRY_PATH = PROJECT_ROOT / "data" / "models" / "registry.json"


class ChampionRegistry:
    def __init__(
        self,
        registry_path: Path | None = None,
        default_model: str | None = None,
    ) -> None:
        self._registry_path = registry_path or DEFAULT_MODEL_REGISTRY_PATH
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._default_model = default_model or os.getenv("LEX_ROUTER_MODEL", "lex-v3")
        self._lock = threading.Lock()

    def propose_challenger(self, model_name: str, job_id: str, eval_score: float) -> dict[str, Any]:
        entry = self._entry(model_name=model_name, job_id=job_id, eval_score=eval_score)
        with self._lock:
            payload = self._read_payload()
            payload["history"].append(entry)
            self._write_payload(payload)
        return entry

    def promote(self, model_name: str, job_id: str, eval_score: float) -> dict[str, Any]:
        entry = self._entry(model_name=model_name, job_id=job_id, eval_score=eval_score)
        with self._lock:
            payload = self._read_payload()
            payload["active"] = model_name
            payload["history"].append(entry)
            self._write_payload(payload)
        return self.current()

    def rollback(self) -> dict[str, Any]:
        with self._lock:
            payload = self._read_payload()
            active = payload.get("active") or self._default_model
            history = payload.get("history", [])
            current_index = None
            for index in range(len(history) - 1, -1, -1):
                if history[index].get("model") == active:
                    current_index = index
                    break

            previous_model = self._default_model
            if current_index is not None:
                for index in range(current_index - 1, -1, -1):
                    candidate = history[index].get("model")
                    if candidate:
                        previous_model = str(candidate)
                        break

            payload["active"] = previous_model
            self._write_payload(payload)
        return self.current()

    def current(self) -> dict[str, Any]:
        payload = self._read_payload()
        active = str(payload.get("active") or self._default_model)
        for entry in reversed(payload.get("history", [])):
            if entry.get("model") == active:
                return {
                    "model": active,
                    "score": self._coerce_score(entry.get("score")),
                    "promoted_at": self._coerce_timestamp(entry.get("promoted_at")),
                }
        return {"model": active, "score": None, "promoted_at": None}

    def _entry(self, *, model_name: str, job_id: str, eval_score: float) -> dict[str, Any]:
        return {
            "model": model_name,
            "score": float(eval_score),
            "promoted_at": datetime.now(UTC).isoformat(),
            "job_id": job_id,
        }

    def _read_payload(self) -> dict[str, Any]:
        if not self._registry_path.exists():
            return {"active": self._default_model, "history": []}

        try:
            payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"active": self._default_model, "history": []}

        active = payload.get("active") or self._default_model
        history = payload.get("history")
        if not isinstance(history, list):
            history = []
        return {"active": active, "history": history}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        temp_path = self._registry_path.with_suffix(f"{self._registry_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self._registry_path)

    @staticmethod
    def _coerce_score(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_timestamp(value: Any) -> str | None:
        return value if isinstance(value, str) else None
