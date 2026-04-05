"""
ML Learning Lab — Unified experiment runner and self-improvement loop.
=====================================================================
Ties together training data collection, evaluation, benchmarking, and
A/B testing into single-call workflows.

Usage:
    lab = LearningLab()
    report = await lab.health_report()
    result = await lab.run_eval_suite("lex-v2", golden_set="routing_canonical")
    summary = await lab.training_data_summary()
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT
from backend.utils import logger

TRAINING_DIR = PROJECT_ROOT / "data" / "training"
DPO_DIR = PROJECT_ROOT / "data" / "dpo"


@dataclass
class DatasetStats:
    """Summary of all available training data."""

    routing_files: int = 0
    trajectory_files: int = 0
    dpo_files: int = 0
    total_routing_pairs: int = 0
    total_trajectory_pairs: int = 0
    total_dpo_pairs: int = 0
    latest_file: str = ""
    latest_timestamp: str = ""


@dataclass
class LabHealthReport:
    """Overall health of the ML learning lab."""

    timestamp: str = ""
    dataset_stats: DatasetStats = field(default_factory=DatasetStats)
    models_available: list[str] = field(default_factory=list)
    golden_tasks_count: int = 0
    last_eval_score: float | None = None
    recommendations: list[str] = field(default_factory=list)


class LearningLab:
    """Unified entry point for ML experimentation workflows."""

    def __init__(self) -> None:
        self._training_dir = TRAINING_DIR
        self._dpo_dir = DPO_DIR

    def training_data_summary(self) -> DatasetStats:
        """Scan training data directories and return a summary."""
        stats = DatasetStats()

        if self._training_dir.exists():
            for f in sorted(self._training_dir.glob("*.jsonl")):
                lines = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
                name = f.name.lower()
                if "routing" in name or "lex_pairs" in name:
                    stats.routing_files += 1
                    stats.total_routing_pairs += lines
                elif "trajectory" in name:
                    stats.trajectory_files += 1
                    stats.total_trajectory_pairs += lines
                stats.latest_file = f.name
                stats.latest_timestamp = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC).isoformat()

        if self._dpo_dir.exists():
            for f in sorted(self._dpo_dir.glob("*.jsonl")):
                lines = sum(1 for _ in f.open(encoding="utf-8", errors="ignore"))
                stats.dpo_files += 1
                stats.total_dpo_pairs += lines

        return stats

    def health_report(self) -> LabHealthReport:
        """Generate a comprehensive health report for the ML lab."""
        stats = self.training_data_summary()
        report = LabHealthReport(
            timestamp=datetime.now(tz=UTC).isoformat(),
            dataset_stats=stats,
        )

        # Check for available models
        ollama_models_dir = Path.home() / ".ollama" / "models" / "manifests"
        if ollama_models_dir.exists():
            for registry in ollama_models_dir.iterdir():
                if registry.is_dir():
                    for lib in registry.iterdir():
                        if lib.is_dir():
                            for model in lib.iterdir():
                                if model.is_dir():
                                    report.models_available.append(model.name)

        # Recommendations
        if stats.total_routing_pairs < 500:
            report.recommendations.append(
                f"Routing pairs ({stats.total_routing_pairs}) below 500 — "
                "run more training sessions or use synthesize_training_data.py"
            )
        if stats.total_dpo_pairs < 50:
            report.recommendations.append(
                f"DPO pairs ({stats.total_dpo_pairs}) below 50 — need more preference data for boundary refinement"
            )
        if stats.trajectory_files == 0:
            report.recommendations.append("No trajectory data — agents can't learn from execution patterns")
        if not report.models_available:
            report.recommendations.append("No Ollama models detected — run 'ollama pull llama3.2'")

        return report

    def list_golden_tasks(self) -> list[dict[str, Any]]:
        """List all golden evaluation tasks from the registry."""
        golden_path = PROJECT_ROOT / "data" / "training" / "golden_eval_set.jsonl"
        if not golden_path.exists():
            return []
        tasks: list[dict[str, Any]] = []
        with golden_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    tasks.append(json.loads(line))
        return tasks

    def add_golden_task(
        self,
        task_id: str,
        user_message: str,
        expected_agent: str,
        expected_tools: list[str] | None = None,
        difficulty: str = "medium",
        boundary: str = "",
    ) -> dict[str, Any]:
        """Add a canonical evaluation task to the golden set."""
        golden_path = PROJECT_ROOT / "data" / "training" / "golden_eval_set.jsonl"
        golden_path.parent.mkdir(parents=True, exist_ok=True)

        task = {
            "task_id": task_id,
            "user_message": user_message,
            "expected_agent": expected_agent,
            "expected_tools": expected_tools or [],
            "difficulty": difficulty,
            "boundary": boundary,
            "added": datetime.now(tz=UTC).isoformat(),
        }

        with golden_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(task) + "\n")

        logger.info(f"golden_task_added task_id={task_id} agent={expected_agent}")
        return task

    def boundary_coverage(self) -> dict[str, int]:
        """Count training examples per agent boundary pair."""
        coverage: dict[str, int] = {}

        if not self._training_dir.exists():
            return coverage

        for f in self._training_dir.glob("*.jsonl"):
            with f.open(encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    boundary = obj.get("boundary", "")
                    if boundary:
                        coverage[boundary] = coverage.get(boundary, 0) + 1

        return dict(sorted(coverage.items(), key=lambda x: x[1], reverse=True))
