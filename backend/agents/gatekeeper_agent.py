from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class GatekeeperResult:
    approved: bool
    violations: list[str]


class GatekeeperAgent:
    """Review layer for lower-reasoning model mutations before commit/promotion."""

    REQUIRED_TEST_PATHS = ("frontend/tests", "backend/tests")
    REQUIRED_QUALITY_CHECKS = ("tests_ok", "playwright_ok", "lighthouse_mobile_ok")

    def review_mutation(self, payload: dict[str, Any]) -> GatekeeperResult:
        violations: list[str] = []

        files_changed = payload.get("files_changed", [])
        if not isinstance(files_changed, list):
            violations.append("files_changed must be a list")
            return GatekeeperResult(approved=False, violations=violations)

        touched_runtime = any(
            str(path).startswith("frontend/src/") or str(path).startswith("backend/")
            for path in files_changed
        )
        touched_tests = any(
            str(path).startswith("frontend/tests/") or str(path).startswith("backend/tests/")
            for path in files_changed
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

        for check_name in self.REQUIRED_QUALITY_CHECKS:
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

        return GatekeeperResult(approved=len(violations) == 0, violations=violations)
