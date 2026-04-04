"""Tests for the agent factory and decision collector."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from backend.ml.decision_collector import (
    DecisionCollector,
    PreferencePair,
    RoutingDecision,
    Trajectory,
)
from backend.orchestrator.agent_factory import (
    MAX_FACTORY_AGENTS,
    AgentBlueprint,
    AgentFactory,
)

# ---------------------------------------------------------------------------
# Agent Factory tests
# ---------------------------------------------------------------------------


class TestAgentBlueprint:
    def test_valid_blueprint(self):
        bp = AgentBlueprint(
            agent_id="test_agent",
            role="Test agent for unit testing purposes",
            system_prompt="You are a test agent for unit tests.",
            tool_permissions=["file_reader"],
            rationale="Needed for testing the factory",
        )
        assert bp.agent_id == "test_agent"

    def test_invalid_agent_id_uppercase(self):
        with pytest.raises(ValueError, match="lowercase snake_case"):
            AgentBlueprint(
                agent_id="TestAgent",
                role="Test agent for testing",
                system_prompt="You are a test agent.",
                rationale="Testing",
            )

    def test_invalid_agent_id_too_short(self):
        with pytest.raises(ValueError, match="lowercase snake_case"):
            AgentBlueprint(
                agent_id="ab",
                role="Test agent for testing",
                system_prompt="You are a test agent.",
                rationale="Testing",
            )

    def test_invalid_agent_id_hyphen(self):
        with pytest.raises(ValueError, match="lowercase snake_case"):
            AgentBlueprint(
                agent_id="test-agent",
                role="Test agent for testing",
                system_prompt="You are a test agent.",
                rationale="Testing",
            )

    def test_invalid_tool(self):
        with pytest.raises(ValueError, match="Unknown tools"):
            AgentBlueprint(
                agent_id="test_agent",
                role="Test agent for testing",
                system_prompt="You are a test agent.",
                tool_permissions=["nonexistent_tool"],
                rationale="Testing",
            )

    def test_valid_tools(self):
        bp = AgentBlueprint(
            agent_id="test_agent",
            role="Test agent for testing",
            system_prompt="You are a test agent.",
            tool_permissions=["file_reader", "safe_shell"],
            rationale="Testing with valid tools",
        )
        assert set(bp.tool_permissions) == {"file_reader", "safe_shell"}


class TestAgentFactory:
    def setup_method(self):
        self.factory = AgentFactory()
        self.factory._created = {}

    def _make_blueprint(self, agent_id: str = "test_agent", **kwargs) -> AgentBlueprint:  # type: ignore[arg-type]
        defaults = {
            "agent_id": agent_id,
            "role": "Test agent for unit testing purposes",
            "system_prompt": "You are a test agent for unit tests.",
            "rationale": "Needed for testing",
        }
        defaults.update(kwargs)
        return AgentBlueprint(**defaults)  # type: ignore[arg-type]

    def test_create_agent_success(self):
        bp = self._make_blueprint()
        result = self.factory.create_agent(bp, existing_ids=set())
        assert result.success
        assert result.agent_id == "test_agent"
        assert result.definition is not None
        assert result.definition.memory_namespace == "test_agent"

    def test_create_agent_duplicate(self):
        bp = self._make_blueprint()
        self.factory.create_agent(bp, existing_ids=set())
        result = self.factory.create_agent(bp, existing_ids=set())
        assert not result.success
        assert "already exists" in (result.error or "")

    def test_create_agent_existing_static(self):
        bp = self._make_blueprint(agent_id="soul_core")
        result = self.factory.create_agent(bp, existing_ids={"soul_core"})
        assert not result.success
        assert "already exists" in (result.error or "")

    def test_create_high_impact_requires_soul(self):
        from backend.models import ChangeImpactLevel

        bp = self._make_blueprint(
            change_impact_level=ChangeImpactLevel.HIGH,
            requested_by="orchestrator",
        )
        result = self.factory.create_agent(bp, existing_ids=set())
        assert not result.success
        assert "soul_core" in (result.error or "")

    def test_create_high_impact_soul_allowed(self):
        from backend.models import ChangeImpactLevel

        bp = self._make_blueprint(
            change_impact_level=ChangeImpactLevel.HIGH,
            requested_by="soul_core",
        )
        result = self.factory.create_agent(bp, existing_ids=set())
        assert result.success

    def test_max_agents_limit(self):
        for i in range(MAX_FACTORY_AGENTS):
            bp = self._make_blueprint(agent_id=f"agent_{i:03d}")
            self.factory.create_agent(bp, existing_ids=set())

        bp = self._make_blueprint(agent_id="one_too_many")
        result = self.factory.create_agent(bp, existing_ids=set())
        assert not result.success
        assert "limit" in (result.error or "").lower()

    def test_delete_agent(self):
        bp = self._make_blueprint()
        self.factory.create_agent(bp, existing_ids=set())
        assert self.factory.count == 1
        assert self.factory.delete_agent("test_agent")
        assert self.factory.count == 0

    def test_delete_nonexistent(self):
        assert not self.factory.delete_agent("ghost_agent")

    def test_list_agents(self):
        self.factory.create_agent(self._make_blueprint("agent_a"), existing_ids=set())
        self.factory.create_agent(self._make_blueprint("agent_b"), existing_ids=set())
        agents = self.factory.list_agents()
        assert len(agents) == 2
        ids = {a.agent_id for a in agents}
        assert ids == {"agent_a", "agent_b"}


# ---------------------------------------------------------------------------
# Decision Collector tests
# ---------------------------------------------------------------------------


class TestDecisionCollector:
    def setup_method(self):
        self.collector = DecisionCollector()

    def test_record_routing_decision(self, tmp_path):
        # Use data_agent — not in any weak boundary pair
        with patch.object(self.collector, "_routing_path", return_value=tmp_path / "routing.jsonl"):
            with patch.object(self.collector, "_lex_training_path", return_value=tmp_path / "lex.jsonl"):
                with patch.object(self.collector, "_dpo_path", return_value=tmp_path / "dpo.jsonl"):
                    decision = self.collector.record_routing_decision(
                        user_message="run the ETL pipeline",
                        chosen_agent="data_agent",
                        method="lex",
                        confidence=0.92,
                        latency_ms=150.0,
                    )

        assert decision.chosen_agent == "data_agent"
        assert decision.difficulty == "easy"
        assert not decision.is_boundary

    def test_record_boundary_decision(self, tmp_path):
        with patch.object(self.collector, "_routing_path", return_value=tmp_path / "routing.jsonl"):
            with patch.object(self.collector, "_lex_training_path", return_value=tmp_path / "lex.jsonl"):
                with patch.object(self.collector, "_dpo_path", return_value=tmp_path / "dpo.jsonl"):
                    decision = self.collector.record_routing_decision(
                        user_message="search the docs for purpose",
                        chosen_agent="knowledge_agent",
                        method="lex",
                        confidence=0.65,
                        latency_ms=800.0,
                    )

        assert decision.is_boundary
        assert "soul_core" in decision.boundary_agents
        assert decision.difficulty == "hard"  # conf 0.65 < 0.7 → hard

    def test_record_hard_decision(self, tmp_path):
        with patch.object(self.collector, "_routing_path", return_value=tmp_path / "routing.jsonl"):
            with patch.object(self.collector, "_lex_training_path", return_value=tmp_path / "lex.jsonl"):
                with patch.object(self.collector, "_dpo_path", return_value=tmp_path / "dpo.jsonl"):
                    decision = self.collector.record_routing_decision(
                        user_message="something vague",
                        chosen_agent="soul_core",
                        method="keyword",
                        confidence=0.55,
                        latency_ms=1.0,
                    )

        assert decision.difficulty == "hard"

    def test_record_feedback_creates_pair(self, tmp_path):
        with patch.object(self.collector, "_dpo_path", return_value=tmp_path / "dpo.jsonl"):
            pair = self.collector.record_feedback(
                user_message="what's the project purpose?",
                original_agent="knowledge_agent",
                correct_agent="soul_core",
                reasoning="Abstract reflection, not doc search",
            )

        assert pair.chosen_agent == "soul_core"
        assert "correction" in pair.category

        # Verify JSONL was written
        lines = (tmp_path / "dpo.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["chosen_agent"] == "soul_core"

    def test_record_feedback_invalid_agent(self):
        with pytest.raises(ValueError, match="Invalid agent"):
            self.collector.record_feedback(
                user_message="test",
                original_agent="soul_core",
                correct_agent="nonexistent_agent",
            )

    def test_record_trajectory(self, tmp_path):
        with patch.object(self.collector, "_trajectory_path", return_value=tmp_path / "traj.jsonl"):
            traj = self.collector.record_trajectory(
                task="Deploy the bot",
                task_type="deployment",
                goal="Ship bot update",
                chosen_agent="devops_agent",
                actions=["git_ops: checked diff", "safe_shell: ran tests"],
                result="Deployed successfully",
                success=True,
            )

        assert traj.chosen_agent == "devops_agent"
        assert traj.success

        lines = (tmp_path / "traj.jsonl").read_text().strip().split("\n")
        assert len(lines) == 1

    def test_get_stats(self, tmp_path):
        stats = self.collector.get_stats()
        assert "routing_decisions" in stats
        assert "dpo_pairs" in stats
        assert "trajectories" in stats


# ---------------------------------------------------------------------------
# Pydantic model tests
# ---------------------------------------------------------------------------


class TestRoutingDecision:
    def test_defaults(self):
        d = RoutingDecision(
            user_message="test",
            chosen_agent="soul_core",
            method="keyword",
            confidence=0.8,
            latency_ms=1.0,
        )
        assert d.was_correct is None
        assert d.difficulty == "medium"


class TestPreferencePair:
    def test_model(self):
        p = PreferencePair(
            task="test",
            user_message="test",
            chosen_agent="devops_agent",
            good_response="Route to devops_agent",
            bad_response="Route to soul_core",
        )
        assert p.chosen_agent == "devops_agent"


class TestTrajectory:
    def test_model(self):
        t = Trajectory(
            task="test",
            task_type="general",
            goal="test goal",
            chosen_agent="devops_agent",
            actions=["safe_shell: ls"],
            result="done",
        )
        assert t.success  # default
