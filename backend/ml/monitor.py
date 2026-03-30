"""
ML Monitor — Runtime monitoring for ML model health.
=====================================================
Tracks:
  - Response latency (flags slow inference)
  - Accuracy drift (compares recent predictions to expected)
  - Data drift (statistical shift in input feature distributions)
  - Feature drift (individual feature distribution changes)
  - Endpoint health (failed/error responses)

All alerts are persisted to a local JSONL log and surfaced via API.
"""

from __future__ import annotations

import json
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from backend.config import (
    ML_MONITORING_DIR,
    ML_ACCURACY_THRESHOLD,
    ML_LATENCY_THRESHOLD_MS,
    ML_DRIFT_THRESHOLD,
)
from backend.utils import logger


class MLAlert:
    """A monitoring alert."""

    def __init__(
        self,
        alert_type: str,
        severity: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        self.alert_type = alert_type
        self.severity = severity
        self.message = message
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()
        self.acknowledged = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


class MLMonitor:
    """Monitors ML model health across multiple dimensions."""

    def __init__(self, monitoring_dir: Optional[Path] = None) -> None:
        self._dir = monitoring_dir or ML_MONITORING_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._alerts_path = self._dir / "alerts.jsonl"
        self._metrics_path = self._dir / "metrics.jsonl"
        self._lock = RLock()

        # In-memory sliding windows for real-time monitoring
        self._latencies: deque[dict[str, Any]] = deque(maxlen=1000)
        self._predictions: deque[dict[str, Any]] = deque(maxlen=1000)
        self._feature_distributions: dict[str, list[float]] = {}
        self._baseline_distributions: dict[str, dict[str, float]] = {}
        self._endpoint_results: deque[dict[str, Any]] = deque(maxlen=500)
        self._alerts: list[MLAlert] = []

        self._load_baseline()

    # ── Recording ────────────────────────────────────────

    def record_latency(self, endpoint: str, latency_ms: float, model_name: str = "") -> None:
        """Record an inference latency measurement."""
        entry = {
            "endpoint": endpoint,
            "model_name": model_name,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._latencies.append(entry)
            self._append_metric("latency", entry)

        if latency_ms > ML_LATENCY_THRESHOLD_MS:
            self._raise_alert(
                alert_type="slow_response",
                severity="warning",
                message=f"Slow response on {endpoint}: {latency_ms:.0f}ms (threshold: {ML_LATENCY_THRESHOLD_MS}ms)",
                details=entry,
            )

    def record_prediction(
        self,
        model_name: str,
        predicted: Any,
        actual: Optional[Any] = None,
        confidence: Optional[float] = None,
    ) -> None:
        """Record a prediction for accuracy tracking."""
        entry: dict[str, Any] = {
            "model_name": model_name,
            "predicted": predicted,
            "actual": actual,
            "confidence": confidence,
            "correct": predicted == actual if actual is not None else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._predictions.append(entry)
            self._append_metric("prediction", entry)

    def record_features(self, model_name: str, features: dict[str, float]) -> None:
        """Record input features for drift detection."""
        with self._lock:
            for name, value in features.items():
                key = f"{model_name}:{name}"
                if key not in self._feature_distributions:
                    self._feature_distributions[key] = []
                self._feature_distributions[key].append(value)

    def record_endpoint_result(
        self, endpoint: str, status_code: int, error: Optional[str] = None
    ) -> None:
        """Record an endpoint call result."""
        entry = {
            "endpoint": endpoint,
            "status_code": status_code,
            "error": error,
            "success": 200 <= status_code < 400,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._endpoint_results.append(entry)
            self._append_metric("endpoint", entry)

        if not entry["success"]:
            self._raise_alert(
                alert_type="endpoint_failure",
                severity="error",
                message=f"Endpoint {endpoint} returned {status_code}: {error or 'unknown'}",
                details=entry,
            )

    def set_baseline(self, model_name: str, features: dict[str, dict[str, float]]) -> None:
        """Set baseline feature distributions for drift comparison.

        features: {"feature_name": {"mean": 0.5, "std": 0.1}}
        """
        with self._lock:
            for fname, stats in features.items():
                key = f"{model_name}:{fname}"
                self._baseline_distributions[key] = stats
            self._save_baseline()

    # ── Analysis ─────────────────────────────────────────

    def check_accuracy(self, model_name: str, window: int = 100) -> dict[str, Any]:
        """Check recent accuracy for a model within a sliding window."""
        with self._lock:
            recent = [
                p for p in self._predictions
                if p["model_name"] == model_name and p["correct"] is not None
            ][-window:]

        if not recent:
            return {"model_name": model_name, "accuracy": None, "sample_size": 0, "alert": False}

        correct = sum(1 for p in recent if p["correct"])
        accuracy = correct / len(recent)

        alert = accuracy < ML_ACCURACY_THRESHOLD
        if alert:
            self._raise_alert(
                alert_type="accuracy_drop",
                severity="critical",
                message=(
                    f"Accuracy for {model_name} dropped to {accuracy:.2%} "
                    f"(threshold: {ML_ACCURACY_THRESHOLD:.2%}, window: {len(recent)})"
                ),
                details={"accuracy": accuracy, "sample_size": len(recent)},
            )

        return {
            "model_name": model_name,
            "accuracy": accuracy,
            "sample_size": len(recent),
            "alert": alert,
        }

    def check_data_drift(self, model_name: str) -> list[dict[str, Any]]:
        """Check for data drift by comparing current vs baseline distributions."""
        drift_results = []
        with self._lock:
            for key, values in self._feature_distributions.items():
                if not key.startswith(f"{model_name}:"):
                    continue
                feature_name = key.split(":", 1)[1]
                baseline = self._baseline_distributions.get(key)
                if not baseline or len(values) < 10:
                    continue

                current_mean = sum(values) / len(values)
                current_std = _std(values)
                baseline_mean = baseline.get("mean", 0)
                baseline_std = baseline.get("std", 1)

                # Normalized mean shift (z-score style)
                if baseline_std > 0:
                    shift = abs(current_mean - baseline_mean) / baseline_std
                else:
                    shift = abs(current_mean - baseline_mean)

                drifted = shift > (ML_DRIFT_THRESHOLD * 10)  # scale to z-score

                result = {
                    "feature": feature_name,
                    "baseline_mean": baseline_mean,
                    "baseline_std": baseline_std,
                    "current_mean": current_mean,
                    "current_std": current_std,
                    "shift": shift,
                    "drifted": drifted,
                }
                drift_results.append(result)

                if drifted:
                    self._raise_alert(
                        alert_type="data_drift",
                        severity="warning",
                        message=f"Data drift detected in {model_name}:{feature_name} — shift={shift:.3f}",
                        details=result,
                    )

        return drift_results

    def check_latency(self, endpoint: Optional[str] = None, window: int = 100) -> dict[str, Any]:
        """Check recent latency stats."""
        with self._lock:
            recent = list(self._latencies)[-window:]
        if endpoint:
            recent = [l for l in recent if l["endpoint"] == endpoint]

        if not recent:
            return {"p50": 0, "p95": 0, "p99": 0, "count": 0, "alert": False}

        latencies = sorted(l["latency_ms"] for l in recent)
        count = len(latencies)

        return {
            "p50": latencies[int(count * 0.5)] if count else 0,
            "p95": latencies[int(count * 0.95)] if count else 0,
            "p99": latencies[int(count * 0.99)] if count else 0,
            "count": count,
            "mean": sum(latencies) / count if count else 0,
            "alert": latencies[int(count * 0.95)] > ML_LATENCY_THRESHOLD_MS if count else False,
        }

    def check_endpoints(self, window: int = 100) -> dict[str, Any]:
        """Check recent endpoint health."""
        with self._lock:
            recent = list(self._endpoint_results)[-window:]

        if not recent:
            return {"total": 0, "success": 0, "failure": 0, "error_rate": 0, "failing": []}

        success = sum(1 for r in recent if r["success"])
        failures = [r for r in recent if not r["success"]]
        failing_endpoints = list({r["endpoint"] for r in failures})

        return {
            "total": len(recent),
            "success": success,
            "failure": len(failures),
            "error_rate": len(failures) / len(recent),
            "failing": failing_endpoints,
        }

    def get_health_report(self, model_name: str = "") -> dict[str, Any]:
        """Full health report across all monitoring dimensions."""
        report: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "latency": self.check_latency(),
            "endpoints": self.check_endpoints(),
            "alerts": self.get_alerts(limit=20),
        }
        if model_name:
            report["accuracy"] = self.check_accuracy(model_name)
            report["drift"] = self.check_data_drift(model_name)
        return report

    def get_alerts(
        self,
        alert_type: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get recent alerts, optionally filtered."""
        with self._lock:
            alerts = list(self._alerts)
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        return [a.to_dict() for a in alerts[-limit:]]

    def acknowledge_alerts(self, alert_type: Optional[str] = None) -> int:
        """Mark alerts as acknowledged. Returns count acknowledged."""
        count = 0
        with self._lock:
            for alert in self._alerts:
                if alert_type and alert.alert_type != alert_type:
                    continue
                if not alert.acknowledged:
                    alert.acknowledged = True
                    count += 1
        return count

    # ── Internals ────────────────────────────────────────

    def _raise_alert(
        self, alert_type: str, severity: str, message: str, details: dict[str, Any]
    ) -> None:
        alert = MLAlert(alert_type, severity, message, details)
        with self._lock:
            self._alerts.append(alert)
            # Keep only last 500 alerts in memory
            if len(self._alerts) > 500:
                self._alerts = self._alerts[-500:]
        self._append_to_file(self._alerts_path, alert.to_dict())
        level = "error" if severity == "critical" else "warning"
        getattr(logger, level)(f"[MLMonitor] {message}")

    def _append_metric(self, category: str, data: dict[str, Any]) -> None:
        record = {"category": category, **data}
        self._append_to_file(self._metrics_path, record)

    def _append_to_file(self, path: Path, data: dict[str, Any]) -> None:
        try:
            with open(path, "a") as f:
                f.write(json.dumps(data) + "\n")
        except OSError as e:
            logger.warning(f"[MLMonitor] Failed to write to {path}: {e}")

    def _save_baseline(self) -> None:
        path = self._dir / "baseline.json"
        path.write_text(json.dumps(self._baseline_distributions, indent=2))

    def _load_baseline(self) -> None:
        path = self._dir / "baseline.json"
        if path.exists():
            try:
                self._baseline_distributions = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                pass


def _std(values: list[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)
