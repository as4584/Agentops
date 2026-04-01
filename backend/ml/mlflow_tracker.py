"""
MLflow Tracker — MLflow-backed experiment tracking for Agentop.
================================================================
Wraps MLflow's tracking API to log experiments locally. Tracks:
model, prompt, temperature, dataset, latency, cost, eval score, pass/fail.

Usage:
    tracker = MLflowTracker()
    with tracker.start_run("qwen_vs_llama", params={...}) as run_id:
        tracker.log_metrics(run_id, {"accuracy": 0.92, "latency_ms": 450})
        tracker.log_llm_call(run_id, model="llama3.2", prompt="...", ...)
"""

from __future__ import annotations

import json
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from backend.config import ML_EXPERIMENTS_DIR
from backend.utils import logger

try:
    import mlflow
    from mlflow.tracking import MlflowClient

    MLFLOW_AVAILABLE = True
except ImportError:
    mlflow = None  # type: ignore[assignment]
    MlflowClient = None  # type: ignore[assignment,misc]
    MLFLOW_AVAILABLE = False


class MLflowTracker:
    """MLflow-backed experiment tracker with comprehensive LLM run logging."""

    def __init__(
        self,
        tracking_uri: str | None = None,
        experiment_name: str = "agentop",
    ) -> None:
        self._lock = Lock()
        self._active_runs: dict[str, Any] = {}  # run_id -> mlflow run object

        if not MLFLOW_AVAILABLE:
            logger.warning("[MLflowTracker] mlflow not installed — using fallback JSON tracking")
            self._fallback_dir = ML_EXPERIMENTS_DIR / "mlflow_fallback"
            self._fallback_dir.mkdir(parents=True, exist_ok=True)
            self._client = None
            return

        uri = tracking_uri or str(ML_EXPERIMENTS_DIR / "mlruns")
        mlflow.set_tracking_uri(f"file://{uri}")  # type: ignore[union-attr]
        mlflow.set_experiment(experiment_name)  # type: ignore[union-attr]
        self._client = MlflowClient(tracking_uri=f"file://{uri}")  # type: ignore[misc]
        self._experiment_name = experiment_name
        logger.info(f"[MLflowTracker] Initialized — tracking to {uri}")

    @contextmanager
    def start_run(
        self,
        run_name: str,
        params: dict[str, Any] | None = None,
        tags: dict[str, str] | None = None,
    ) -> Generator[str, None, None]:
        """Context manager to start and auto-close an MLflow run."""
        if not MLFLOW_AVAILABLE:
            run_id = f"fallback_{int(time.time() * 1000)}"
            self._active_runs[run_id] = {
                "name": run_name,
                "params": params or {},
                "tags": tags or {},
                "metrics": {},
                "artifacts": [],
                "started_at": datetime.now(UTC).isoformat(),
            }
            try:
                yield run_id
            finally:
                self._end_fallback_run(run_id)
            return

        with self._lock:
            run = mlflow.start_run(run_name=run_name)  # type: ignore[union-attr]
            run_id = run.info.run_id
            self._active_runs[run_id] = run

        if params:
            # MLflow params must be strings
            str_params = {k: str(v) for k, v in params.items()}
            mlflow.log_params(str_params)  # type: ignore[union-attr]
        if tags:
            mlflow.set_tags(tags)  # type: ignore[union-attr]

        try:
            yield run_id
        except Exception as e:
            mlflow.set_tag("error", str(e)[:250])  # type: ignore[union-attr]
            mlflow.end_run(status="FAILED")  # type: ignore[union-attr]
            with self._lock:
                self._active_runs.pop(run_id, None)
            raise
        else:
            mlflow.end_run(status="FINISHED")  # type: ignore[union-attr]
            with self._lock:
                self._active_runs.pop(run_id, None)

    def log_metrics(self, run_id: str, metrics: dict[str, float], step: int | None = None) -> None:
        """Log multiple metrics at once."""
        if not MLFLOW_AVAILABLE:
            if run_id in self._active_runs:
                for k, v in metrics.items():
                    self._active_runs[run_id]["metrics"][k] = v
            return

        with self._lock:
            if run_id in self._active_runs:
                with mlflow.start_run(run_id=run_id, nested=True):  # type: ignore[union-attr]
                    mlflow.log_metrics(metrics, step=step)  # type: ignore[union-attr]

    def log_llm_call(
        self,
        run_id: str,
        *,
        model: str,
        prompt: str,
        response: str = "",
        temperature: float = 0.7,
        latency_ms: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        eval_score: float | None = None,
        pass_fail: bool | None = None,
        task_type: str = "",
    ) -> None:
        """Log a single LLM invocation with full metadata."""
        metrics: dict[str, float] = {
            "latency_ms": latency_ms,
            "tokens_in": float(tokens_in),
            "tokens_out": float(tokens_out),
            "cost_usd": cost_usd,
            "temperature": temperature,
        }
        if eval_score is not None:
            metrics["eval_score"] = eval_score
        if pass_fail is not None:
            metrics["pass_fail"] = 1.0 if pass_fail else 0.0

        params = {
            "model": model,
            "task_type": task_type,
            "prompt_length": str(len(prompt)),
        }

        if not MLFLOW_AVAILABLE:
            if run_id in self._active_runs:
                self._active_runs[run_id]["metrics"].update(metrics)
                self._active_runs[run_id]["params"].update(params)
            return

        with self._lock:
            if run_id in self._active_runs:
                with mlflow.start_run(run_id=run_id, nested=True):  # type: ignore[union-attr]
                    mlflow.log_metrics(metrics)  # type: ignore[union-attr]
                    # Log prompt/response as artifacts to avoid param length limits
                    artifact_dir = ML_EXPERIMENTS_DIR / "artifacts" / run_id
                    artifact_dir.mkdir(parents=True, exist_ok=True)
                    call_log = {
                        "model": model,
                        "prompt": prompt[:2000],  # Truncate for storage
                        "response": response[:2000],
                        "temperature": temperature,
                        "task_type": task_type,
                        "timestamp": datetime.now(UTC).isoformat(),
                    }
                    log_path = artifact_dir / f"llm_call_{int(time.time() * 1000)}.json"
                    log_path.write_text(json.dumps(call_log, indent=2))
                    mlflow.log_artifact(str(log_path))  # type: ignore[union-attr]

    def log_artifact(self, run_id: str, path: str) -> None:
        """Log a file artifact to the run."""
        if not MLFLOW_AVAILABLE:
            if run_id in self._active_runs:
                self._active_runs[run_id]["artifacts"].append(path)
            return

        with self._lock:
            if run_id in self._active_runs:
                with mlflow.start_run(run_id=run_id, nested=True):  # type: ignore[union-attr]
                    mlflow.log_artifact(path)  # type: ignore[union-attr]

    def search_runs(
        self,
        experiment_name: str | None = None,
        filter_string: str = "",
        max_results: int = 100,
    ) -> list[dict[str, Any]]:
        """Search runs with optional filter."""
        if not MLFLOW_AVAILABLE:
            # Return fallback runs from disk
            results = []
            fallback_dir = ML_EXPERIMENTS_DIR / "mlflow_fallback"
            if fallback_dir.exists():
                for f in sorted(fallback_dir.glob("*.json"), reverse=True)[:max_results]:
                    results.append(json.loads(f.read_text()))
            return results

        exp_name = experiment_name or self._experiment_name
        experiment = self._client.get_experiment_by_name(exp_name)  # type: ignore[union-attr]
        if not experiment:
            return []

        runs = self._client.search_runs(  # type: ignore[union-attr]
            experiment_ids=[experiment.experiment_id],
            filter_string=filter_string,
            max_results=max_results,
        )
        return [
            {
                "run_id": r.info.run_id,
                "run_name": r.info.run_name,
                "status": r.info.status,
                "params": dict(r.data.params),
                "metrics": dict(r.data.metrics),
                "tags": dict(r.data.tags),
                "start_time": r.info.start_time,
                "end_time": r.info.end_time,
            }
            for r in runs
        ]

    def get_best_run(
        self,
        metric: str = "eval_score",
        higher_is_better: bool = True,
        experiment_name: str | None = None,
    ) -> dict[str, Any] | None:
        """Find the best run by a metric."""
        runs = self.search_runs(
            experiment_name=experiment_name,
            filter_string=f"metrics.{metric} > 0",
            max_results=1,
        )
        if not runs:
            return None
        # Sort manually since search_runs doesn't guarantee order by metric
        runs_with_metric = [r for r in runs if metric in r.get("metrics", {})]
        if not runs_with_metric:
            return None
        return sorted(
            runs_with_metric,
            key=lambda r: r["metrics"].get(metric, 0),
            reverse=higher_is_better,
        )[0]

    def _end_fallback_run(self, run_id: str) -> None:
        """Persist a fallback run to JSON."""
        if run_id not in self._active_runs:
            return
        run_data = self._active_runs.pop(run_id)
        run_data["ended_at"] = datetime.now(UTC).isoformat()
        run_data["run_id"] = run_id
        fallback_dir = ML_EXPERIMENTS_DIR / "mlflow_fallback"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        out_path = fallback_dir / f"{run_id}.json"
        out_path.write_text(json.dumps(run_data, indent=2))
