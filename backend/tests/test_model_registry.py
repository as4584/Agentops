from __future__ import annotations

import json
import threading
from pathlib import Path

from backend.ml.model_registry import ChampionRegistry


def _registry(tmp_path: Path, default_model: str = "lex-v3") -> ChampionRegistry:
    return ChampionRegistry(
        registry_path=tmp_path / "data" / "models" / "registry.json",
        default_model=default_model,
    )


def test_promote_writes_registry_json(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    current = registry.promote("lex-v4", job_id="job-1", eval_score=0.91)
    payload = json.loads((tmp_path / "data" / "models" / "registry.json").read_text(encoding="utf-8"))

    assert current["model"] == "lex-v4"
    assert payload["active"] == "lex-v4"
    assert payload["history"] == [
        {
            "model": "lex-v4",
            "score": 0.91,
            "promoted_at": current["promoted_at"],
            "job_id": "job-1",
        }
    ]


def test_rollback_restores_previous_champion(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    first = registry.promote("lex-v4", job_id="job-1", eval_score=0.82)
    registry.promote("lex-v5", job_id="job-2", eval_score=0.94)

    rolled_back = registry.rollback()

    assert rolled_back["model"] == "lex-v4"
    assert rolled_back["score"] == 0.82
    assert rolled_back["promoted_at"] == first["promoted_at"]


def test_concurrent_promote_is_threadsafe(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    barrier = threading.Barrier(8)

    def promote(i: int) -> None:
        barrier.wait()
        registry.promote(f"lex-v{i}", job_id=f"job-{i}", eval_score=0.5 + i / 100)

    threads = [threading.Thread(target=promote, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    payload = json.loads((tmp_path / "data" / "models" / "registry.json").read_text(encoding="utf-8"))

    assert payload["active"].startswith("lex-v")
    assert len(payload["history"]) == 8
    assert {entry["job_id"] for entry in payload["history"]} == {f"job-{i}" for i in range(8)}


def test_propose_does_not_change_active(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.promote("lex-v4", job_id="job-1", eval_score=0.88)

    proposed = registry.propose_challenger("lex-v5", job_id="job-2", eval_score=0.9)
    current = registry.current()

    assert proposed["model"] == "lex-v5"
    assert current["model"] == "lex-v4"
    assert current["score"] == 0.88


def test_registry_missing_file_returns_default(tmp_path: Path) -> None:
    registry = _registry(tmp_path, default_model="lex-v3")

    assert registry.current() == {
        "model": "lex-v3",
        "score": None,
        "promoted_at": None,
    }
