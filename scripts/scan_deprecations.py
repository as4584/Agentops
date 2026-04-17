#!/usr/bin/env python3
"""
Scan the codebase for patterns listed in scripts/repair_patterns.json
and report hit counts per pattern.

Usage
-----
    python scripts/scan_deprecations.py [--fix] [--severity LEVEL] [--paths PATH ...]

Options
-------
--fix           Apply safe mechanical fixes (runs fix_cmd for safe=true patterns).
--severity      Only report patterns at or above this severity level.
                Choices: medium, high, critical  [default: medium]
--paths         One or more root paths to scan  [default: backend/ deerflow/ scripts/]
--patterns      Path to repair_patterns.json  [default: scripts/repair_patterns.json]

Exit codes
----------
0  No critical hits found (or --fix resolved all safe ones)
1  One or more critical hits remain after scan
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_PATTERNS = _ROOT / "scripts" / "repair_patterns.json"
_DEFAULT_PATHS = ["backend", "deerflow", "scripts"]
_SEVERITY_ORDER = {"medium": 0, "high": 1, "critical": 2}

# Extensions we scan
_SCAN_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx"}


def _load_patterns(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())["patterns"]


def _scan_file(path: Path, patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a list of hits: {pattern_id, file, line, text}."""
    hits: list[dict[str, Any]] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits

    lines = content.splitlines()
    for pat in patterns:
        try:
            rx = re.compile(pat["detect"], re.MULTILINE)
        except re.error:
            continue
        for m in rx.finditer(content):
            lineno = content[: m.start()].count("\n") + 1
            hits.append(
                {
                    "pattern_id": pat["id"],
                    "severity": pat["severity"],
                    "safe": pat["safe"],
                    "fix_cmd": pat.get("fix_cmd"),
                    "file": str(path.relative_to(_ROOT)),
                    "line": lineno,
                    "text": lines[lineno - 1].strip()[:120] if lineno <= len(lines) else "",
                }
            )
    return hits


def scan(
    roots: list[Path],
    patterns: list[dict[str, Any]],
    min_severity: str = "medium",
) -> list[dict[str, Any]]:
    threshold = _SEVERITY_ORDER.get(min_severity, 0)
    active = [p for p in patterns if _SEVERITY_ORDER.get(p["severity"], 0) >= threshold]
    all_hits: list[dict[str, Any]] = []
    for root in roots:
        for fpath in root.rglob("*"):
            if fpath.suffix not in _SCAN_EXTS:
                continue
            # skip venv, node_modules, __pycache__
            parts = set(fpath.parts)
            if parts & {".venv", "node_modules", "__pycache__", ".git", "htmlcov"}:
                continue
            all_hits.extend(_scan_file(fpath, active))
    return all_hits


def _apply_fixes(hits: list[dict[str, Any]], *, dry_run: bool = False) -> dict[str, bool]:
    """Run fix_cmd for each unique safe pattern that has hits. Returns {pattern_id: success}."""
    seen: set[str] = set()
    results: dict[str, bool] = {}
    for hit in hits:
        pid = hit["pattern_id"]
        if not hit["safe"] or not hit["fix_cmd"] or pid in seen:
            continue
        seen.add(pid)
        cmd = hit["fix_cmd"]
        print(f"  Running fix for {pid}: {' '.join(cmd)}")
        if dry_run:
            results[pid] = True
            continue
        rc = subprocess.run(cmd, capture_output=False).returncode  # noqa: S603
        results[pid] = rc == 0
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="Apply safe fixes")
    parser.add_argument(
        "--severity",
        default="medium",
        choices=["medium", "high", "critical"],
        help="Minimum severity to report",
    )
    parser.add_argument(
        "--paths",
        nargs="+",
        default=_DEFAULT_PATHS,
        help="Root paths to scan",
    )
    parser.add_argument(
        "--patterns",
        default=str(_DEFAULT_PATTERNS),
        help="Path to repair_patterns.json",
    )
    parser.add_argument("--dry-run", action="store_true", help="With --fix: don't actually run")
    args = parser.parse_args(argv)

    patterns_path = Path(args.patterns)
    if not patterns_path.exists():
        print(f"ERROR: patterns file not found: {patterns_path}")
        return 1

    patterns = _load_patterns(patterns_path)
    roots = [_ROOT / p for p in args.paths]
    hits = scan(roots, patterns, min_severity=args.severity)

    # ── Summary ─────────────────────────────────────────────────────────
    by_pattern: dict[str, list[dict[str, Any]]] = {}
    for h in hits:
        by_pattern.setdefault(h["pattern_id"], []).append(h)

    print(f"\n{'═' * 60}")
    print("  Sprint 8 Pattern Scan — Hit Report")
    print(f"{'═' * 60}")
    total = 0
    critical_remain = 0
    for pat in patterns:
        if _SEVERITY_ORDER.get(pat["severity"], 0) < _SEVERITY_ORDER.get(args.severity, 0):
            continue
        count = len(by_pattern.get(pat["id"], []))
        total += count
        tag = "🔴" if pat["severity"] == "critical" else ("🟠" if pat["severity"] == "high" else "🟡")
        auto = "AUTO" if pat["safe"] else "HUMAN"
        print(f"  {tag} [{auto}] {pat['id']:<38} {count:>4} hit(s)")
        for h in by_pattern.get(pat["id"], [])[:3]:
            print(f"       {h['file']}:{h['line']}  {h['text'][:80]}")
        if count > 3:
            print(f"       … and {count - 3} more")
    print(f"{'─' * 60}")
    print(f"  Total hits: {total}  (severity >= {args.severity})")
    print(f"{'═' * 60}\n")

    if args.fix:
        fix_results = _apply_fixes(hits, dry_run=args.dry_run)
        for pid, ok in fix_results.items():
            print(f"  fix {'OK' if ok else 'FAILED'}: {pid}")

    # Count critical remaining after potential fix
    for pat in patterns:
        if pat["severity"] == "critical":
            count = len(by_pattern.get(pat["id"], []))
            if count > 0 and (not args.fix or not pat["safe"]):
                critical_remain += count

    return 1 if critical_remain > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
