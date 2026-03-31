"""
ML Documentation Enforcer — Mandatory change logging for ML space.
===================================================================
Every agent must call MLDocEnforcer.log_change() when:
  - A training run completes
  - A model is deployed or swapped
  - A pipeline step is modified
  - A new goal/objective is added
  - Monitoring thresholds change
  - Training data is updated

The log is append-only Markdown at docs/ML_CHANGELOG.md.
The enforcer also validates that changes have been logged (audit mode).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import ML_DIR, ML_DOC_PATH
from backend.utils import logger


class MLDocEnforcer:
    """Enforces and manages ML documentation requirements."""

    def __init__(self, doc_path: Path | None = None) -> None:
        self._doc_path = doc_path or ML_DOC_PATH
        self._audit_path = ML_DIR / "audit_log.jsonl"
        self._lock = Lock()
        self._ensure_doc_exists()

    def log_change(
        self,
        agent_name: str,
        change_type: str,
        description: str,
        details: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> None:
        """Log an ML change. This MUST be called by any agent modifying ML state.

        change_type: one of training_run, model_deploy, pipeline_change,
                     goal_added, threshold_change, data_update, config_change
        """
        timestamp = datetime.now(UTC)
        ts_str = timestamp.strftime("%Y-%m-%d %H:%M UTC")

        # Append to Markdown changelog
        entry = f"\n### [{ts_str}] {change_type.upper()} — {agent_name}\n\n{description}\n"
        if run_id:
            entry += f"\n- **Run ID:** `{run_id}`\n"
        if details:
            for k, v in details.items():
                entry += f"- **{k}:** {v}\n"
        entry += "\n---\n"

        with self._lock:
            with open(self._doc_path, "a") as f:
                f.write(entry)

            # Also write structured audit log
            audit_record = {
                "timestamp": timestamp.isoformat(),
                "agent_name": agent_name,
                "change_type": change_type,
                "description": description,
                "details": details or {},
                "run_id": run_id,
            }
            self._audit_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._audit_path, "a") as f:
                f.write(json.dumps(audit_record) + "\n")

        logger.info(f"[MLDocEnforcer] Logged {change_type} by {agent_name}: {description[:80]}")

    def log_goal(self, agent_name: str, goal: str, success_criteria: str = "") -> None:
        """Log a new ML goal/objective."""
        details = {}
        if success_criteria:
            details["Success Criteria"] = success_criteria
        self.log_change(
            agent_name=agent_name,
            change_type="goal_added",
            description=f"New ML goal: {goal}",
            details=details,
        )

    def log_training_run(
        self,
        agent_name: str,
        run_id: str,
        model_type: str,
        metrics: dict[str, float],
        dataset_version: str = "",
    ) -> None:
        """Log a training run completion."""
        details: dict[str, Any] = {"Model Type": model_type}
        if dataset_version:
            details["Dataset Version"] = dataset_version
        for k, v in metrics.items():
            details[k] = f"{v:.4f}" if isinstance(v, float) else str(v)
        self.log_change(
            agent_name=agent_name,
            change_type="training_run",
            description=f"Training run completed for {model_type}",
            details=details,
            run_id=run_id,
        )

    def get_recent_entries(self, limit: int = 20) -> list[dict[str, Any]]:
        """Read recent audit log entries."""
        if not self._audit_path.exists():
            return []
        entries = []
        try:
            with open(self._audit_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass
        return entries[-limit:]

    def audit_compliance(self, run_ids: list[str]) -> dict[str, Any]:
        """Check if all given run IDs have been documented."""
        entries = self.get_recent_entries(limit=500)
        documented_ids = {e.get("run_id") for e in entries if e.get("run_id")}

        missing = [rid for rid in run_ids if rid not in documented_ids]
        return {
            "total_runs": len(run_ids),
            "documented": len(run_ids) - len(missing),
            "missing": missing,
            "compliant": len(missing) == 0,
        }

    def _ensure_doc_exists(self) -> None:
        """Create the ML changelog if it doesn't exist."""
        if not self._doc_path.exists():
            self._doc_path.parent.mkdir(parents=True, exist_ok=True)
            self._doc_path.write_text(
                "# ML Changelog\n\n"
                "> Auto-generated log of all ML changes. Every agent MUST log here.\n"
                "> Do not edit manually — use `MLDocEnforcer.log_change()`.\n\n"
                "---\n"
            )
