"""
scripts/quality_gate.py

Hard CI gate. Exits 1 if overall or per-dimension score falls below threshold,
or if a regression is detected vs the previous trend entry.

Usage:
    python scripts/quality_gate.py [--report quality_report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Minimum scores required to pass each gate (0–100 scale)
THRESHOLDS: dict[str, float] = {
    "overall_score": 60.0,  # Block merge below this
    "security": 70.0,  # Security is non-negotiable
    "type_safety": 50.0,  # Minimum type annotation coverage
    "complexity": 40.0,  # Allow legacy code some slack
    "maintainability": 40.0,
}

TREND_LOG = Path("reports/quality/quality_trend.jsonl")


def _last_two_scores() -> tuple[float, float] | None:
    """Return (prev_score, current_score) from trend log, or None."""
    if not TREND_LOG.exists():
        return None
    lines = [ln.strip() for ln in TREND_LOG.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        return None
    prev = json.loads(lines[-2])
    last = json.loads(lines[-1])
    return float(prev["overall"]), float(last["overall"])


def check(report_path: str = "quality_report.json") -> None:
    path = Path(report_path)
    if not path.exists():
        print(f"ERROR: report not found: {path}", file=sys.stderr)
        sys.exit(2)

    report: dict[str, object] = json.loads(path.read_text())
    failures: list[str] = []

    # ── Overall gate ──────────────────────────────────────────────
    overall = float(report["overall_score"])  # type: ignore[arg-type]
    if overall < THRESHOLDS["overall_score"]:
        failures.append(f"Overall score {overall:.1f} below minimum {THRESHOLDS['overall_score']}")

    # ── Per-dimension gates ───────────────────────────────────────
    dimensions: dict[str, dict[str, object]] = report.get("dimensions", {})  # type: ignore[assignment]
    for dim, minimum in THRESHOLDS.items():
        if dim == "overall_score":
            continue
        dim_data = dimensions.get(dim, {})
        score = float(dim_data.get("score", 0))  # type: ignore[arg-type]
        if score < minimum:
            meta = dim_data.get("meta", {})
            failures.append(f"{dim} score {score:.1f} below minimum {minimum}  (meta: {meta})")

    # ── Regression gate ───────────────────────────────────────────
    scores = _last_two_scores()
    if scores is not None:
        prev_score, curr_score = scores
        drop = prev_score - curr_score
        if drop > 10.0:  # >10pt drop triggers a hard block
            failures.append(f"Regression: score dropped {drop:.1f} pts ({prev_score:.1f} → {curr_score:.1f})")

    # ── Result ────────────────────────────────────────────────────
    if failures:
        print("QUALITY GATE FAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)

    grade = report.get("grade", "?")
    print(f"Quality gate passed: {overall:.1f} ({grade})")
    sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentop quality gate — blocks CI on low score")
    parser.add_argument("--report", default="quality_report.json", help="Path to quality_report.json")
    args = parser.parse_args()
    check(args.report)
