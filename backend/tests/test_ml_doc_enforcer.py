"""
Tests for MLDocEnforcer — change logging, goal logging, compliance audits.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.ml.doc_enforcer import MLDocEnforcer


@pytest.fixture
def enforcer(tmp_path: Path) -> MLDocEnforcer:
    doc = tmp_path / "ML_CHANGELOG.md"
    with patch("backend.ml.doc_enforcer.ML_DIR", tmp_path):
        return MLDocEnforcer(doc_path=doc)


class TestMLDocEnforcer:
    # ── log_change ───────────────────────────────────

    def test_log_change_writes_markdown(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_change(
            agent_name="gsd_agent",
            change_type="pipeline_change",
            description="Added feature extraction step",
        )
        md = enforcer._doc_path.read_text()
        assert "gsd_agent" in md
        assert "PIPELINE_CHANGE" in md
        assert "Added feature extraction step" in md

    def test_log_change_writes_jsonl(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_change(
            agent_name="devops_agent",
            change_type="config_change",
            description="Bumped accuracy threshold to 0.90",
            details={"old": 0.85, "new": 0.90},
        )
        lines = enforcer._audit_path.read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["agent_name"] == "devops_agent"
        assert record["change_type"] == "config_change"
        assert record["details"]["new"] == 0.90

    def test_log_change_with_run_id(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_change(
            agent_name="soul_core",
            change_type="training_run",
            description="Retrained classifier",
            run_id="run-123",
        )
        lines = enforcer._audit_path.read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["run_id"] == "run-123"

    # ── log_goal ─────────────────────────────────────

    def test_log_goal(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_goal(
            agent_name="gsd_agent",
            goal="Achieve 95% accuracy on intent classification",
            success_criteria="accuracy >= 0.95, latency < 200ms",
        )
        md = enforcer._doc_path.read_text()
        assert "95%" in md

        lines = enforcer._audit_path.read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["change_type"] == "goal_added"
        assert "95%" in record["description"]

    # ── log_training_run ─────────────────────────────

    def test_log_training_run(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_training_run(
            agent_name="gsd_agent",
            run_id="run-456",
            model_type="random_forest",
            metrics={"accuracy": 0.92, "f1": 0.89},
            dataset_version="abc123",
        )
        md = enforcer._doc_path.read_text()
        assert "run-456" in md
        assert "random_forest" in md

        lines = enforcer._audit_path.read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["change_type"] == "training_run"
        assert record["run_id"] == "run-456"

    # ── get_recent_entries ───────────────────────────

    def test_get_recent_entries(self, enforcer: MLDocEnforcer) -> None:
        for i in range(5):
            enforcer.log_change("agent", "config_change", f"Change {i}")

        recent = enforcer.get_recent_entries(limit=3)
        assert len(recent) == 3
        # Last 3 entries (2, 3, 4) in original order
        assert "Change 2" in recent[0]["description"]
        assert "Change 4" in recent[2]["description"]

    def test_get_recent_entries_empty(self, enforcer: MLDocEnforcer) -> None:
        recent = enforcer.get_recent_entries()
        assert recent == []

    # ── audit_compliance ─────────────────────────────

    def test_audit_compliance_all_documented(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_training_run("a", "r1", "svm", {"acc": 0.8}, "v1")
        enforcer.log_training_run("a", "r2", "rf", {"acc": 0.9}, "v2")

        result = enforcer.audit_compliance(["r1", "r2"])
        assert result["compliant"] is True
        assert result["documented"] == 2
        assert result["missing"] == []

    def test_audit_compliance_missing_runs(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_training_run("a", "r1", "svm", {"acc": 0.8}, "v1")

        result = enforcer.audit_compliance(["r1", "r2", "r3"])
        assert result["compliant"] is False
        assert result["documented"] == 1
        assert set(result["missing"]) == {"r2", "r3"}

    # ── Multiple writes ──────────────────────────────

    def test_multiple_entries_append(self, enforcer: MLDocEnforcer) -> None:
        enforcer.log_change("a", "config_change", "First")
        enforcer.log_change("b", "data_update", "Second")
        enforcer.log_goal("c", "Goal X", "metric >= 0.9")

        lines = enforcer._audit_path.read_text().strip().split("\n")
        assert len(lines) == 3

        md = enforcer._doc_path.read_text()
        assert "First" in md
        assert "Second" in md
        assert "Goal X" in md
