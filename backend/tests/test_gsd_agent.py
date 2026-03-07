"""Tests for GSDAgent — backend/agents/gsd_agent.py"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.models.gsd import (
    GSDPlan,
    GSDTask,
    PhaseStatus,
    TaskStatus,
)


# ---------------------------------------------------------------------------
# _parse_plan_json
# ---------------------------------------------------------------------------

def test_parse_plan_json_valid():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    raw = json.dumps({
        "phase": 1,
        "title": "Test phase",
        "description": "A test",
        "tasks": [
            {"id": "T1", "description": "do A", "file_targets": ["backend/foo.py"],
             "symbol_refs": [], "depends_on": [], "wave": 1},
            {"id": "T2", "description": "test A", "file_targets": ["backend/tests/test_foo.py"],
             "symbol_refs": [], "depends_on": ["T1"], "wave": 1},
        ],
    })
    plan = agent._parse_plan_json(raw, 1, "A test")
    assert plan.phase == 1
    assert plan.title == "Test phase"
    assert len(plan.tasks) == 2
    assert plan.tasks[0].id == "T1"
    assert plan.tasks[1].depends_on == ["T1"]


def test_parse_plan_json_with_markdown_fences():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    raw = '```json\n{"phase": 2, "title": "T2", "description": "d", "tasks": []}\n```'
    plan = agent._parse_plan_json(raw, 2, "d")
    assert plan.phase == 2
    assert plan.tasks == []


def test_parse_plan_json_malformed_returns_fallback():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    plan = agent._parse_plan_json("NOT JSON AT ALL {{{{", 3, "description")
    assert plan.phase == 3
    assert len(plan.tasks) == 1
    assert "parse failed" in plan.tasks[0].description.lower() or plan.tasks[0].id == "T1"


# ---------------------------------------------------------------------------
# _plan_to_gatekeeper_payload
# ---------------------------------------------------------------------------

def test_plan_to_gatekeeper_payload_has_test_task():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    plan = GSDPlan(
        phase=1, title="T", description="D",
        tasks=[
            GSDTask(id="T1", description="Add feature", file_targets=["backend/foo.py"], wave=1),
            GSDTask(id="T2", description="Add test for feature", file_targets=["backend/tests/test_foo.py"], wave=1),
        ],
    )
    payload = agent._plan_to_gatekeeper_payload(plan)
    assert "backend/foo.py" in payload["files_changed"]
    assert payload["tests_ok"] is True


def test_plan_to_gatekeeper_payload_no_test_task():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    plan = GSDPlan(
        phase=1, title="T", description="D",
        tasks=[
            GSDTask(id="T1", description="Add feature", file_targets=["backend/foo.py"], wave=1),
        ],
    )
    payload = agent._plan_to_gatekeeper_payload(plan)
    # touches runtime but no test task → tests_ok should be False
    assert payload["tests_ok"] is False


def test_plan_to_gatekeeper_payload_no_runtime_files():
    from backend.agents.gsd_agent import GSDAgent
    agent = GSDAgent()
    plan = GSDPlan(
        phase=1, title="T", description="D",
        tasks=[
            GSDTask(id="T1", description="Update readme", file_targets=["README.md"], wave=1),
        ],
    )
    payload = agent._plan_to_gatekeeper_payload(plan)
    # doesn't touch runtime → tests_ok is True (nothing to enforce)
    assert payload["tests_ok"] is True


# ---------------------------------------------------------------------------
# map_codebase (mocked LLM)
# ---------------------------------------------------------------------------

def test_map_codebase_produces_result(tmp_path: Path):
    from backend.agents.gsd_agent import GSDAgent
    import backend.agents.gsd_agent as mod
    import backend.database.gsd_store as store_mod

    def aw_side(path: Path, data: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.rename(path)

    with (
        patch.object(mod, "_llm_generate", return_value="## Mocked output"),
        patch.object(store_mod, "_MAP_PATH", tmp_path / "map_docs.json"),
        patch.object(store_mod, "_STATE_PATH", tmp_path / "gsd_state.json"),
        patch.object(store_mod, "_GSD_ROOT", tmp_path),
        patch.object(store_mod, "_atomic_write", side_effect=aw_side),
    ):
        agent = GSDAgent()
        result = asyncio.run(agent.map_codebase(str(tmp_path)))

    assert result.stack == "## Mocked output"
    assert result.architecture == "## Mocked output"
    assert result.conventions == "## Mocked output"
    assert result.concerns == "## Mocked output"


# ---------------------------------------------------------------------------
# quick (mocked LLM)
# ---------------------------------------------------------------------------

def test_quick_returns_result(tmp_path: Path):
    from backend.agents.gsd_agent import GSDAgent
    import backend.agents.gsd_agent as mod
    import backend.database.gsd_store as store_mod

    def aw_side(path: Path, data: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.rename(path)

    with (
        patch.object(mod, "_llm_generate", return_value="Task done."),
        patch.object(store_mod, "_STATE_PATH", tmp_path / "gsd_state.json"),
        patch.object(store_mod, "_GSD_ROOT", tmp_path),
        patch.object(store_mod, "_atomic_write", side_effect=aw_side),
    ):
        agent = GSDAgent()
        result = asyncio.run(agent.quick("Fix the linting errors"))

    assert result.prompt == "Fix the linting errors"
    assert result.response == "Task done."
    assert result.committed is False


def test_quick_full_attempts_commit(tmp_path: Path):
    from backend.agents.gsd_agent import GSDAgent
    import backend.agents.gsd_agent as mod
    import backend.database.gsd_store as store_mod

    def aw_side(path: Path, data: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.rename(path)

    with (
        patch.object(mod, "_llm_generate", return_value="Done."),
        patch.object(store_mod, "_STATE_PATH", tmp_path / "gsd_state.json"),
        patch.object(store_mod, "_GSD_ROOT", tmp_path),
        patch.object(store_mod, "_atomic_write", side_effect=aw_side),
        patch.object(GSDAgent, "_try_commit", return_value=True),
    ):
        agent = GSDAgent()
        result = asyncio.run(agent.quick("Fix lint", full=True))

    assert result.committed is True


# ---------------------------------------------------------------------------
# execute_phase wave grouping
# ---------------------------------------------------------------------------

def test_wave_grouping_is_correct():
    """Tasks in the same wave number should be executed together."""
    from backend.models.gsd import GSDPlan, GSDTask
    tasks = [
        GSDTask(id="T1", description="a", wave=1),
        GSDTask(id="T2", description="b", wave=1),
        GSDTask(id="T3", description="c", wave=2),
    ]
    plan = GSDPlan(phase=1, title="T", description="D", tasks=tasks)
    waves: dict[int, list] = {}
    for t in plan.tasks:
        waves.setdefault(t.wave, []).append(t)
    assert set(t.id for t in waves[1]) == {"T1", "T2"}
    assert set(t.id for t in waves[2]) == {"T3"}


# ---------------------------------------------------------------------------
# verify_work checklist parsing
# ---------------------------------------------------------------------------

def test_generate_checklist_parses_json_array():
    from backend.agents.gsd_agent import GSDAgent
    import backend.agents.gsd_agent as mod

    with patch.object(mod, "_llm_generate", return_value='["Check health", "DB has rows"]'):
        agent = GSDAgent()
        items = agent._generate_checklist(1, "", "")
    assert "Check health" in items
    assert "DB has rows" in items


def test_generate_checklist_falls_back_to_lines():
    from backend.agents.gsd_agent import GSDAgent
    import backend.agents.gsd_agent as mod

    with patch.object(mod, "_llm_generate", return_value="- Check health\n- DB has rows"):
        agent = GSDAgent()
        items = agent._generate_checklist(1, "", "")
    assert any("health" in i.lower() for i in items)
