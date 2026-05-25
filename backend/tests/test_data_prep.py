"""
Regression tests for the finetune_lex.py data preparation pipeline.

These tests guard against the class of silent data loss bugs where training
files load with "0 SFT + 0 DPO" because a new format variant falls through
to the "unknown format, skipping" branch.

Failure of any test here means training data will be silently discarded.
"""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers to import functions directly from the script (not a package)
# ---------------------------------------------------------------------------

def _load_module():
    """Import finetune_lex.py as a module without executing __main__."""
    root = Path(__file__).parents[2]
    script = root / "scripts" / "finetune_lex.py"
    spec = importlib.util.spec_from_file_location("finetune_lex", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Prevent the script body from running side-effects at import time
    sys.modules.setdefault("finetune_lex", mod)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.fixture(scope="module")
def lex():
    return _load_module()


# ---------------------------------------------------------------------------
# Unit: _normalize_routing_pair
# ---------------------------------------------------------------------------

class TestNormalizeRoutingPair:
    def test_valid_pair_becomes_sharegpt(self, lex):
        rec = {
            "user_message": "deploy the backend to prod",
            "expected_agent": "devops_agent",
            "reasoning": "Deployment is a devops task.",
            "difficulty": "hard",
            "expected_tools": ["safe_shell", "git_ops"],
            "confidence": 0.85,
        }
        result = lex._normalize_routing_pair(rec)
        assert result is not None
        convs = result["conversations"]
        assert len(convs) == 2
        assert convs[0]["from"] == "human"
        assert "deploy the backend to prod" in convs[0]["value"]
        assert convs[1]["from"] == "gpt"
        assert "devops_agent" in convs[1]["value"]

    def test_tools_included_in_gpt_turn(self, lex):
        rec = {
            "user_message": "check the logs",
            "expected_agent": "monitor_agent",
            "reasoning": "Log inspection.",
            "expected_tools": ["log_tail"],
            "confidence": 0.9,
        }
        result = lex._normalize_routing_pair(rec)
        assert result is not None
        assert "log_tail" in result["conversations"][1]["value"]

    def test_missing_user_message_returns_none(self, lex):
        rec = {"expected_agent": "devops_agent", "reasoning": "no message"}
        assert lex._normalize_routing_pair(rec) is None

    def test_missing_expected_agent_returns_none(self, lex):
        rec = {"user_message": "hello", "reasoning": "no agent"}
        assert lex._normalize_routing_pair(rec) is None

    def test_metadata_preserved(self, lex):
        rec = {
            "user_message": "scan for secrets",
            "expected_agent": "security_agent",
            "reasoning": "Security scan.",
            "difficulty": "easy",
            "confidence": 0.95,
        }
        result = lex._normalize_routing_pair(rec)
        assert result is not None
        assert result["_expected_agent"] == "security_agent"
        assert result["_difficulty"] == "easy"
        assert result["_confidence"] == 0.95
        assert result["_source"] == "routing_pair"


# ---------------------------------------------------------------------------
# Unit: load_sharegpt_file — format dispatch
# ---------------------------------------------------------------------------

class TestLoadSharegptFile:
    def _write_jsonl(self, tmp_path: Path, records: list[dict]) -> Path:
        p = tmp_path / "test.jsonl"
        with open(p, "w") as f:
            for r in records:
                json.dump(r, f)
                f.write("\n")
        return p

    def test_sharegpt_format_loaded(self, lex, tmp_path):
        records = [
            {"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "hello"}]}
        ]
        p = self._write_jsonl(tmp_path, records)
        result = lex.load_sharegpt_file(p)
        assert len(result) == 1
        assert "conversations" in result[0]

    def test_routing_pair_format_loaded_as_sharegpt(self, lex, tmp_path):
        """Regression: opus_session_routing files must NOT produce 'unknown format'."""
        records = [
            {
                "user_message": "turn this repo into a skill",
                "expected_agent": "devops_agent",
                "reasoning": "Skill creation is a build task.",
                "difficulty": "hard",
                "expected_tools": ["file_reader", "safe_shell"],
                "confidence": 0.75,
            }
        ]
        p = self._write_jsonl(tmp_path, records)
        result = lex.load_sharegpt_file(p)
        assert len(result) == 1, "Routing pair must be converted to a training record"
        assert "conversations" in result[0]

    def test_trajectory_format_loaded_as_sharegpt(self, lex, tmp_path):
        """Regression: trajectory files with task_type+chosen_agent must not produce 'unknown format'."""
        records = [
            {
                "task": "Deploy updated Discord bot safely",
                "task_type": "deployment",
                "goal": "Ship bot update without breaking current service",
                "constraints": ["Ubuntu only", "minimal diff"],
                "chosen_agent": "devops_agent",
                "rejected_agents": ["self_healer_agent"],
                "plan": ["Inspect service config", "Run tests", "Restart service"],
            }
        ]
        p = self._write_jsonl(tmp_path, records)
        result = lex.load_sharegpt_file(p)
        assert len(result) == 1, "Trajectory record must be converted to a training record"
        assert "conversations" in result[0]
        assert "devops_agent" in result[0]["conversations"][1]["value"]

    def test_live_dpo_format_loaded(self, lex, tmp_path):
        records = [
            {
                "user_message": "check security",
                "chosen_agent": "security_agent",
                "good_response": "I will scan secrets.",
                "bad_response": "I don't know.",
                "good_plan": "scan",
                "bad_plan": "nothing",
                "why_good_is_better": "uses the right tool",
                "category": "boundary_security",
            }
        ]
        p = self._write_jsonl(tmp_path, records)
        result = lex.load_sharegpt_file(p)
        assert len(result) == 1
        assert "prompt" in result[0] or "chosen" in result[0]

    def test_invalid_json_skipped(self, lex, tmp_path, capsys):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"valid": true}\nnot json\n{"valid": true}\n')
        result = lex.load_sharegpt_file(p)
        # Two valid lines, one bad
        assert len(result) == 0  # valid lines don't match known formats but no crash
        out = capsys.readouterr().out
        assert "invalid JSON" in out

    def test_unknown_format_warns(self, lex, tmp_path, capsys):
        records = [{"completely": "unknown", "format": True}]
        p = self._write_jsonl(tmp_path, records)
        lex.load_sharegpt_file(p)
        out = capsys.readouterr().out
        assert "unknown format" in out

    def test_empty_file_returns_empty(self, lex, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert lex.load_sharegpt_file(p) == []

    def test_routing_pair_without_agent_skipped(self, lex, tmp_path, capsys):
        """A routing record missing expected_agent must warn, not crash."""
        records = [{"user_message": "do something", "reasoning": "dunno"}]
        p = self._write_jsonl(tmp_path, records)
        result = lex.load_sharegpt_file(p)
        # No conversations produced — falls through to unknown format warning
        sharegpt = [r for r in result if "conversations" in r]
        assert len(sharegpt) == 0


# ---------------------------------------------------------------------------
# Unit: conversation_hash — dedup stability
# ---------------------------------------------------------------------------

class TestConversationHash:
    def test_same_conversation_same_hash(self, lex):
        c = {"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "hello"}]}
        assert lex.conversation_hash(c) == lex.conversation_hash(c)

    def test_different_conversations_different_hash(self, lex):
        c1 = {"conversations": [{"from": "human", "value": "hi"}]}
        c2 = {"conversations": [{"from": "human", "value": "bye"}]}
        assert lex.conversation_hash(c1) != lex.conversation_hash(c2)

    def test_prompt_format_hashed(self, lex):
        c = {"prompt": "route this", "chosen": "devops", "rejected": "cs"}
        h = lex.conversation_hash(c)
        assert isinstance(h, str) and len(h) == 16


# ---------------------------------------------------------------------------
# Unit: validate_conversations — data quality gate
# ---------------------------------------------------------------------------

class TestValidateConversations:
    def test_valid_conversation_passes(self, lex):
        records = [{"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": "hello"}]}]
        result = lex.validate_conversations(records)
        assert len(result) == 1

    def test_too_short_dropped(self, lex):
        records = [{"conversations": [{"from": "human", "value": "hi"}]}]
        assert lex.validate_conversations(records) == []

    def test_must_start_with_human(self, lex):
        records = [{"conversations": [{"from": "gpt", "value": "hi"}, {"from": "human", "value": "ok"}]}]
        assert lex.validate_conversations(records) == []

    def test_must_have_gpt_turn(self, lex):
        records = [{"conversations": [{"from": "human", "value": "hi"}, {"from": "human", "value": "hey"}]}]
        assert lex.validate_conversations(records) == []

    def test_empty_value_dropped(self, lex):
        records = [{"conversations": [{"from": "human", "value": "hi"}, {"from": "gpt", "value": ""}]}]
        assert lex.validate_conversations(records) == []

    def test_routing_pair_normalized_record_passes_validation(self, lex):
        """End-to-end: routing pair → normalize → validate → valid record."""
        raw = {
            "user_message": "scan code for secrets",
            "expected_agent": "security_agent",
            "reasoning": "Secret scanning is security_agent's role.",
            "expected_tools": ["secret_scanner"],
            "confidence": 0.92,
        }
        normalized = lex._normalize_routing_pair(raw)
        assert normalized is not None
        valid = lex.validate_conversations([normalized])
        assert len(valid) == 1, "Normalized routing pair must survive validation"
