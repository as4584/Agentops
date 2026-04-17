#!/usr/bin/env python3
"""
Classify pytest failures by type before blocking a PR.

Failure classes
---------------
regression   — was passing, now failing — BLOCK merge
new_coverage — new test, first run — WARN only
flaky        — non-deterministic pattern detected — flag for LLM judge
drift        — architecture contract broken — BLOCK merge
deprecation  — DeprecationWarning or RuntimeWarning — schedule cleanup sprint

Usage
-----
    python scripts/classify_failures.py \\
        [--input  reports/eval_results.json] \\
        [--junit  reports/junit.xml] \\
        [--output reports/failure_classes.json] \\
        [--exit-nonzero-on BLOCKING_CLASS,...]

Exit codes
----------
0  — no blocking failures (or no failures at all)
1  — one or more blocking failures found
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Failure class definitions
# ---------------------------------------------------------------------------

FAILURE_CLASSES: dict[str, str] = {
    "regression": "was passing, now failing — BLOCK merge",
    "new_coverage": "new test, first run — WARN only",
    "flaky": "non-deterministic — flag for LLM judge",
    "drift": "architecture contract broken — BLOCK merge",
    "deprecation": "warning only — schedule cleanup sprint",
    "unknown": "unclassified failure — manual triage required",
}

# Classes that must block a merge when present
BLOCKING_CLASSES: frozenset[str] = frozenset({"regression", "drift"})

# ---------------------------------------------------------------------------
# Classification heuristics
# ---------------------------------------------------------------------------

# Patterns that suggest architecture/drift failures
_DRIFT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(registry.router|router.registry|parity)", re.I),
    re.compile(r"(architecture|invariant|INV-\d)", re.I),
    re.compile(r"(drift|DriftGuard)", re.I),
    re.compile(r"(namespace.overlap|ARCHITECTURAL_MODIFY)", re.I),
]

# Patterns that suggest flakiness
_FLAKY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(timeout|timed out|connection refused|temporarily unavailable)", re.I),
    re.compile(r"(asyncio|event loop|RuntimeWarning.*coroutine)", re.I),
    re.compile(r"(random|nondeterministic|order.dependent)", re.I),
]

# Patterns that suggest deprecation warnings elevated to errors
_DEPRECATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"DeprecationWarning", re.I),
    re.compile(r"RuntimeWarning", re.I),
    re.compile(r"PytestUnraisableExceptionWarning", re.I),
]

# Test name patterns that indicate a brand-new test (first run)
_NEW_TEST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"test_(new|add|sprint\d+|feature)", re.I),
]


def _classify_single(test_name: str, message: str) -> str:
    """Return the class string for one failure entry."""
    combined = f"{test_name} {message}"

    for pat in _DEPRECATION_PATTERNS:
        if pat.search(combined):
            return "deprecation"

    for pat in _DRIFT_PATTERNS:
        if pat.search(combined):
            return "drift"

    for pat in _FLAKY_PATTERNS:
        if pat.search(combined):
            return "flaky"

    for pat in _NEW_TEST_PATTERNS:
        if pat.search(test_name):
            return "new_coverage"

    # Default: treat unknown failures as regression (conservative)
    return "regression"


# ---------------------------------------------------------------------------
# Input parsers
# ---------------------------------------------------------------------------


def _parse_junit(path: Path) -> list[dict[str, str]]:
    """Extract failures from a JUnit XML file (pytest --junit-xml output)."""
    failures: list[dict[str, str]] = []
    try:
        tree = ET.parse(path)  # noqa: S314 — trusted local file
    except ET.ParseError:
        return failures

    for testcase in tree.iter("testcase"):
        for child in testcase:
            if child.tag in ("failure", "error"):
                failures.append(
                    {
                        "name": testcase.get("classname", "") + "::" + testcase.get("name", ""),
                        "message": child.get("message", "") + (child.text or ""),
                    }
                )
    return failures


def _parse_eval_results(path: Path) -> list[dict[str, str]]:
    """Extract failures from an eval_results.json produced by eval_expanded.py."""
    failures: list[dict[str, str]] = []
    try:
        data: Any = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return failures

    items = data.get("results", data) if isinstance(data, dict) else data
    if not isinstance(items, list):
        return failures

    for item in items:
        if isinstance(item, dict) and not item.get("passed", True):
            failures.append(
                {
                    "name": str(item.get("test_id", item.get("name", "unknown")) or "unknown"),
                    "message": str(item.get("error", item.get("reason", "")) or ""),
                }
            )
    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def classify(failures: list[dict[str, str]]) -> dict[str, list[str]]:
    """Return a mapping of class → [test_name, ...] for all failures."""
    result: dict[str, list[str]] = {cls: [] for cls in FAILURE_CLASSES}
    for f in failures:
        cls = _classify_single(f.get("name", ""), f.get("message", ""))
        result[cls].append(f["name"])
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default=None, help="Path to eval_results.json")
    parser.add_argument("--junit", default=None, help="Path to JUnit XML (pytest --junit-xml)")
    parser.add_argument("--output", default=None, help="Write classified results to this JSON file")
    parser.add_argument(
        "--exit-nonzero-on",
        default=",".join(BLOCKING_CLASSES),
        help="Comma-separated list of classes that cause a non-zero exit (default: regression,drift)",
    )
    args = parser.parse_args(argv)

    blocking_on = frozenset(c.strip() for c in args.exit_nonzero_on.split(",") if c.strip())

    raw: list[dict[str, str]] = []
    if args.input:
        p = Path(args.input)
        if p.exists():
            raw.extend(_parse_eval_results(p))
    if args.junit:
        p = Path(args.junit)
        if p.exists():
            raw.extend(_parse_junit(p))

    if not raw:
        print("No failures to classify.")
        return 0

    classified = classify(raw)

    # ── Console report ──────────────────────────────────────────────────
    print(f"\n{'─' * 56}")
    print("  Failure Classification Report")
    print(f"{'─' * 56}")
    total = sum(len(v) for v in classified.values())
    for cls, items in classified.items():
        if not items:
            continue
        tag = "BLOCK" if cls in BLOCKING_CLASSES else "WARN "
        print(f"  [{tag}] {cls.upper()}: {len(items)} — {FAILURE_CLASSES[cls]}")
        for name in items[:5]:
            print(f"         • {name}")
        if len(items) > 5:
            print(f"         … and {len(items) - 5} more")
    print(f"{'─' * 56}")
    print(f"  Total failures: {total}")
    print(f"{'─' * 56}\n")

    # ── Write output JSON ───────────────────────────────────────────────
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        blocking_count = sum(len(classified[c]) for c in blocking_on if c in classified)
        out_path.write_text(
            json.dumps(
                {
                    "total": total,
                    "blocking": blocking_count,
                    "has_blocking": blocking_count > 0,
                    # alias used by auto_repair.yml
                    "failure_classes": classified,
                    # legacy key — kept for backwards compatibility
                    "classes": classified,
                    "descriptions": FAILURE_CLASSES,
                },
                indent=2,
            )
        )

    # ── Exit code ───────────────────────────────────────────────────────
    for cls in blocking_on:
        if classified.get(cls):
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
