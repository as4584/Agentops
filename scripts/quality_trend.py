"""
scripts/quality_trend.py

Appends the current quality report to a JSONL trend log and detects regressions.
Exits 1 if score dropped more than --threshold points vs previous run.

Usage:
    python scripts/quality_trend.py [--threshold 5] [--report quality_report.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

TREND_LOG = Path("reports/quality/quality_trend.jsonl")


def append_trend(report: dict[str, object]) -> None:
    TREND_LOG.parent.mkdir(parents=True, exist_ok=True)
    dims: dict[str, dict[str, object]] = report.get("dimensions", {})  # type: ignore[assignment]
    entry = {
        "ts": datetime.now(UTC).isoformat(),
        "overall": report["overall_score"],
        "grade": report["grade"],
        "dimensions": {dim: data["score"] for dim, data in dims.items()},
    }
    with TREND_LOG.open("a") as fh:
        fh.write(json.dumps(entry) + "\n")
    print(f"Trend appended: {entry['overall']} ({entry['grade']})")


def detect_regression(threshold: float = 5.0) -> bool:
    """Return True if score dropped more than threshold points."""
    if not TREND_LOG.exists():
        return False
    lines = [ln.strip() for ln in TREND_LOG.read_text().splitlines() if ln.strip()]
    if len(lines) < 2:
        return False
    last = json.loads(lines[-1])
    prev = json.loads(lines[-2])
    drop = float(prev["overall"]) - float(last["overall"])
    if drop > threshold:
        print(f"QUALITY REGRESSION: score dropped {drop:.1f} points ({prev['overall']} → {last['overall']})")
        return True
    delta = float(last["overall"]) - float(prev["overall"])
    trend = "↑" if delta >= 0 else "↓"
    print(f"Trend: {prev['overall']} → {last['overall']} ({trend}{abs(delta):.1f})")
    return False


def print_history(n: int = 10) -> None:
    """Print last N trend entries as a table."""
    if not TREND_LOG.exists():
        print("No trend data yet.")
        return
    lines = [ln.strip() for ln in TREND_LOG.read_text().splitlines() if ln.strip()]
    entries = [json.loads(ln) for ln in lines[-n:]]
    print(f"\n{'Date':<28} {'Score':>6} {'Grade':>5}  Dimensions")
    print("-" * 80)
    for e in entries:
        dims = "  ".join(f"{k}={v:.0f}" for k, v in e.get("dimensions", {}).items())
        print(f"{e['ts']:<28} {e['overall']:>6.1f} {e['grade']:>5}  {dims}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Track quality score trend")
    parser.add_argument("--report", default="quality_report.json", help="quality_report.json path")
    parser.add_argument("--threshold", type=float, default=5.0, help="Regression threshold (pts)")
    parser.add_argument("--history", action="store_true", help="Print trend history and exit")
    args = parser.parse_args()

    if args.history:
        print_history()
        sys.exit(0)

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"Report not found: {report_path}", file=sys.stderr)
        sys.exit(1)

    report = json.loads(report_path.read_text())
    append_trend(report)
    regressed = detect_regression(args.threshold)
    sys.exit(1 if regressed else 0)
