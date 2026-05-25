#!/usr/bin/env python3
"""
Prune old generated runtime artifacts without touching tracked source files.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class CleanupRule:
    path: str
    kind: str = "files"
    age_hours: int = 72


RULES = (
    CleanupRule("output", age_hours=48),
    CleanupRule("reports", age_hours=120),
    CleanupRule("htmlcov", kind="dir", age_hours=24),
    CleanupRule(".pytest_cache", kind="dir", age_hours=24),
    CleanupRule(".mypy_cache", kind="dir", age_hours=24),
    CleanupRule(".ruff_cache", kind="dir", age_hours=24),
    CleanupRule("backend/logs", age_hours=72),
    CleanupRule("data/training_runs", age_hours=168),
    CleanupRule("data/experiments", age_hours=168),
    CleanupRule("ml-lab-viewer/output", age_hours=72),
)


def within_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except ValueError:
        return False


def is_tracked(candidate: Path) -> bool:
    rel = candidate.relative_to(REPO_ROOT)
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(rel)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def older_than(candidate: Path, cutoff_ts: float) -> bool:
    try:
        return candidate.stat().st_mtime < cutoff_ts
    except FileNotFoundError:
        return False


def delete_path(candidate: Path, dry_run: bool) -> None:
    if dry_run:
        return
    if candidate.is_dir():
        shutil.rmtree(candidate, ignore_errors=True)
    else:
        candidate.unlink(missing_ok=True)


def cleanup_rule(rule: CleanupRule, dry_run: bool) -> tuple[int, int]:
    target = REPO_ROOT / rule.path
    if not target.exists() or not within_repo(target):
        return (0, 0)

    cutoff_ts = time.time() - (rule.age_hours * 3600)
    removed = 0
    reclaimed = 0

    if rule.kind == "dir":
        if older_than(target, cutoff_ts) and not is_tracked(target):
            reclaimed = sum(
                child.stat().st_size for child in target.rglob("*") if child.exists() and child.is_file()
            )
            delete_path(target, dry_run)
            return (1, reclaimed)
        return (0, 0)

    for child in target.rglob("*"):
        if not child.exists() or child.is_dir():
            continue
        if not within_repo(child) or is_tracked(child) or not older_than(child, cutoff_ts):
            continue
        reclaimed += child.stat().st_size
        delete_path(child, dry_run)
        removed += 1
    return (removed, reclaimed)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune old generated runtime artifacts.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be removed without deleting anything.")
    args = parser.parse_args()

    total_removed = 0
    total_reclaimed = 0

    print(f"Agentop runtime cleanup ({'dry-run' if args.dry_run else 'apply'})")
    for rule in RULES:
        removed, reclaimed = cleanup_rule(rule, args.dry_run)
        total_removed += removed
        total_reclaimed += reclaimed
        print(f"- {rule.path}: removed={removed} retention={rule.age_hours}h")

    print(
        "Summary: "
        f"entries_removed={total_removed}, "
        f"approx_bytes_reclaimed={total_reclaimed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
