#!/usr/bin/env python3
"""Smart test runner — only test what changed.

Maps changed source files to their relevant test modules and runs only those.
Use --full for pre-merge CI (runs entire suite).

Usage:
    python scripts/smart_test.py              # run tests for changed files
    python scripts/smart_test.py --full       # run all tests (CI / pre-merge)
    python scripts/smart_test.py --diff main  # compare against a specific branch
    python scripts/smart_test.py --dry-run    # show what would run without executing
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ── Source → Test mapping ────────────────────────────────────────────
# Explicit mappings for files that have dedicated tests.
# Wildcard entries (ending in /) match any file under that directory.

_EXPLICIT_MAP: dict[str, list[str]] = {
    # Agents
    "backend/agents/__init__.py": [
        "backend/tests/test_agent_definitions.py",
        "backend/tests/test_agent_factory.py",
        "backend/tests/test_ocr_agent.py",
    ],
    # Orchestrator
    "backend/orchestrator/lex_router.py": ["backend/tests/test_lex_router.py"],
    "backend/orchestrator/openclaw_bridge.py": ["backend/tests/test_openclaw.py"],
    # ML
    "backend/ml/preprocessor.py": ["backend/tests/test_preprocessor.py"],
    "backend/ml/training_generator.py": ["backend/tests/test_training_generator.py"],
    "backend/ml/eval_framework.py": ["backend/tests/test_eval_framework.py"],
    "backend/ml/experiment_tracker.py": ["backend/tests/test_experiment_tracker.py"],
    "backend/ml/learning_lab.py": ["backend/tests/test_learning_lab.py"],
    # Config / core
    "backend/config.py": ["backend/tests/test_config.py"],
    "backend/security_middleware.py": ["backend/tests/test_security_middleware.py"],
    "app.py": ["backend/tests/test_app_startup.py"],
    # Gateway
    "backend/gateway/": ["backend/tests/test_gateway.py", "backend/tests/test_gateway_integration.py"],
    # Tools
    "backend/tools/": ["backend/tests/test_tools.py", "backend/tests/test_safe_shell.py"],
    # Skills
    "backend/skills/": ["backend/tests/test_skills.py"],
    # Knowledge
    "backend/knowledge/": ["backend/tests/test_knowledge_store.py"],
    # OCR
    "backend/ocr/": ["backend/tests/test_ocr_agent.py"],
    # Memory
    "backend/memory/": ["backend/tests/test_memory_store.py"],
    # Models
    "backend/models/": ["backend/tests/test_models.py"],
    # Browser
    "backend/browser/": ["backend/tests/test_browser.py"],
    # Middleware
    "backend/middleware/": ["backend/tests/test_drift_guard.py"],
    # Content pipeline
    "backend/content/": ["backend/tests/test_content_pipeline.py"],
    # WebGen
    "backend/webgen/": ["backend/tests/test_webgen.py"],
    # Database
    "backend/database/": ["backend/tests/test_database.py"],
    # LLM
    "backend/llm/": ["backend/tests/test_llm.py", "backend/tests/test_ollama.py"],
    # Routes
    "backend/routes/": ["backend/tests/test_routes.py"],
    # DeerFlow
    "deerflow/": ["deerflow/tests/"],
}


def _get_changed_files(diff_base: str = "HEAD") -> list[str]:
    """Get files changed relative to diff_base using git."""
    try:
        # Staged + unstaged changes
        result = subprocess.run(
            ["git", "diff", "--name-only", diff_base],
            capture_output=True, text=True, cwd=ROOT, check=True,
        )
        files = set(result.stdout.strip().split("\n")) if result.stdout.strip() else set()

        # Also include staged files
        result2 = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],
            capture_output=True, text=True, cwd=ROOT, check=True,
        )
        if result2.stdout.strip():
            files.update(result2.stdout.strip().split("\n"))

        # Also include untracked new files
        result3 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, cwd=ROOT, check=True,
        )
        if result3.stdout.strip():
            files.update(result3.stdout.strip().split("\n"))

        return sorted(f for f in files if f)
    except subprocess.CalledProcessError:
        print("Warning: git diff failed, running full suite", file=sys.stderr)
        return []


def _map_to_tests(changed_files: list[str]) -> set[str]:
    """Map changed source files to test files/directories."""
    tests: set[str] = set()

    for changed in changed_files:
        # If a test file itself changed, include it directly
        if "test" in changed and changed.endswith(".py"):
            tests.add(changed)
            continue

        # Check exact matches first
        if changed in _EXPLICIT_MAP:
            for t in _EXPLICIT_MAP[changed]:
                tests.add(t)
            continue

        # Check directory prefix matches
        matched = False
        for prefix, test_targets in _EXPLICIT_MAP.items():
            if prefix.endswith("/") and changed.startswith(prefix):
                for t in test_targets:
                    tests.add(t)
                matched = True
                break

        if matched:
            continue

        # Convention-based fallback: backend/foo/bar.py → backend/tests/test_bar.py
        path = Path(changed)
        if path.suffix == ".py" and path.stem != "__init__":
            candidate = f"backend/tests/test_{path.stem}.py"
            if (ROOT / candidate).exists():
                tests.add(candidate)

    return tests


def _filter_existing(tests: set[str]) -> list[str]:
    """Only keep test paths that actually exist."""
    existing = []
    for t in sorted(tests):
        full = ROOT / t
        if full.exists():
            existing.append(t)
    return existing


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart test runner — only test what changed.")
    parser.add_argument("--full", action="store_true", help="Run the full test suite (CI / pre-merge)")
    parser.add_argument("--diff", default="HEAD", help="Git ref to diff against (default: HEAD)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output")
    args = parser.parse_args()

    if args.full:
        print("Running full test suite (--full)")
        cmd = ["python", "-m", "pytest", "backend/tests/", "deerflow/tests/", "-x", "--tb=short", "-q"]
        if args.verbose:
            cmd.append("-v")
        if args.dry_run:
            print(f"  Would run: {' '.join(cmd)}")
            return
        sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)

    changed = _get_changed_files(args.diff)
    if not changed:
        print("No changes detected — nothing to test.")
        return

    print(f"Changed files ({len(changed)}):")
    for f in changed:
        print(f"  {f}")

    tests = _map_to_tests(changed)
    existing = _filter_existing(tests)

    if not existing:
        print("\nNo matching test files found for changed files.")
        return

    print(f"\nTest targets ({len(existing)}):")
    for t in existing:
        print(f"  {t}")

    if args.dry_run:
        print("\n[dry-run] Would run the above tests.")
        return

    cmd = ["python", "-m", "pytest"] + existing + ["-x", "--tb=short", "-q"]
    if args.verbose:
        cmd.append("-v")

    print(f"\nRunning: {' '.join(cmd)}\n")
    sys.exit(subprocess.run(cmd, cwd=ROOT).returncode)


if __name__ == "__main__":
    main()
