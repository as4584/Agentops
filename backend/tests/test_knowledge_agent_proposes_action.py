"""
Week 2 sprint A4 — knowledge_agent must emit a ProposedAction (not prose)
when the user's message contains a remediation intent.

Acceptance criterion (from docs/WEEK_2_SPRINT.md):
  "asking 'nginx is down, restart it' produces a ChatResponse with one
   pending ProposedAction whose action_type == 'process_restart', and the
   action is queryable via GET /actions/pending."

These tests cover three layers:
  - Pure detector (unit) — deterministic regex.
  - Orchestrator integration — call _agent_executor_node directly with a
    mocked LLM/context-assembler; assert proposed_action is attached to
    knowledge_result AND persisted.
  - Round-trip via the actions HTTP API — GET /actions/pending returns it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.agents.action_proposer import detect_remediation_intent
from backend.database import actions_store as actions_store_module
from backend.database import audit_store as audit_store_module
from backend.models.actions import ActionSource, ActionStatus
from backend.routes import actions as actions_route

# ---------------------------------------------------------------------------
# Pure detector
# ---------------------------------------------------------------------------


def test_detector_matches_classic_outage_phrasing() -> None:
    action = detect_remediation_intent("nginx is down, restart it")
    assert action is not None
    assert action.action_type == "process_restart"
    assert action.parameters == {"process_name": "nginx"}
    assert action.status == ActionStatus.PENDING


def test_detector_matches_imperative_restart() -> None:
    action = detect_remediation_intent("please restart the ollama service now")
    assert action is not None
    assert action.parameters["process_name"] == "ollama"


def test_detector_skips_pure_information_queries() -> None:
    assert detect_remediation_intent("is nginx running?") is None
    assert detect_remediation_intent("what is nginx?") is None
    assert detect_remediation_intent("how do I install postgres") is None


def test_detector_ignores_stopword_targets() -> None:
    # "restart it" with no antecedent noun → no actionable target
    assert detect_remediation_intent("just restart it") is None


def test_detector_honours_source_parameter() -> None:
    action = detect_remediation_intent(
        "restart nginx",
        agent_id="knowledge_agent",
        source=ActionSource.DISCORD,
    )
    assert action is not None
    assert action.source is ActionSource.DISCORD
    assert action.agent_id == "knowledge_agent"


# ---------------------------------------------------------------------------
# Orchestrator integration + HTTP round-trip
# ---------------------------------------------------------------------------


def _make_orchestrator() -> Any:
    """Mirror of helper in test_orchestrator_routing.py — no network calls."""
    from backend.orchestrator import AgentOrchestrator

    mock_llm = MagicMock()
    mock_llm.model = "local"
    mock_llm.generate = AsyncMock(return_value="nginx appears unreachable on :80.")
    mock_llm.chat = AsyncMock(return_value="mock chat")

    with (
        patch("backend.orchestrator.KnowledgeVectorStore.__init__", return_value=None),
        patch("backend.orchestrator.GatekeeperAgent.__init__", return_value=None),
    ):
        orch = AgentOrchestrator(llm_client=mock_llm)

    orch._knowledge_store = MagicMock()
    orch._knowledge_store.search = AsyncMock(return_value=[])
    orch._knowledge_store.search_business_profiles = AsyncMock(return_value=[])
    orch._context_assembler = MagicMock()
    orch._context_assembler.retrieve_records = AsyncMock(return_value=[])
    orch._context_assembler.search_business_profiles = AsyncMock(return_value=[])
    orch._context_assembler.health_check.return_value = {"fallback_active": False}
    return orch


@pytest.fixture()
def isolated_stores(tmp_path: Path) -> Path:
    """Point the action + audit singletons at a temp DB so the test is hermetic."""
    actions_store_module.reset_default_store(tmp_path / "actions.db")
    audit_store_module.reset_default_store(tmp_path / "audit.db")
    return tmp_path


@pytest.fixture()
def actions_app(isolated_stores: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(actions_route.router)
    app.include_router(actions_route.audit_router)
    return app


def test_knowledge_agent_emits_proposed_action_via_orchestrator(
    isolated_stores: Path,
) -> None:
    orch = _make_orchestrator()
    state: dict[str, Any] = {
        "target_agent": "knowledge_agent",
        "message": "nginx is down, restart it",
        "context": {},
        "response": "",
        "tool_calls": [],
        "tool_id_registry": None,
        "drift_status": "GREEN",
        "governance_notes": [],
        "timestamp": "",
        "error": None,
        "knowledge_result": None,
    }

    result = asyncio.run(orch._agent_executor_node(state))

    kr = result.get("knowledge_result")
    assert kr is not None, "knowledge_agent must populate knowledge_result"
    proposal = kr.get("proposed_action")
    assert proposal is not None, "remediation intent must surface as proposed_action"
    assert proposal["action_type"] == "process_restart"
    assert proposal["parameters"] == {"process_name": "nginx"}
    assert proposal["status"] == ActionStatus.PENDING.value
    assert proposal["agent_id"] == "knowledge_agent"

    # Persisted: queryable via the actions store.
    pending = actions_store_module.actions_store.list_by_status(ActionStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].id == proposal["id"]


def test_knowledge_agent_information_query_emits_no_proposal(
    isolated_stores: Path,
) -> None:
    orch = _make_orchestrator()
    state: dict[str, Any] = {
        "target_agent": "knowledge_agent",
        "message": "what does nginx do?",
        "context": {},
        "response": "",
        "tool_calls": [],
        "tool_id_registry": None,
        "drift_status": "GREEN",
        "governance_notes": [],
        "timestamp": "",
        "error": None,
        "knowledge_result": None,
    }

    result = asyncio.run(orch._agent_executor_node(state))
    assert result["knowledge_result"]["proposed_action"] is None
    assert actions_store_module.actions_store.list_by_status(ActionStatus.PENDING) == []


def test_proposed_action_is_queryable_via_pending_endpoint(isolated_stores: Path, actions_app: FastAPI) -> None:
    orch = _make_orchestrator()
    state: dict[str, Any] = {
        "target_agent": "knowledge_agent",
        "message": "the backend is crashed please restart it",
        "context": {"source": "discord"},
        "response": "",
        "tool_calls": [],
        "tool_id_registry": None,
        "drift_status": "GREEN",
        "governance_notes": [],
        "timestamp": "",
        "error": None,
        "knowledge_result": None,
    }

    asyncio.run(orch._agent_executor_node(state))

    with TestClient(actions_app) as client:
        r = client.get("/actions/pending")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["action_type"] == "process_restart"
        assert items[0]["parameters"]["process_name"] == "backend"
        assert items[0]["source"] == ActionSource.DISCORD.value
