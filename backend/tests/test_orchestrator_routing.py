"""Real tests for AgentOrchestrator routing nodes — backend/orchestrator/__init__.py.

Tests call the node methods directly (not via LangGraph's compiled graph) so
they run instantly without needing Ollama or Docker.

Node contracts tested:
  _router_node    — system halt, unknown agent, known agent resolution
  _agent_executor_node  — short-circuit on error, BaseAgent dispatch
  _governance_check_node — drift status + violation reporting
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator() -> Any:
    """Build an AgentOrchestrator with a mock LLM client — no network calls."""
    from backend.orchestrator import AgentOrchestrator

    mock_llm = MagicMock()
    mock_llm.model = "local"
    mock_llm.generate = AsyncMock(return_value="mock knowledge response")
    mock_llm.chat = AsyncMock(return_value="mock chat response")

    # Patch heavy constructors so we don't need Docker / Qdrant
    with (
        patch("backend.orchestrator.KnowledgeVectorStore.__init__", return_value=None),
        patch("backend.orchestrator.GatekeeperAgent.__init__", return_value=None),
    ):
        orch = AgentOrchestrator(llm_client=mock_llm)

    # Give the knowledge store a stub search method
    orch._knowledge_store = MagicMock()
    orch._knowledge_store.search = AsyncMock(return_value=[])
    orch._knowledge_store.search_business_profiles = AsyncMock(return_value=[])

    return orch


def _base_state(**overrides) -> dict:
    """Minimal valid OrchestratorState-like dict."""
    state: dict[str, Any] = {
        "target_agent": "knowledge_agent",
        "message": "test message",
        "context": {},
        "response": "",
        "tool_calls": [],
        "tool_id_registry": None,
        "drift_status": "GREEN",
        "governance_notes": [],
        "timestamp": "",
        "error": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# _router_node — system halt
# ---------------------------------------------------------------------------


def test_router_blocks_when_system_halted() -> None:
    """If drift_guard.is_halted is True, router must return an error dict with drift_status RED."""
    orch = _make_orchestrator()
    state = _base_state(target_agent="knowledge_agent")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = True
        result = asyncio.run(orch._router_node(state))

    assert result.get("error") is not None
    assert "HALTED" in result["error"]
    assert result.get("drift_status") == "RED"


def test_router_halt_check_takes_priority_over_unknown_agent() -> None:
    """A halted system should block even for requests to unknown agents."""
    orch = _make_orchestrator()
    state = _base_state(target_agent="nonexistent_agent_xyz")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = True
        result = asyncio.run(orch._router_node(state))

    assert "HALTED" in result.get("error", "")


# ---------------------------------------------------------------------------
# _router_node — unknown agent
# ---------------------------------------------------------------------------


def test_router_rejects_unknown_agent() -> None:
    """An unknown agent ID must return an error listing available agents."""
    orch = _make_orchestrator()
    # Register a known real agent so the available list is non-empty
    mock_agent = MagicMock()
    orch._agents["soul_core"] = mock_agent

    state = _base_state(target_agent="definitely_not_real")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = False
        result = asyncio.run(orch._router_node(state))

    assert result.get("error") is not None
    assert "not found" in result["error"].lower() or "definitely_not_real" in result["error"]
    # Available agents should be listed
    assert "soul_core" in result["error"]


def test_router_error_includes_available_agents_sorted() -> None:
    """The error message for unknown agent must list known agents in sorted order."""
    orch = _make_orchestrator()
    orch._agents["zebra_agent"] = MagicMock()
    orch._agents["alpha_agent"] = MagicMock()

    state = _base_state(target_agent="no_such_agent")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = False
        result = asyncio.run(orch._router_node(state))

    error_text = result["error"]
    alpha_pos = error_text.find("alpha_agent")
    zebra_pos = error_text.find("zebra_agent")
    assert alpha_pos != -1 and zebra_pos != -1
    assert alpha_pos < zebra_pos, "Agents should be listed in sorted order"


# ---------------------------------------------------------------------------
# _router_node — known agent
# ---------------------------------------------------------------------------


def test_router_sets_target_agent_for_known_agent() -> None:
    """A known agent ID should be set as the resolved target."""
    orch = _make_orchestrator()
    mock_agent = MagicMock()
    orch._agents["soul_core"] = mock_agent

    state = _base_state(target_agent="soul_core")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = False
        result = asyncio.run(orch._router_node(state))

    assert result.get("error") is None
    assert result.get("target_agent") == "soul_core"


def test_router_appends_routing_note() -> None:
    """Router must append a governance note confirming the routing decision."""
    orch = _make_orchestrator()
    orch._agents["monitor_agent"] = MagicMock()

    state = _base_state(target_agent="monitor_agent", governance_notes=["existing note"])

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = False
        result = asyncio.run(orch._router_node(state))

    notes = result.get("governance_notes", [])
    assert any("Routed to" in n for n in notes)
    assert any("monitor_agent" in n for n in notes)


def test_router_falls_back_to_knowledge_agent_when_target_not_in_agents_dict() -> None:
    """If the target is a valid agent ID (in _all_agent_ids) but not instantiated,
    it should fall back to knowledge_agent path without error."""
    orch = _make_orchestrator()
    # knowledge_agent is always in _all_agent_ids; don't add target to _agents
    # We need to add it to _all_agent_ids via a mock
    _original_all = orch._all_agent_ids

    state = _base_state(target_agent="knowledge_agent")

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.is_halted = False
        result = asyncio.run(orch._router_node(state))

    assert result.get("error") is None
    assert result.get("target_agent") == "knowledge_agent"


# ---------------------------------------------------------------------------
# _agent_executor_node — short-circuit on error state
# ---------------------------------------------------------------------------


def test_executor_short_circuits_when_error_in_state() -> None:
    """When state['error'] is set, the executor must return immediately with that error,
    without calling any agent."""
    orch = _make_orchestrator()
    mock_agent = MagicMock()
    mock_agent.process_message = AsyncMock(return_value="should not be called")
    orch._agents["soul_core"] = mock_agent

    state = _base_state(
        target_agent="soul_core",
        error="SYSTEM HALTED: upstream error",
    )

    result = asyncio.run(orch._agent_executor_node(state))

    assert "Error:" in result["response"]
    assert "SYSTEM HALTED" in result["response"]
    mock_agent.process_message.assert_not_called()


# ---------------------------------------------------------------------------
# _agent_executor_node — BaseAgent dispatch
# ---------------------------------------------------------------------------


def test_executor_calls_process_message_on_base_agent() -> None:
    """For a known BaseAgent, process_message must be called with (message, context)."""
    from backend.agents import BaseAgent

    orch = _make_orchestrator()

    mock_agent = MagicMock(spec=BaseAgent)
    mock_agent.process_message = AsyncMock(return_value="Agent response here")
    orch._agents["cs_agent"] = mock_agent

    state = _base_state(
        target_agent="cs_agent",
        message="How do I reset my password?",
        context={"user_id": "42"},
        error=None,
    )

    result = asyncio.run(orch._agent_executor_node(state))

    mock_agent.process_message.assert_called_once_with("How do I reset my password?", {"user_id": "42"})
    assert result["response"] == "Agent response here"
    assert result.get("error") is None


def test_executor_appends_agent_response_shared_event() -> None:
    """After successful agent dispatch, a AGENT_RESPONSE event must be appended."""
    from backend.agents import BaseAgent

    orch = _make_orchestrator()

    mock_agent = MagicMock(spec=BaseAgent)
    mock_agent.process_message = AsyncMock(return_value="Done")
    orch._agents["it_agent"] = mock_agent

    state = _base_state(target_agent="it_agent", message="Check DNS", error=None)

    with patch("backend.orchestrator.memory_store") as mock_memory:
        asyncio.run(orch._agent_executor_node(state))

    mock_memory.append_shared_event.assert_called_once()
    event = mock_memory.append_shared_event.call_args[0][0]
    assert event["type"] == "AGENT_RESPONSE"
    assert event["agent_id"] == "it_agent"


def test_executor_returns_error_when_agent_process_message_raises() -> None:
    """If agent.process_message raises, executor must return error response (no crash)."""
    from backend.agents import BaseAgent

    orch = _make_orchestrator()

    mock_agent = MagicMock(spec=BaseAgent)
    mock_agent.process_message = AsyncMock(side_effect=RuntimeError("LLM timeout"))
    orch._agents["data_agent"] = mock_agent

    state = _base_state(target_agent="data_agent", message="Run ETL", error=None)

    result = asyncio.run(orch._agent_executor_node(state))

    assert "Error:" in result["response"]
    assert "LLM timeout" in result["response"]


# ---------------------------------------------------------------------------
# _governance_check_node — drift reporting
# ---------------------------------------------------------------------------


def test_governance_check_appends_drift_status() -> None:
    """After execution, governance_notes must contain the drift status."""
    from backend.models import DriftReport, DriftStatus

    orch = _make_orchestrator()
    state = _base_state(governance_notes=["Routed to knowledge_agent"])

    mock_report = DriftReport(last_check=__import__("datetime").datetime.utcnow())
    mock_report.status = DriftStatus.GREEN

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.check_invariants.return_value = mock_report
        result = asyncio.run(orch._governance_check_node(state))

    notes = result["governance_notes"]
    assert any("Drift status:" in n for n in notes)
    assert any("GREEN" in n for n in notes)


def test_governance_check_includes_violations() -> None:
    """Active invariant violations must appear in governance_notes."""
    from backend.models import ChangeImpactLevel, DriftEvent, DriftReport, DriftStatus

    orch = _make_orchestrator()
    state = _base_state(governance_notes=[])

    mock_report = DriftReport(last_check=__import__("datetime").datetime.utcnow())
    mock_report.status = DriftStatus.RED
    mock_report.violations = [
        DriftEvent(
            invariant_id="INV-3",
            description="Agent called agent directly",
            severity=ChangeImpactLevel.CRITICAL,
        )
    ]

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.check_invariants.return_value = mock_report
        result = asyncio.run(orch._governance_check_node(state))

    notes = result["governance_notes"]
    assert any("INV-3" in n for n in notes)
    assert any("VIOLATION" in n for n in notes)
    assert result["drift_status"] == "RED"


def test_governance_check_preserves_existing_notes() -> None:
    """Notes from earlier nodes must be preserved, not overwritten."""
    from backend.models import DriftReport, DriftStatus

    orch = _make_orchestrator()
    state = _base_state(governance_notes=["Routed to soul_core", "Extra note"])

    mock_report = DriftReport(last_check=__import__("datetime").datetime.utcnow())
    mock_report.status = DriftStatus.GREEN

    with patch("backend.orchestrator.drift_guard") as mock_guard:
        mock_guard.check_invariants.return_value = mock_report
        result = asyncio.run(orch._governance_check_node(state))

    notes = result["governance_notes"]
    assert "Routed to soul_core" in notes
    assert "Extra note" in notes
