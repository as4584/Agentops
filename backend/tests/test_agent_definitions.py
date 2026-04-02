"""Deterministic tests for agent definitions and orchestrator pure-logic.

Tests ALL_AGENT_DEFINITIONS, OrchestratorState, INTAKE_QUESTIONS, AgentMessage.
No Ollama. No LangGraph execution.
"""

from __future__ import annotations

import pytest

from backend.agents import ALL_AGENT_DEFINITIONS
from backend.orchestrator import INTAKE_QUESTIONS, AgentMessage

# ── ALL_AGENT_DEFINITIONS Validation ────────────────────────────────


# The canonical agent IDs from copilot-instructions.md
# knowledge_agent is created dynamically by the orchestrator, not in ALL_AGENT_DEFINITIONS
CANONICAL_AGENTS = {
    "soul_core",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "cs_agent",
    "it_agent",
}


class TestAllAgentDefinitions:
    def test_agent_definitions_exist(self):
        assert len(ALL_AGENT_DEFINITIONS) > 0

    def test_canonical_agents_registered(self):
        """Every canonical agent from the architecture spec must be registered."""
        registered_ids = set(ALL_AGENT_DEFINITIONS.keys())
        for agent_id in CANONICAL_AGENTS:
            assert agent_id in registered_ids, f"Missing canonical agent: {agent_id}"

    def test_no_duplicate_agent_ids(self):
        # dict keys are unique by definition, but check programmatically
        ids = list(ALL_AGENT_DEFINITIONS.keys())
        assert len(ids) == len(set(ids))

    def test_each_agent_has_required_fields(self):
        for agent_id, defn in ALL_AGENT_DEFINITIONS.items():
            assert defn.agent_id == agent_id, f"Mismatched key vs agent_id for {agent_id}"
            assert defn.role, f"Agent {agent_id} has no role"
            assert defn.system_prompt, f"Agent {agent_id} has no system_prompt"
            assert defn.memory_namespace, f"Agent {agent_id} has no memory_namespace"

    def test_tool_permissions_are_strings(self):
        """All tool permissions should be non-empty strings."""
        for agent_id, defn in ALL_AGENT_DEFINITIONS.items():
            for tool in defn.tool_permissions:
                assert isinstance(tool, str) and len(tool) > 0, (
                    f"Agent {agent_id} has invalid tool permission: {tool!r}"
                )

    def test_memory_namespace_unique_per_agent(self):
        """Each agent must have a unique memory namespace."""
        namespaces = [defn.memory_namespace for defn in ALL_AGENT_DEFINITIONS.values()]
        assert len(namespaces) == len(set(namespaces))


# ── INTAKE_QUESTIONS ─────────────────────────────────────────────────


class TestIntakeQuestions:
    def test_intake_questions_count(self):
        assert len(INTAKE_QUESTIONS) == 8

    def test_each_question_is_tuple_pair(self):
        for key, question in INTAKE_QUESTIONS:
            assert isinstance(key, str) and len(key) > 0
            assert isinstance(question, str) and len(question) > 0

    def test_unique_keys(self):
        keys = [k for k, _ in INTAKE_QUESTIONS]
        assert len(keys) == len(set(keys))


# ── AgentMessage Model ───────────────────────────────────────────────


class TestAgentMessage:
    def test_create_minimal(self):
        msg = AgentMessage(
            message_id="msg-1",
            thread_id="thread-1",
            from_agent="soul_core",
            to_agent="devops_agent",
            purpose="deploy",
            payload={"branch": "dev"},
            created_at="2026-03-30T00:00:00Z",
        )
        assert msg.from_agent == "soul_core"
        assert msg.depth == 0
        assert msg.parent_message_id is None

    def test_depth_non_negative(self):
        with pytest.raises(Exception):
            AgentMessage(
                message_id="msg-1",
                thread_id="thread-1",
                from_agent="a",
                to_agent="b",
                purpose="test",
                payload={},
                created_at="2026-01-01",
                depth=-1,
            )

    def test_with_parent_message(self):
        msg = AgentMessage(
            message_id="msg-2",
            thread_id="thread-1",
            from_agent="devops_agent",
            to_agent="soul_core",
            parent_message_id="msg-1",
            depth=1,
            purpose="deploy_result",
            payload={"status": "ok"},
            created_at="2026-03-30T00:00:01Z",
        )
        assert msg.parent_message_id == "msg-1"
        assert msg.depth == 1

    def test_serialization(self):
        msg = AgentMessage(
            message_id="msg-3",
            thread_id="thread-2",
            from_agent="comms_agent",
            to_agent="it_agent",
            purpose="alert",
            payload={"severity": "high"},
            created_at="2026-03-30T12:00:00Z",
        )
        data = msg.model_dump()
        assert data["from_agent"] == "comms_agent"
        assert data["payload"]["severity"] == "high"
