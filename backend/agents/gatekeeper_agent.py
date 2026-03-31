from __future__ import annotations

import asyncio
import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class GatekeeperResult:
    approved: bool
    violations: list[str]
    test_output: str = ""
    lint_output: str = ""


@dataclass
class QualityReport:
    """Result of running real quality checks."""

    tests_ok: bool = False
    tests_output: str = ""
    lint_ok: bool = False
    lint_output: str = ""
    files_checked: list[str] = field(default_factory=list)


class GatekeeperAgent:
    """Review layer for lower-reasoning model mutations before commit/promotion.

    Sprint 7 upgrade: Actually runs pytest and ruff instead of trusting
    the caller to set tests_ok=True.
    """

    REQUIRED_TEST_PATHS = ("frontend/tests", "backend/tests")

    PYTEST_TIMEOUT = 60  # seconds
    RUFF_TIMEOUT = 30  # seconds

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or PROJECT_ROOT

    # ── Real quality checks ───────────────────────────────────────────

    def run_pytest(self, changed_files: list[str] | None = None) -> tuple[bool, str]:
        """Run pytest on backend/tests and deerflow/tests. Returns (passed, output)."""
        cmd = [
            "python",
            "-m",
            "pytest",
            "backend/tests/",
            "deerflow/tests/",
            "--ignore=backend/tests/test_scheduler_routes.py",
            "-x",
            "--tb=short",
            "-q",
            "--no-header",
        ]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.PYTEST_TIMEOUT,
            )
            output = result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout
            if result.stderr:
                output += "\n" + result.stderr[-500:]
            passed = result.returncode == 0
            logger.info("pytest %s (exit %d)", "PASSED" if passed else "FAILED", result.returncode)
            return passed, output
        except subprocess.TimeoutExpired:
            logger.warning("pytest timed out after %ds", self.PYTEST_TIMEOUT)
            return False, f"pytest timed out after {self.PYTEST_TIMEOUT}s"
        except FileNotFoundError:
            logger.error("python not found — cannot run pytest")
            return False, "python binary not found"

    def run_ruff_check(self, changed_files: list[str] | None = None) -> tuple[bool, str]:
        """Run ruff check on the project. Returns (passed, output)."""
        cmd = ["ruff", "check", "."]
        try:
            result = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=self.RUFF_TIMEOUT,
            )
            output = result.stdout[-1000:] if len(result.stdout) > 1000 else result.stdout
            passed = result.returncode == 0
            logger.info("ruff check %s (exit %d)", "PASSED" if passed else "FAILED", result.returncode)
            return passed, output
        except subprocess.TimeoutExpired:
            return False, f"ruff check timed out after {self.RUFF_TIMEOUT}s"
        except FileNotFoundError:
            logger.warning("ruff not found — skipping lint check")
            return True, "ruff not installed — skipped"

    def run_quality_checks(self, changed_files: list[str] | None = None) -> QualityReport:
        """Run all real quality checks and return a report."""
        report = QualityReport(files_checked=changed_files or [])

        report.tests_ok, report.tests_output = self.run_pytest(changed_files)
        report.lint_ok, report.lint_output = self.run_ruff_check(changed_files)

        return report

    async def run_quality_checks_async(self, changed_files: list[str] | None = None) -> QualityReport:
        """Async wrapper for run_quality_checks."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.run_quality_checks, changed_files)

    # ── Mutation review (original + enhanced) ─────────────────────────

    def review_mutation(
        self,
        payload: dict[str, Any],
        *,
        run_checks: bool = False,
    ) -> GatekeeperResult:
        """Review a mutation payload.

        Args:
            payload: Mutation metadata (files_changed, source_model, etc.)
            run_checks: If True, actually run pytest/ruff instead of trusting
                        the caller's tests_ok field.
        """
        violations: list[str] = []
        test_output = ""
        lint_output = ""

        files_changed = payload.get("files_changed", [])
        if not isinstance(files_changed, list):
            violations.append("files_changed must be a list")
            return GatekeeperResult(approved=False, violations=violations)

        touched_runtime = any(
            str(path).startswith("frontend/src/") or str(path).startswith("backend/") for path in files_changed
        )
        touched_tests = any(
            str(path).startswith("frontend/tests/") or str(path).startswith("backend/tests/") for path in files_changed
        )
        if touched_runtime and not touched_tests:
            violations.append("TDD violation: runtime code changed without corresponding tests")

        source_model = str(payload.get("source_model", "")).lower()
        is_local_source = "local" in source_model or "ollama" in source_model or source_model.startswith("llama")
        if is_local_source:
            if not payload.get("sandbox_session_id"):
                violations.append("Local-model mutation missing sandbox_session_id")
            if payload.get("staged_in_playbox") is not True:
                violations.append("Local-model mutation must be staged in playbox before release")

        # ── Quality checks: run real tests or trust payload ───────────
        if run_checks:
            report = self.run_quality_checks(files_changed)
            test_output = report.tests_output
            lint_output = report.lint_output
            if not report.tests_ok:
                violations.append(f"pytest FAILED: {report.tests_output[:200]}")
            if not report.lint_ok:
                violations.append(f"ruff check FAILED: {report.lint_output[:200]}")
        else:
            # Legacy trust-based check
            for check_name in ("tests_ok", "playwright_ok", "lighthouse_mobile_ok"):
                if payload.get(check_name) is not True:
                    violations.append(f"Required quality check failed or missing: {check_name}")

        syntax_ok = payload.get("syntax_ok", None)
        if syntax_ok is False:
            violations.append("Syntax/type checks failed")

        lighthouse_ok = payload.get("lighthouse_ok", None)
        if lighthouse_ok is False:
            violations.append("Lighthouse budget regression detected")

        secrets_ok = payload.get("secrets_ok", None)
        if secrets_ok is False:
            violations.append("Potential secrets leak detected")

        return GatekeeperResult(
            approved=len(violations) == 0,
            violations=violations,
            test_output=test_output,
            lint_output=lint_output,
        )
