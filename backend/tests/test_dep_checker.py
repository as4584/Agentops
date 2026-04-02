"""Tests for backend.agents.dep_checker — dependency health monitoring."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest  # noqa: F401 — used by tmp_path fixture

from backend.agents.dep_checker import (
    check_consistency,
    check_cves,
    check_outdated,
    run_full_check,
)


class TestCheckCVEs:
    """CVE scanning via pip-audit wrapper."""

    def test_clean_scan(self):
        """No CVEs → status 'clean'."""
        mock_output = json.dumps({"dependencies": [{"name": "fastapi", "version": "0.111.0", "vulns": []}]})
        with patch("backend.agents.dep_checker._run_cmd", return_value=(0, mock_output)):
            result = check_cves()
        assert result["status"] == "clean"
        assert result["count"] == 0

    def test_vulnerable_package(self):
        """CVE found → status 'vulnerable' with details."""
        mock_output = json.dumps(
            {
                "dependencies": [
                    {
                        "name": "requests",
                        "version": "2.25.0",
                        "vulns": [{"id": "CVE-2023-32681", "fix_versions": ["2.31.0"]}],
                    }
                ]
            }
        )
        with patch("backend.agents.dep_checker._run_cmd", return_value=(0, mock_output)):
            result = check_cves()
        assert result["status"] == "vulnerable"
        assert result["count"] == 1
        assert result["vulnerabilities"][0]["package"] == "requests"

    def test_pip_audit_failure(self):
        """pip-audit exits non-zero → empty results, status 'clean'."""
        with patch("backend.agents.dep_checker._run_cmd", return_value=(1, "error")):
            result = check_cves()
        assert result["status"] == "clean"
        assert result["count"] == 0


class TestCheckOutdated:
    """Outdated package detection."""

    def test_all_up_to_date(self):
        with patch("backend.agents.dep_checker._run_cmd", return_value=(0, "[]")):
            result = check_outdated()
        assert result["status"] == "up_to_date"
        assert result["count"] == 0

    def test_outdated_found(self):
        mock_output = json.dumps(
            [
                {"name": "requests", "version": "2.25.0", "latest_version": "2.33.0", "latest_filetype": "wheel"},
            ]
        )
        with patch("backend.agents.dep_checker._run_cmd", return_value=(0, mock_output)):
            result = check_outdated()
        assert result["status"] == "updates_available"
        assert result["count"] == 1
        assert result["packages"][0]["latest"] == "2.33.0"

    def test_pip_failure(self):
        with patch("backend.agents.dep_checker._run_cmd", return_value=(1, "error")):
            result = check_outdated()
        assert result["status"] == "up_to_date"
        assert result["count"] == 0


class TestCheckConsistency:
    """pyproject.toml ↔ requirements.txt consistency."""

    def test_consistent(self):
        result = check_consistency()
        # Both files exist in the repo — should return a valid result
        assert result["check"] == "consistency"
        assert result["status"] in ("consistent", "inconsistent")

    def test_missing_pyproject(self, tmp_path: Path):
        with patch("backend.agents.dep_checker.PROJECT_ROOT", tmp_path):
            # No files exist at all
            result = check_consistency()
        assert result["status"] == "error"
        assert any("pyproject.toml" in i for i in result["issues"])


class TestRunFullCheck:
    """Full dependency audit integration."""

    def test_full_check_healthy(self, tmp_path: Path):
        """All checks pass → overall 'healthy'."""
        # Create the data dir for event logging
        (tmp_path / "data").mkdir()
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = [\n"fastapi>=0.111.0",\n]')
        (tmp_path / "requirements.txt").write_text("fastapi>=0.111.0\n")

        clean_cve = json.dumps({"dependencies": []})
        no_outdated = "[]"

        with (
            patch("backend.agents.dep_checker.PROJECT_ROOT", tmp_path),
            patch(
                "backend.agents.dep_checker._run_cmd",
                side_effect=[(0, clean_cve), (0, no_outdated)],
            ),
        ):
            report = run_full_check()

        assert report["overall_health"] == "healthy"
        assert report["checks"]["cves"]["status"] == "clean"
        assert report["checks"]["outdated"]["status"] == "up_to_date"
        assert report["checks"]["consistency"]["status"] == "consistent"

        # Verify event was logged
        events = (tmp_path / "data" / "shared_events.jsonl").read_text().strip()
        event = json.loads(events)
        assert event["event"] == "dep_check_completed"

    def test_full_check_attention_needed(self, tmp_path: Path):
        """CVE found → overall 'attention_needed'."""
        (tmp_path / "data").mkdir()
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = [\n"fastapi>=0.111.0",\n]')
        (tmp_path / "requirements.txt").write_text("fastapi>=0.111.0\n")

        vuln_cve = json.dumps(
            {"dependencies": [{"name": "pip", "version": "25.0", "vulns": [{"id": "CVE-2099-0001"}]}]}
        )

        with (
            patch("backend.agents.dep_checker.PROJECT_ROOT", tmp_path),
            patch(
                "backend.agents.dep_checker._run_cmd",
                side_effect=[(0, vuln_cve), (0, "[]")],
            ),
        ):
            report = run_full_check()

        assert report["overall_health"] == "attention_needed"
        assert report["checks"]["cves"]["count"] == 1
