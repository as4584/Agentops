from unittest.mock import patch

from backend.agents.gatekeeper_agent import GatekeeperAgent


def test_gatekeeper_rejects_runtime_without_tests():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["frontend/src/app/page.tsx"],
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is False
    assert any("TDD violation" in item for item in result.violations)


def test_gatekeeper_rejects_local_without_sandbox_and_playbox():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["backend/orchestrator/__init__.py", "backend/tests/test_orchestrator.py"],
            "source_model": "local",
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is False
    assert any("sandbox_session_id" in item for item in result.violations)
    assert any("playbox" in item for item in result.violations)


def test_gatekeeper_approves_local_when_all_checks_pass():
    gatekeeper = GatekeeperAgent()
    result = gatekeeper.review_mutation(
        {
            "files_changed": ["backend/orchestrator/__init__.py", "backend/tests/test_orchestrator.py"],
            "source_model": "local",
            "sandbox_session_id": "session-1234",
            "staged_in_playbox": True,
            "tests_ok": True,
            "playwright_ok": True,
            "lighthouse_mobile_ok": True,
            "syntax_ok": True,
            "secrets_ok": True,
            "lighthouse_ok": True,
        }
    )
    assert result.approved is True
    assert result.violations == []


# ── Sprint 7: Real test execution ─────────────────────────────────────


class TestGatekeeperRealChecks:
    """Tests for the Gatekeeper's ability to actually run pytest and ruff."""

    def test_run_pytest_success(self):
        gk = GatekeeperAgent()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "783 passed in 12.00s"
            mock_run.return_value.stderr = ""
            passed, output = gk.run_pytest()
            assert passed is True
            assert "783 passed" in output
            mock_run.assert_called_once()

    def test_run_pytest_failure(self):
        gk = GatekeeperAgent()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = "FAILED test_foo.py::test_bar"
            mock_run.return_value.stderr = ""
            passed, output = gk.run_pytest()
            assert passed is False
            assert "FAILED" in output

    def test_run_pytest_timeout(self):
        import subprocess as sp

        gk = GatekeeperAgent()
        with patch("subprocess.run", side_effect=sp.TimeoutExpired("pytest", 60)):
            passed, output = gk.run_pytest()
            assert passed is False
            assert "timed out" in output

    def test_run_ruff_check_success(self):
        gk = GatekeeperAgent()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "All checks passed!"
            passed, output = gk.run_ruff_check()
            assert passed is True

    def test_run_ruff_check_failure(self):
        gk = GatekeeperAgent()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stdout = "Found 5 errors."
            passed, output = gk.run_ruff_check()
            assert passed is False

    def test_run_quality_checks_returns_report(self):
        gk = GatekeeperAgent()
        with patch.object(gk, "run_pytest", return_value=(True, "all pass")):
            with patch.object(gk, "run_ruff_check", return_value=(True, "clean")):
                report = gk.run_quality_checks(["backend/foo.py"])
                assert report.tests_ok is True
                assert report.lint_ok is True
                assert report.files_checked == ["backend/foo.py"]

    def test_review_mutation_with_run_checks_passes(self):
        gk = GatekeeperAgent()
        with patch.object(gk, "run_quality_checks") as mock_qc:
            from backend.agents.gatekeeper_agent import QualityReport

            mock_qc.return_value = QualityReport(
                tests_ok=True,
                tests_output="783 passed",
                lint_ok=True,
                lint_output="All checks passed!",
            )
            result = gk.review_mutation(
                {
                    "files_changed": [
                        "backend/routes/health.py",
                        "backend/tests/test_health.py",
                    ],
                },
                run_checks=True,
            )
            assert result.approved is True
            assert result.violations == []
            mock_qc.assert_called_once()

    def test_review_mutation_with_run_checks_fails_on_test_failure(self):
        gk = GatekeeperAgent()
        with patch.object(gk, "run_quality_checks") as mock_qc:
            from backend.agents.gatekeeper_agent import QualityReport

            mock_qc.return_value = QualityReport(
                tests_ok=False,
                tests_output="FAILED test_foo.py",
                lint_ok=True,
                lint_output="clean",
            )
            result = gk.review_mutation(
                {
                    "files_changed": [
                        "backend/routes/health.py",
                        "backend/tests/test_health.py",
                    ],
                },
                run_checks=True,
            )
            assert result.approved is False
            assert any("pytest FAILED" in v for v in result.violations)
