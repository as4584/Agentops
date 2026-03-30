"""
Experiment Tracker — Records every ML training/eval run.
=========================================================
Tracks: model type, hyperparameters, dataset version, metrics, artifacts.
Persists to JSON on disk. No cloud dependencies (no MLflow/W&B).

Usage:
    tracker = ExperimentTracker()
    run_id = tracker.start_run("intent_classifier", {"lr": 0.001, "epochs": 50})
    tracker.log_metric(run_id, "accuracy", 0.92)
    tracker.log_metric(run_id, "f1", 0.89)
    tracker.log_artifact(run_id, "/path/to/model.pkl")
    tracker.end_run(run_id, status="completed")
    tracker.compare_runs(["run_001", "run_002"])
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger


class ExperimentRun:
    """Single experiment run record."""

    def __init__(
        self,
        run_id: str,
        experiment_name: str,
        model_type: str,
        hyperparameters: dict[str, Any],
        dataset_version: str,
        tags: Optional[dict[str, str]] = None,
    ) -> None:
        self.run_id = run_id
        self.experiment_name = experiment_name
        self.model_type = model_type
        self.hyperparameters = hyperparameters
        self.dataset_version = dataset_version
        self.tags = tags or {}
        self.metrics: dict[str, list[dict[str, Any]]] = {}
        self.artifacts: list[str] = []
        self.status: str = "running"
        self.started_at: str = datetime.now(timezone.utc).isoformat()
        self.ended_at: Optional[str] = None
        self.notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "experiment_name": self.experiment_name,
            "model_type": self.model_type,
            "hyperparameters": self.hyperparameters,
            "dataset_version": self.dataset_version,
            "tags": self.tags,
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperimentRun:
        run = cls(
            run_id=data["run_id"],
            experiment_name=data["experiment_name"],
            model_type=data["model_type"],
            hyperparameters=data["hyperparameters"],
            dataset_version=data["dataset_version"],
            tags=data.get("tags", {}),
        )
        run.metrics = data.get("metrics", {})
        run.artifacts = data.get("artifacts", [])
        run.status = data.get("status", "unknown")
        run.started_at = data.get("started_at", "")
        run.ended_at = data.get("ended_at")
        run.notes = data.get("notes", "")
        return run


class ExperimentTracker:
    """Persists all ML experiment runs to disk as structured JSON."""

    def __init__(self, experiments_dir: Optional[Path] = None) -> None:
        self._dir = experiments_dir or ML_EXPERIMENTS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self._dir / "index.json"
        self._lock = Lock()
        self._runs: dict[str, ExperimentRun] = {}
        self._load_index()

    # ── Public API ───────────────────────────────────────

    def start_run(
        self,
        experiment_name: str,
        hyperparameters: dict[str, Any],
        model_type: str = "",
        dataset_version: str = "",
        tags: Optional[dict[str, str]] = None,
    ) -> str:
        """Start a new experiment run. Returns its run_id."""
        run_id = self._generate_run_id(experiment_name)
        run = ExperimentRun(
            run_id=run_id,
            experiment_name=experiment_name,
            model_type=model_type,
            hyperparameters=hyperparameters,
            dataset_version=dataset_version,
            tags=tags,
        )
        with self._lock:
            self._runs[run_id] = run
            self._save_run(run)
            self._save_index()
        logger.info(f"[ExperimentTracker] Started run {run_id} for {experiment_name}")
        return run_id

    def log_metric(
        self, run_id: str, name: str, value: float, step: Optional[int] = None
    ) -> None:
        """Log a metric value for a run (supports time-series via step)."""
        with self._lock:
            run = self._get_run(run_id)
            if name not in run.metrics:
                run.metrics[name] = []
            entry: dict[str, Any] = {
                "value": value,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if step is not None:
                entry["step"] = step
            run.metrics[name].append(entry)
            self._save_run(run)

    def log_artifact(self, run_id: str, artifact_path: str) -> None:
        """Register an artifact (model file, plot, etc.) for a run."""
        with self._lock:
            run = self._get_run(run_id)
            run.artifacts.append(artifact_path)
            self._save_run(run)

    def end_run(self, run_id: str, status: str = "completed", notes: str = "") -> None:
        """Mark a run as complete (or failed)."""
        with self._lock:
            run = self._get_run(run_id)
            run.status = status
            run.ended_at = datetime.now(timezone.utc).isoformat()
            run.notes = notes
            self._save_run(run)
            self._save_index()
        logger.info(f"[ExperimentTracker] Ended run {run_id} — {status}")

    def get_run(self, run_id: str) -> dict[str, Any]:
        """Get a single run by ID."""
        return self._get_run(run_id).to_dict()

    def list_runs(
        self,
        experiment_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """List all runs, optionally filtered."""
        runs = list(self._runs.values())
        if experiment_name:
            runs = [r for r in runs if r.experiment_name == experiment_name]
        if status:
            runs = [r for r in runs if r.status == status]
        return [r.to_dict() for r in sorted(runs, key=lambda r: r.started_at, reverse=True)]

    def compare_runs(self, run_ids: list[str]) -> list[dict[str, Any]]:
        """Compare multiple runs side by side — returns latest metric per run."""
        results = []
        for rid in run_ids:
            run = self._get_run(rid)
            latest_metrics = {}
            for name, entries in run.metrics.items():
                if entries:
                    latest_metrics[name] = entries[-1]["value"]
            results.append({
                "run_id": rid,
                "experiment_name": run.experiment_name,
                "model_type": run.model_type,
                "hyperparameters": run.hyperparameters,
                "dataset_version": run.dataset_version,
                "status": run.status,
                "metrics": latest_metrics,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
            })
        return results

    def best_run(
        self, experiment_name: str, metric: str = "accuracy", higher_is_better: bool = True
    ) -> Optional[dict[str, Any]]:
        """Find the best run for an experiment by a given metric."""
        runs = [r for r in self._runs.values() if r.experiment_name == experiment_name]
        best: Optional[ExperimentRun] = None
        best_value: Optional[float] = None
        for run in runs:
            entries = run.metrics.get(metric, [])
            if not entries:
                continue
            val = entries[-1]["value"]
            if best_value is None or (
                (higher_is_better and val > best_value)
                or (not higher_is_better and val < best_value)
            ):
                best_value = val
                best = run
        return best.to_dict() if best else None

    # ── Internals ────────────────────────────────────────

    def _get_run(self, run_id: str) -> ExperimentRun:
        if run_id not in self._runs:
            # Try loading from disk
            run_path = self._dir / f"{run_id}.json"
            if run_path.exists():
                data = json.loads(run_path.read_text())
                self._runs[run_id] = ExperimentRun.from_dict(data)
            else:
                raise KeyError(f"Run not found: {run_id}")
        return self._runs[run_id]

    def _generate_run_id(self, experiment_name: str) -> str:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        h = hashlib.sha256(f"{experiment_name}:{ts}".encode()).hexdigest()[:8]
        return f"{experiment_name}_{ts}_{h}"

    def _save_run(self, run: ExperimentRun) -> None:
        path = self._dir / f"{run.run_id}.json"
        path.write_text(json.dumps(run.to_dict(), indent=2))

    def _save_index(self) -> None:
        index = {
            rid: {
                "experiment_name": r.experiment_name,
                "status": r.status,
                "started_at": r.started_at,
                "model_type": r.model_type,
            }
            for rid, r in self._runs.items()
        }
        self._index_path.write_text(json.dumps(index, indent=2))

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            index = json.loads(self._index_path.read_text())
            for run_id in index:
                run_path = self._dir / f"{run_id}.json"
                if run_path.exists():
                    data = json.loads(run_path.read_text())
                    self._runs[run_id] = ExperimentRun.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"[ExperimentTracker] Failed to load index: {e}")
