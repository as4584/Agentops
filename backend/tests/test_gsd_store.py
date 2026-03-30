"""
Tests for GSDStore — backend/database/gsd_store.py
"""
from __future__ import annotations

import json
import tempfile
from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.database.gsd_store import GSDStore, _atomic_write
from backend.models.gsd import (
    GSDMapResult,
    GSDPlan,
    GSDStateFile,
    GSDTask,
    GSDVerifyReport,
    PhaseStatus,
    TaskStatus,
    VerifyCheckItem,
)


@pytest.fixture()
def tmp_store(tmp_path: Path) -> Generator[GSDStore, None, None]:
    """A GSDStore with all paths redirected to a temp directory."""
    store = GSDStore()
    # Patch all path constants to use tmp_path
    import backend.database.gsd_store as mod

    with (
        patch.object(mod, "_GSD_ROOT", tmp_path / "gsd"),
        patch.object(mod, "_STATE_PATH", tmp_path / "gsd" / "gsd_state.json"),
        patch.object(mod, "_MAP_PATH", tmp_path / "gsd" / "map_docs.json"),
        patch.object(mod, "_PHASES_ROOT", tmp_path / "gsd" / "phases"),
    ):
        yield GSDStore()


# ---------------------------------------------------------------------------
# _atomic_write
# ---------------------------------------------------------------------------

def test_atomic_write_creates_file(tmp_path: Path):
    target = tmp_path / "output.json"
    _atomic_write(target, '{"ok": true}')
    assert target.exists()
    assert json.loads(target.read_text())["ok"] is True


def test_atomic_write_no_tmp_leftover(tmp_path: Path):
    target = tmp_path / "output.json"
    _atomic_write(target, '{"v": 1}')
    tmp = target.with_suffix(".json.tmp")
    assert not tmp.exists(), "Temp file should have been renamed away"


def test_atomic_write_overwrites(tmp_path: Path):
    target = tmp_path / "data.json"
    _atomic_write(target, "first")
    _atomic_write(target, "second")
    assert target.read_text() == "second"


def test_atomic_write_creates_parents(tmp_path: Path):
    target = tmp_path / "deep" / "nested" / "file.json"
    _atomic_write(target, "data")
    assert target.exists()


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def test_save_and_load_state(tmp_path: Path):
    import backend.database.gsd_store as mod
    with (
        patch.object(mod, "_STATE_PATH", tmp_path / "gsd_state.json"),
        patch.object(mod, "_GSD_ROOT", tmp_path),
    ):
        store = GSDStore()
        state = GSDStateFile(active_phase=3, completed_phases=[1, 2])
        store.save_state(state)
        loaded = store.load_state()
    assert loaded.active_phase == 3
    assert loaded.completed_phases == [1, 2]


def test_load_state_missing_returns_default(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_STATE_PATH", tmp_path / "nonexistent.json"):
        store = GSDStore()
        state = store.load_state()
    assert state.active_phase is None
    assert state.completed_phases == []


def test_save_state_updates_last_updated(tmp_path: Path):
    import backend.database.gsd_store as mod
    before = datetime.now(timezone.utc)
    with (
        patch.object(mod, "_STATE_PATH", tmp_path / "gsd_state.json"),
        patch.object(mod, "_GSD_ROOT", tmp_path),
    ):
        store = GSDStore()
        state = GSDStateFile()
        store.save_state(state)
        loaded = store.load_state()
    assert loaded.last_updated >= before


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def _make_plan(phase: int = 1) -> GSDPlan:
    return GSDPlan(
        phase=phase,
        title=f"Test Phase {phase}",
        description="A test plan",
        tasks=[
            GSDTask(id="T1", description="Do something", file_targets=["backend/foo.py"], wave=1),
            GSDTask(id="T2", description="Test something", file_targets=["backend/tests/test_foo.py"], wave=1),
        ],
    )


def test_save_and_load_plan(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        plan = _make_plan(1)
        store.save_plan(1, plan)
        loaded = store.load_plan(1)
    assert loaded is not None
    assert loaded.phase == 1
    assert loaded.title == "Test Phase 1"
    assert len(loaded.tasks) == 2


def test_save_plan_writes_markdown(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        store.save_plan(1, _make_plan(1))
        md_path = tmp_path / "phases" / "1" / "PLAN.md"
    assert md_path.exists()
    content = md_path.read_text()
    assert "Phase 1" in content


def test_load_plan_missing_returns_none(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        assert store.load_plan(99) is None


def test_list_phases(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        for n in (3, 1, 2):
            store.save_plan(n, _make_plan(n))
        phases = store.list_phases()
    assert phases == [1, 2, 3]


# ---------------------------------------------------------------------------
# Execution log
# ---------------------------------------------------------------------------

def test_append_and_read_execution_log(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        store.append_execution_log(1, "## Wave 1")
        store.append_execution_log(1, "#### T1 done")
        log = store.read_execution_log(1)
    assert "Wave 1" in log
    assert "T1 done" in log


def test_read_execution_log_missing_returns_empty(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        assert store.read_execution_log(42) == ""


# ---------------------------------------------------------------------------
# Map docs
# ---------------------------------------------------------------------------

def test_save_and_load_map_docs(tmp_path: Path):
    import backend.database.gsd_store as mod

    map_json = tmp_path / "map_docs.json"

    result = GSDMapResult(
        stack="Python 3.11",
        architecture="FastAPI + LangGraph",
        conventions="atomic writes",
        concerns="CMD-001 open",
    )

    # Redirect every _atomic_write call so nothing touches the real workspace.
    def aw_side(path: Path, data: str) -> None:
        # Everything (map JSON + individual docs) lands in tmp_path
        target = tmp_path / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = target.with_suffix(target.suffix + ".tmp")
        tmp_file.write_text(data, encoding="utf-8")
        tmp_file.rename(target)

    with (
        patch.object(mod, "_MAP_PATH", map_json),
        patch.object(mod, "_atomic_write", side_effect=aw_side),
        patch("pathlib.Path.mkdir"),
    ):
        store = GSDStore()
        store.save_map_docs(result)

    with patch.object(mod, "_MAP_PATH", map_json):
        store2 = GSDStore()
        loaded = store2.load_map_docs()

    assert loaded is not None
    assert loaded.stack == "Python 3.11"
    assert loaded.stack == "Python 3.11"


def test_load_map_docs_missing_returns_none(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_MAP_PATH", tmp_path / "missing.json"):
        store = GSDStore()
        assert store.load_map_docs() is None


# ---------------------------------------------------------------------------
# Verify report
# ---------------------------------------------------------------------------

def test_save_and_load_verify_report(tmp_path: Path):
    import backend.database.gsd_store as mod
    with patch.object(mod, "_PHASES_ROOT", tmp_path / "phases"):
        store = GSDStore()
        report = GSDVerifyReport(
            phase=1,
            passed=[VerifyCheckItem(description="health ok", status="passed")],
            failed=[],
            unverifiable=[VerifyCheckItem(description="manual step", status="unverifiable")],
        )
        store.save_verify_report(report, phase_n=1)
        loaded = store.load_verify_report(phase_n=1)
    assert loaded is not None
    assert len(loaded.passed) == 1
    assert loaded.passed[0].description == "health ok"
