"""
Tests for ML Monitor — latency, accuracy, drift, endpoint health, alerts.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.ml.monitor import MLMonitor, _std


@pytest.fixture
def monitor(tmp_path: Path) -> MLMonitor:
    return MLMonitor(monitoring_dir=tmp_path / "monitoring")


class TestMLMonitor:
    # ── Latency ──────────────────────────────────────

    def test_record_latency_normal(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/chat", 150.0, "llama3.2")
        stats = monitor.check_latency()
        assert stats["count"] == 1
        assert stats["mean"] == 150.0

    def test_record_latency_triggers_alert(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/chat", 5000.0, "llama3.2")
        alerts = monitor.get_alerts(alert_type="slow_response")
        assert len(alerts) == 1
        assert "5000" in alerts[0]["message"]

    def test_latency_percentiles(self, monitor: MLMonitor) -> None:
        for i in range(100):
            monitor.record_latency("/chat", float(i * 10), "model")
        stats = monitor.check_latency()
        assert stats["p50"] > 0
        assert stats["p95"] > stats["p50"]
        assert stats["count"] == 100

    def test_latency_filter_by_endpoint(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/chat", 100.0)
        monitor.record_latency("/predict", 200.0)
        stats = monitor.check_latency(endpoint="/predict")
        assert stats["count"] == 1
        assert stats["mean"] == 200.0

    # ── Accuracy ─────────────────────────────────────

    def test_record_prediction_accuracy(self, monitor: MLMonitor) -> None:
        for _ in range(80):
            monitor.record_prediction("model_a", "positive", "positive")
        for _ in range(20):
            monitor.record_prediction("model_a", "positive", "negative")

        result = monitor.check_accuracy("model_a")
        assert result["accuracy"] == 0.8
        assert result["sample_size"] == 100

    def test_accuracy_below_threshold_triggers_alert(self, monitor: MLMonitor) -> None:
        # Default threshold is 0.85
        for _ in range(50):
            monitor.record_prediction("bad_model", "a", "a")
        for _ in range(50):
            monitor.record_prediction("bad_model", "a", "b")  # 50% accuracy

        result = monitor.check_accuracy("bad_model")
        assert result["alert"] is True
        alerts = monitor.get_alerts(alert_type="accuracy_drop")
        assert len(alerts) >= 1

    def test_accuracy_no_data(self, monitor: MLMonitor) -> None:
        result = monitor.check_accuracy("nonexistent")
        assert result["accuracy"] is None
        assert result["sample_size"] == 0

    # ── Data Drift ───────────────────────────────────

    def test_set_baseline_and_no_drift(self, monitor: MLMonitor) -> None:
        monitor.set_baseline("model_x", {
            "feature_a": {"mean": 0.5, "std": 0.1},
        })
        for _ in range(20):
            monitor.record_features("model_x", {"feature_a": 0.51})

        results = monitor.check_data_drift("model_x")
        assert len(results) == 1
        assert results[0]["drifted"] is False

    def test_data_drift_detected(self, monitor: MLMonitor) -> None:
        monitor.set_baseline("model_y", {
            "feature_b": {"mean": 0.5, "std": 0.1},
        })
        # Far from baseline
        for _ in range(20):
            monitor.record_features("model_y", {"feature_b": 5.0})

        results = monitor.check_data_drift("model_y")
        assert len(results) == 1
        assert results[0]["drifted"] is True

    def test_drift_no_baseline(self, monitor: MLMonitor) -> None:
        for _ in range(20):
            monitor.record_features("no_baseline", {"feat": 1.0})
        results = monitor.check_data_drift("no_baseline")
        assert len(results) == 0  # no baseline, can't compare

    # ── Endpoint Health ──────────────────────────────

    def test_record_success(self, monitor: MLMonitor) -> None:
        monitor.record_endpoint_result("/chat", 200)
        health = monitor.check_endpoints()
        assert health["total"] == 1
        assert health["success"] == 1
        assert health["failure"] == 0

    def test_record_failure_triggers_alert(self, monitor: MLMonitor) -> None:
        monitor.record_endpoint_result("/chat", 500, error="Internal Server Error")
        alerts = monitor.get_alerts(alert_type="endpoint_failure")
        assert len(alerts) == 1
        health = monitor.check_endpoints()
        assert health["failure"] == 1
        assert "/chat" in health["failing"]

    def test_mixed_endpoint_results(self, monitor: MLMonitor) -> None:
        for _ in range(90):
            monitor.record_endpoint_result("/chat", 200)
        for _ in range(10):
            monitor.record_endpoint_result("/chat", 503)

        health = monitor.check_endpoints()
        assert health["error_rate"] == 0.1

    # ── Alerts ───────────────────────────────────────

    def test_acknowledge_alerts(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/slow", 9999.0)
        count = monitor.acknowledge_alerts(alert_type="slow_response")
        assert count == 1
        alerts = monitor.get_alerts()
        assert all(a["acknowledged"] for a in alerts)

    def test_alerts_filter_by_severity(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/slow", 9999.0)  # warning
        monitor.record_endpoint_result("/fail", 500)  # error

        warnings = monitor.get_alerts(severity="warning")
        errors = monitor.get_alerts(severity="error")
        assert len(warnings) >= 1
        assert len(errors) >= 1

    # ── Health Report ────────────────────────────────

    def test_full_health_report(self, monitor: MLMonitor) -> None:
        monitor.record_latency("/chat", 100.0)
        monitor.record_endpoint_result("/chat", 200)
        report = monitor.get_health_report()
        assert "latency" in report
        assert "endpoints" in report
        assert "alerts" in report

    def test_health_report_with_model(self, monitor: MLMonitor) -> None:
        monitor.record_prediction("test_model", "a", "a")
        report = monitor.get_health_report(model_name="test_model")
        assert "accuracy" in report
        assert "drift" in report

    # ── Empty state ──────────────────────────────────

    def test_check_latency_empty(self, monitor: MLMonitor) -> None:
        stats = monitor.check_latency()
        assert stats["count"] == 0

    def test_check_endpoints_empty(self, monitor: MLMonitor) -> None:
        health = monitor.check_endpoints()
        assert health["total"] == 0


class TestStdHelper:
    def test_std_empty(self) -> None:
        assert _std([]) == 0.0

    def test_std_single(self) -> None:
        assert _std([5.0]) == 0.0

    def test_std_known(self) -> None:
        # std of [2, 4, 4, 4, 5, 5, 7, 9] = 2.0
        result = _std([2, 4, 4, 4, 5, 5, 7, 9])
        assert abs(result - 2.0) < 0.01
