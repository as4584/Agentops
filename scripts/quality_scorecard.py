"""
scripts/quality_scorecard.py

Aggregates ruff, mypy, radon, bandit outputs into a single scored report.
Five dimensions, one score each (0–100). Weighted overall score + letter grade.

Usage:
    python scripts/quality_scorecard.py --reports reports/quality --output quality_report.json
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

WEIGHTS: dict[str, float] = {
    "lint": 0.20,  # Ruff — style + correctness
    "type_safety": 0.25,  # Mypy — type coverage %
    "complexity": 0.20,  # Radon CC — avg cyclomatic
    "maintainability": 0.20,  # Radon MI — maintainability index
    "security": 0.15,  # Bandit — high/medium findings
}


def score_lint(ruff_path: Path) -> tuple[float, dict[str, object]]:
    """0 errors → 100. Linear decay at 2 pts per error, floor 0."""
    data: list[object] = json.loads(ruff_path.read_text())
    errors = len(data)
    score = max(0.0, 100.0 - (errors * 2))
    return score, {"error_count": errors}


def score_type_safety(mypy_dir: Path) -> tuple[float, dict[str, object]]:
    """Lower any% → higher score. Reads mypy JSON summary."""
    summary_path = mypy_dir / "json" / "summary.json"
    if not summary_path.exists():
        # Try flat summary.json (mypy --json-report writes here)
        summary_path = mypy_dir / "summary.json"
    summary: dict[str, object] = json.loads(summary_path.read_text())
    precision: dict[str, object] = summary.get("precision", {})  # type: ignore[assignment]
    # any_str_pct = percentage of expressions typed as Any
    any_pct: float = float(precision.get("any_str_pct", 0))  # type: ignore[arg-type]
    score = max(0.0, 100.0 - any_pct)
    return round(score, 1), {"any_pct": round(any_pct, 2)}


def score_complexity(radon_path: Path) -> tuple[float, dict[str, object]]:
    """
    Radon CC JSON: {filepath: [{complexity: int, name: str, ...}]}
    A=1-5 (100), B=6-10, C=11-15, D=16-20, F=21+ (0).
    """
    data: dict[str, list[dict[str, object]]] = json.loads(radon_path.read_text())
    scores: list[float] = []
    for blocks in data.values():
        for block in blocks:
            scores.append(float(block["complexity"]))  # type: ignore[arg-type]
    if not scores:
        return 100.0, {"avg_complexity": 0, "sample_size": 0}
    avg = sum(scores) / len(scores)
    # Linear: avg=1 → 100, avg=18 → 0
    score = max(0.0, 100.0 - ((avg - 1) * 6))
    return round(score, 1), {
        "avg_complexity": round(avg, 2),
        "max_complexity": int(max(scores)),
        "sample_size": len(scores),
    }


def score_maintainability(radon_path: Path) -> tuple[float, dict[str, object]]:
    """
    Radon MI JSON: {filepath: {mi: float, rank: str}}
    MI is already 0–100; use it directly.
    """
    data: dict[str, dict[str, object]] = json.loads(radon_path.read_text())
    mis: list[float] = [float(v["mi"]) for v in data.values() if "mi" in v]  # type: ignore[arg-type]
    if not mis:
        return 100.0, {"avg_mi": 100, "sample_size": 0}
    avg = sum(mis) / len(mis)
    return round(avg, 1), {"avg_mi": round(avg, 2), "sample_size": len(mis)}


def score_security(bandit_path: Path) -> tuple[float, dict[str, object]]:
    """HIGH finding = -10pts, MEDIUM = -3pts, floor 0."""
    data: dict[str, object] = json.loads(bandit_path.read_text())
    results: list[dict[str, object]] = data.get("results", [])  # type: ignore[assignment]
    high = sum(1 for r in results if r.get("issue_severity") == "HIGH")
    medium = sum(1 for r in results if r.get("issue_severity") == "MEDIUM")
    score = max(0.0, 100.0 - (high * 10) - (medium * 3))
    return round(score, 1), {"high": high, "medium": medium, "low": len(results) - high - medium}


def grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def generate(reports_dir: str, output: str) -> dict[str, object]:
    base = Path(reports_dir)

    scorers: dict[str, tuple[object, Path]] = {
        "lint": (score_lint, base / "ruff.json"),
        "type_safety": (score_type_safety, base / "mypy"),
        "complexity": (score_complexity, base / "complexity.json"),
        "maintainability": (score_maintainability, base / "maintainability.json"),
        "security": (score_security, base / "security.json"),
    }

    dimensions: dict[str, dict[str, object]] = {}
    total = 0.0

    for dim, (fn, path) in scorers.items():
        try:
            score, meta = fn(path)  # type: ignore[operator]
        except Exception as exc:
            score, meta = 0.0, {"error": str(exc)}
        dimensions[dim] = {"score": score, "meta": meta}
        total += score * WEIGHTS[dim]

    report: dict[str, object] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_score": round(total, 1),
        "grade": grade(total),
        "dimensions": dimensions,
        "thresholds": {
            "block_merge": 60,
            "warn": 75,
            "healthy": 85,
        },
    }

    Path(output).write_text(json.dumps(report, indent=2))
    print(f"Overall quality score: {report['overall_score']} ({report['grade']})")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Agentop quality scorecard")
    parser.add_argument("--reports", required=True, help="Directory containing tool JSON outputs")
    parser.add_argument("--output", required=True, help="Path to write quality_report.json")
    args = parser.parse_args()
    generate(args.reports, args.output)
