"""
A/B Experiment Harness — Compare models, prompts, and configurations.
=====================================================================
Supports head-to-head comparisons:
- Model A vs Model B (e.g., Qwen vs Llama)
- System prompt A vs System prompt B
- Different chunk sizes, embedding models, tool planners

Each experiment defines variants and runs them against the same eval suite.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger


@dataclass
class Variant:
    """A single configuration variant in an A/B experiment."""

    name: str
    model: str = ""
    system_prompt: str = ""
    temperature: float = 0.7
    chunk_size: int = 512
    embedding_model: str = ""
    tool_planner: str = ""
    extra_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class VariantResult:
    """Aggregated results for one variant across all test cases."""

    variant_name: str
    total_cases: int = 0
    passed: int = 0
    failed: int = 0
    avg_score: float = 0.0
    avg_latency_ms: float = 0.0
    avg_tokens: float = 0.0
    total_cost_usd: float = 0.0
    scores_by_dimension: dict[str, float] = field(default_factory=dict)
    case_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ABExperiment:
    """An A/B experiment comparing multiple variants."""

    experiment_id: str
    name: str
    description: str = ""
    variants: list[Variant] = field(default_factory=list)
    status: str = "created"  # created, running, completed
    created_at: str = ""
    completed_at: str | None = None
    results: dict[str, VariantResult] = field(default_factory=dict)
    winner: str | None = None
    metric_for_winner: str = "avg_score"

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["variants"] = [v.to_dict() for v in self.variants]
        d["results"] = {k: v.to_dict() for k, v in self.results.items()}
        return d


class ABExperimentHarness:
    """Manages A/B experiments: create, run variants, determine winners."""

    def __init__(self, storage_dir: Path | None = None) -> None:
        self._storage_dir = storage_dir or (ML_EXPERIMENTS_DIR / "ab_experiments")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._experiments: dict[str, ABExperiment] = {}
        self._load_experiments()

    def create_experiment(
        self,
        name: str,
        variants: list[dict[str, Any]],
        description: str = "",
        metric_for_winner: str = "avg_score",
    ) -> str:
        """Create a new A/B experiment. Returns experiment_id."""
        ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        h = hashlib.sha256(f"{name}:{ts}".encode()).hexdigest()[:8]
        experiment_id = f"ab_{ts}_{h}"

        parsed_variants = [Variant(**v) for v in variants]
        experiment = ABExperiment(
            experiment_id=experiment_id,
            name=name,
            description=description,
            variants=parsed_variants,
            metric_for_winner=metric_for_winner,
        )

        with self._lock:
            self._experiments[experiment_id] = experiment
            self._save_experiment(experiment)

        logger.info(f"[ABHarness] Created experiment {experiment_id}: {name} ({len(parsed_variants)} variants)")
        return experiment_id

    def record_variant_case(
        self,
        experiment_id: str,
        variant_name: str,
        case_result: dict[str, Any],
    ) -> None:
        """Record a single case result for a variant."""
        with self._lock:
            exp = self._get_experiment(experiment_id)
            if exp.status == "completed":
                raise ValueError(f"Experiment {experiment_id} is already completed")
            if exp.status == "created":
                exp.status = "running"

            if variant_name not in exp.results:
                exp.results[variant_name] = VariantResult(variant_name=variant_name)

            vr = exp.results[variant_name]
            vr.case_results.append(case_result)
            vr.total_cases = len(vr.case_results)
            vr.passed = sum(1 for c in vr.case_results if c.get("passed", False))
            vr.failed = vr.total_cases - vr.passed

            scores = [c.get("overall_score", 0.0) for c in vr.case_results]
            vr.avg_score = sum(scores) / len(scores) if scores else 0.0

            latencies = [c.get("latency_ms", 0.0) for c in vr.case_results]
            vr.avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

            tokens = [c.get("tokens_in", 0) + c.get("tokens_out", 0) for c in vr.case_results]
            vr.avg_tokens = sum(tokens) / len(tokens) if tokens else 0.0

            vr.total_cost_usd = sum(c.get("cost_usd", 0.0) for c in vr.case_results)

            self._save_experiment(exp)

    def complete_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Finalize experiment and determine winner."""
        with self._lock:
            exp = self._get_experiment(experiment_id)
            exp.status = "completed"
            exp.completed_at = datetime.now(UTC).isoformat()

            # Determine winner
            if exp.results:
                metric = exp.metric_for_winner
                best_name = None
                best_val = -1.0
                for name, vr in exp.results.items():
                    val = getattr(vr, metric, vr.avg_score)
                    if val > best_val:
                        best_val = val
                        best_name = name
                exp.winner = best_name

            self._save_experiment(exp)
            logger.info(f"[ABHarness] Completed {experiment_id} — winner: {exp.winner}")
            return exp.to_dict()

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        return self._get_experiment(experiment_id).to_dict()

    def list_experiments(self, status: str | None = None) -> list[dict[str, Any]]:
        exps = list(self._experiments.values())
        if status:
            exps = [e for e in exps if e.status == status]
        return [e.to_dict() for e in sorted(exps, key=lambda e: e.created_at, reverse=True)]

    def compare_variants(self, experiment_id: str) -> dict[str, Any]:
        """Side-by-side comparison of all variants in an experiment."""
        exp = self._get_experiment(experiment_id)
        comparison: dict[str, Any] = {
            "experiment_id": experiment_id,
            "name": exp.name,
            "status": exp.status,
            "winner": exp.winner,
            "variants": {},
        }
        for name, vr in exp.results.items():
            comparison["variants"][name] = {
                "total_cases": vr.total_cases,
                "passed": vr.passed,
                "failed": vr.failed,
                "pass_rate": vr.passed / vr.total_cases if vr.total_cases > 0 else 0.0,
                "avg_score": vr.avg_score,
                "avg_latency_ms": vr.avg_latency_ms,
                "avg_tokens": vr.avg_tokens,
                "total_cost_usd": vr.total_cost_usd,
            }
        return comparison

    def _get_experiment(self, experiment_id: str) -> ABExperiment:
        if experiment_id not in self._experiments:
            path = self._storage_dir / f"{experiment_id}.json"
            if path.exists():
                data = json.loads(path.read_text())
                self._experiments[experiment_id] = self._from_dict(data)
            else:
                raise KeyError(f"Experiment not found: {experiment_id}")
        return self._experiments[experiment_id]

    def _save_experiment(self, exp: ABExperiment) -> None:
        path = self._storage_dir / f"{exp.experiment_id}.json"
        path.write_text(json.dumps(exp.to_dict(), indent=2, default=str))

    def _load_experiments(self) -> None:
        for f in self._storage_dir.glob("ab_*.json"):
            data = json.loads(f.read_text())
            exp = self._from_dict(data)
            self._experiments[exp.experiment_id] = exp

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> ABExperiment:
        variants = [Variant(**v) for v in data.get("variants", [])]
        results = {}
        for name, vr_data in data.get("results", {}).items():
            results[name] = VariantResult(**vr_data)
        return ABExperiment(
            experiment_id=data["experiment_id"],
            name=data["name"],
            description=data.get("description", ""),
            variants=variants,
            status=data.get("status", "created"),
            created_at=data.get("created_at", ""),
            completed_at=data.get("completed_at"),
            results=results,
            winner=data.get("winner"),
            metric_for_winner=data.get("metric_for_winner", "avg_score"),
        )
