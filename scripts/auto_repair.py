#!/usr/bin/env python3
"""
Auto-repair runner for CI failures.

Reads a failure classification report produced by classify_failures.py and
applies deterministic, safe mechanical fixes for known repairable failure
classes.  Writes a repair result JSON and exits 0 on success or 1 when the
failure is not auto-repairable (so the caller can open a human-review issue).

Repair rules (safe = never changes logic, only formatting/ordering)
-------------------------------------------------------------------
ruff_format     → ruff format .
ruff_lint       → ruff check . --fix --select E,F,I,UP,N,B,RUF
import_order    → ruff check . --fix --select I
missing_newline → ruff format .

Everything else is considered non-repairable by this script and is left
for a human.  TypeError / AssertionError / ImportError failures are
explicitly blocked from auto-repair because they require judgment.

Usage
-----
    python scripts/auto_repair.py \\
        --report reports/failure_classes.json \\
        --branch dev \\
        [--output reports/repair_result.json] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repair catalogue
# ---------------------------------------------------------------------------

# Maps failure class → shell command that fixes it deterministically.
# Only include commands that are safe to run without human review.
_SAFE_REPAIRS: dict[str, list[str]] = {
    "ruff_format": ["ruff", "format", "."],
    "ruff_lint": ["ruff", "check", ".", "--fix", "--select", "E,F,I,UP,N,B,RUF"],
    "import_order": ["ruff", "check", ".", "--fix", "--select", "I"],
    "missing_newline": ["ruff", "format", "."],
    "deprecation": [
        "python",
        "scripts/scan_deprecations.py",
        "--fix",
        "--severity",
        "warning",
    ],
}

# Failure classes that must NEVER be auto-repaired (need human judgment).
_HUMAN_ONLY: frozenset[str] = frozenset(
    {
        "regression",
        "drift",
        "unknown",
        "test_logic",
        "type_error",
        "import_error",
        "silent_fail",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd: list[str], *, dry_run: bool = False) -> tuple[int, str]:
    """Run *cmd* and return (returncode, combined stdout+stderr)."""
    if dry_run:
        print(f"  [dry-run] would run: {' '.join(cmd)}")
        return 0, ""
    result = subprocess.run(  # noqa: S603
        cmd,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout + result.stderr


def _load_report(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(f"ERROR: Cannot read report at {path}: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Core repair logic
# ---------------------------------------------------------------------------


def repair(report: dict, *, dry_run: bool = False) -> dict:
    """
    Attempt to repair all repairable failure classes in *report*.

    Returns a result dict with keys:
        repaired: bool
        applied_fixes: list[str]
        skipped: list[str]
        reason: str
    """
    # Support both key names from classify_failures.py
    classes: dict[str, list[str]] = report.get("failure_classes") or report.get("classes") or {}

    applied: list[str] = []
    skipped: list[str] = []

    # Check for any human-only failures first.
    blocking_human = [cls for cls in _HUMAN_ONLY if classes.get(cls)]
    if blocking_human:
        return {
            "repaired": False,
            "applied_fixes": [],
            "skipped": list(classes.keys()),
            "reason": (
                f"Non-auto-repairable failure class(es) present: {', '.join(blocking_human)}. Human review required."
            ),
        }

    # Apply safe repairs for any repairable class that has failures.
    repairable_present = [cls for cls in _SAFE_REPAIRS if classes.get(cls)]

    if not repairable_present:
        total_failures = sum(len(v) for v in classes.values() if isinstance(v, list))
        if total_failures == 0:
            return {
                "repaired": True,
                "applied_fixes": [],
                "skipped": [],
                "reason": "No failures to repair.",
            }
        return {
            "repaired": False,
            "applied_fixes": [],
            "skipped": list(classes.keys()),
            "reason": "Failures present but no matching repair rule found.",
        }

    # Deduplicate commands — ruff format covers both ruff_format and missing_newline.
    seen_cmds: set[str] = set()
    for cls in repairable_present:
        cmd = _SAFE_REPAIRS[cls]
        cmd_key = " ".join(cmd)
        if cmd_key in seen_cmds:
            skipped.append(cls)
            continue
        seen_cmds.add(cmd_key)

        print(f"  Applying repair for '{cls}': {' '.join(cmd)}")
        rc, output = _run(cmd, dry_run=dry_run)
        if rc == 0:
            applied.append(cls)
            if output.strip():
                print(f"    → {output.strip()[:200]}")
        else:
            print(f"  WARN: repair for '{cls}' exited {rc}:\n{output[:400]}")
            skipped.append(cls)

    success = len(applied) > 0 and len(skipped) == 0
    return {
        "repaired": success,
        "applied_fixes": applied,
        "skipped": skipped,
        "reason": ("All repairable classes fixed." if success else f"Applied: {applied}. Could not repair: {skipped}."),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, help="Path to failure_classes.json")
    parser.add_argument("--branch", default="dev", help="Branch being repaired (informational)")
    parser.add_argument("--output", default=None, help="Write repair result JSON here")
    parser.add_argument("--dry-run", action="store_true", help="Print fixes without running them")
    args = parser.parse_args(argv)

    report = _load_report(Path(args.report))
    print(f"\nAuto-repair: branch={args.branch}  dry_run={args.dry_run}")

    result = repair(report, dry_run=args.dry_run)

    print(f"\nResult: repaired={result['repaired']}")
    print(f"  Applied: {result['applied_fixes']}")
    print(f"  Skipped: {result['skipped']}")
    print(f"  Reason:  {result['reason']}\n")

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2))

    return 0 if result["repaired"] else 1


if __name__ == "__main__":
    sys.exit(main())
