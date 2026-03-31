"""Tests for A/B Experiment Harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.ml.ab_experiment import ABExperimentHarness, Variant


@pytest.fixture
def harness(tmp_path: Path) -> ABExperimentHarness:
    return ABExperimentHarness(storage_dir=tmp_path / "ab")


VARIANTS = [
    {"name": "llama3", "model": "llama3.2", "temperature": 0.7},
    {"name": "qwen", "model": "qwen2.5", "temperature": 0.5},
]


class TestABExperimentHarness:
    def test_create_experiment(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("test_ab", VARIANTS, description="test")
        assert exp_id.startswith("ab_")

    def test_get_experiment(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("test_ab", VARIANTS)
        exp = harness.get_experiment(exp_id)
        assert exp["name"] == "test_ab"
        assert len(exp["variants"]) == 2

    def test_record_variant_case(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("test_ab", VARIANTS)
        harness.record_variant_case(
            exp_id,
            "llama3",
            {
                "case_id": "c1",
                "passed": True,
                "overall_score": 0.9,
                "latency_ms": 100,
                "tokens_in": 50,
                "tokens_out": 80,
                "cost_usd": 0.001,
            },
        )
        exp = harness.get_experiment(exp_id)
        assert exp["status"] == "running"

    def test_complete_experiment(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("test_ab", VARIANTS)
        harness.record_variant_case(
            exp_id,
            "llama3",
            {
                "passed": True,
                "overall_score": 0.9,
                "latency_ms": 100,
                "tokens_in": 50,
                "tokens_out": 80,
                "cost_usd": 0.001,
            },
        )
        harness.record_variant_case(
            exp_id,
            "qwen",
            {
                "passed": True,
                "overall_score": 0.85,
                "latency_ms": 200,
                "tokens_in": 60,
                "tokens_out": 90,
                "cost_usd": 0.002,
            },
        )
        result = harness.complete_experiment(exp_id)
        assert result["status"] == "completed"
        assert result["winner"] == "llama3"

    def test_compare_variants(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("test_ab", VARIANTS)
        harness.record_variant_case(
            exp_id,
            "llama3",
            {
                "passed": True,
                "overall_score": 0.9,
                "latency_ms": 100,
                "tokens_in": 50,
                "tokens_out": 80,
                "cost_usd": 0.001,
            },
        )
        comparison = harness.compare_variants(exp_id)
        assert "llama3" in comparison["variants"]

    def test_list_experiments(self, harness: ABExperimentHarness) -> None:
        harness.create_experiment("exp1", VARIANTS)
        harness.create_experiment("exp2", VARIANTS)
        exps = harness.list_experiments()
        assert len(exps) == 2

    def test_list_experiments_by_status(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("exp1", VARIANTS)
        harness.record_variant_case(exp_id, "llama3", {"passed": True, "overall_score": 0.9})
        harness.complete_experiment(exp_id)
        harness.create_experiment("exp2", VARIANTS)
        assert len(harness.list_experiments(status="completed")) == 1
        assert len(harness.list_experiments(status="created")) == 1

    def test_experiment_not_found(self, harness: ABExperimentHarness) -> None:
        with pytest.raises(KeyError):
            harness.get_experiment("nonexistent")

    def test_record_after_completion(self, harness: ABExperimentHarness) -> None:
        exp_id = harness.create_experiment("done", VARIANTS)
        harness.record_variant_case(exp_id, "llama3", {"passed": True, "overall_score": 0.9})
        harness.complete_experiment(exp_id)
        with pytest.raises(ValueError):
            harness.record_variant_case(exp_id, "llama3", {"passed": True, "overall_score": 0.8})

    def test_variant_config_hash(self) -> None:
        v = Variant(name="test", model="llama3.2")
        h = v.config_hash()
        assert len(h) == 12
        # Deterministic
        assert v.config_hash() == h

    def test_persistence_reload(self, tmp_path: Path) -> None:
        h1 = ABExperimentHarness(storage_dir=tmp_path / "ab")
        exp_id = h1.create_experiment("persist_test", VARIANTS)
        h1.record_variant_case(exp_id, "llama3", {"passed": True, "overall_score": 0.9})
        # Create a new instance to test loading from disk
        h2 = ABExperimentHarness(storage_dir=tmp_path / "ab")
        exp = h2.get_experiment(exp_id)
        assert exp["name"] == "persist_test"
