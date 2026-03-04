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
