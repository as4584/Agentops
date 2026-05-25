"""
scripts/quality_hotspots.py

Identifies worst files across complexity, type coverage, and security dimensions.
Cross-references to surface files that appear in 2+ categories — highest cleanup priority.

Usage:
    python scripts/quality_hotspots.py [--top 10] [--output reports/quality/hotspots.json]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def get_complex_files(top: int = 10) -> list[dict[str, object]]:
    """Top N files by average cyclomatic complexity (radon cc)."""
    result = subprocess.run(
        ["radon", "cc", "backend", "scripts", "deerflow", "-j", "--exclude", "*.venv*"],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return []
    data: dict[str, list[dict[str, object]]] = json.loads(result.stdout)
    file_scores: list[dict[str, object]] = []
    for filepath, blocks in data.items():
        if not blocks:
            continue
        complexities = [float(b["complexity"]) for b in blocks]  # type: ignore[arg-type,index]
        avg = sum(complexities) / len(complexities)
        worst_block = max(blocks, key=lambda b: float(b["complexity"]))  # type: ignore[arg-type,index]
        file_scores.append(
            {
                "file": filepath,
                "avg_complexity": round(avg, 2),
                "max_complexity": int(max(complexities)),
                "block_count": len(blocks),
                "worst_function": worst_block.get("name", "?"),
            }
        )
    return sorted(file_scores, key=lambda x: float(x["avg_complexity"]), reverse=True)[:top]  # type: ignore[arg-type]


def get_untyped_files(top: int = 10) -> list[dict[str, object]]:
    """Top N files by % of Any-typed expressions (mypy --any-exprs-report)."""
    any_report_dir = Path("/tmp/mypy_any_report")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "backend",
            "--ignore-missing-imports",
            "--any-exprs-report",
            str(any_report_dir),
            "--no-error-summary",
            "--no-pretty",
            "--quiet",
        ],
        capture_output=True,
        text=True,
    )
    any_file = any_report_dir / "any-exprs.txt"
    if not any_file.exists():
        return []

    file_scores: list[dict[str, object]] = []
    for line in any_file.read_text().splitlines()[1:]:  # skip header
        parts = line.split()
        if len(parts) >= 3:
            try:
                any_count = int(parts[1])
                total = int(parts[2])
                file_scores.append(
                    {
                        "file": parts[0],
                        "any_count": any_count,
                        "total_exprs": total,
                        "any_pct": round(any_count / max(total, 1) * 100, 1),
                    }
                )
            except ValueError:
                continue
    return sorted(file_scores, key=lambda x: float(x["any_pct"]), reverse=True)[:top]  # type: ignore[arg-type]


def get_security_hotspots() -> list[dict[str, object]]:
    """Files with HIGH or MEDIUM severity Bandit findings."""
    result = subprocess.run(
        ["bandit", "-r", "backend", "scripts", "-f", "json", "-q"],
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        return []
    data: dict[str, object] = json.loads(result.stdout)
    results: list[dict[str, object]] = data.get("results", [])  # type: ignore[assignment]
    hotspots = [
        {
            "file": r.get("filename", ""),
            "line": r.get("line_number", 0),
            "issue": r.get("issue_text", ""),
            "severity": r.get("issue_severity", ""),
            "confidence": r.get("issue_confidence", ""),
            "cwe": (r.get("issue_cwe") or {}).get("id", ""),  # type: ignore[union-attr,attr-defined]
        }
        for r in results
        if str(r.get("issue_severity", "")) in ("HIGH", "MEDIUM")
    ]
    return sorted(hotspots, key=lambda x: (x["severity"], x["file"]))  # type: ignore[arg-type]


def get_dead_code(top: int = 20) -> list[dict[str, object]]:
    """Unreferenced names found by vulture (confidence ≥ 80%)."""
    result = subprocess.run(
        ["vulture", "backend", "scripts", "--min-confidence", "80"],
        capture_output=True,
        text=True,
    )
    dead: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        # Format: path/file.py:42: unused function 'foo' (80% confidence)
        if "unused " in line:
            parts = line.split(":", 2)
            if len(parts) >= 3:
                dead.append({"location": f"{parts[0]}:{parts[1]}", "detail": parts[2].strip()})
    return dead[:top]


def generate_hotspot_report(top: int = 10, output: str = "reports/quality/hotspots.json") -> dict[str, object]:
    print("Scanning complexity…")
    complex_files = get_complex_files(top)
    print(f"  → {len(complex_files)} complex files")

    print("Scanning type coverage…")
    untyped_files = get_untyped_files(top)
    print(f"  → {len(untyped_files)} untyped files")

    print("Scanning security…")
    security = get_security_hotspots()
    print(f"  → {len(security)} security findings")

    print("Scanning dead code…")
    dead = get_dead_code()
    print(f"  → {len(dead)} dead code items")

    complex_set = {str(f["file"]) for f in complex_files}
    untyped_set = {str(f["file"]) for f in untyped_files}
    security_set = {str(f["file"]) for f in security}

    critical_files = sorted((complex_set & untyped_set) | (complex_set & security_set) | (untyped_set & security_set))

    report: dict[str, object] = {
        "complex_files": complex_files,
        "untyped_files": untyped_files,
        "security_hotspots": security,
        "dead_code": dead,
        "critical_files": critical_files,
        "critical_file_count": len(critical_files),
    }

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))

    print(f"\nCritical files (appear in 2+ categories): {len(critical_files)}")
    for f in critical_files:
        print(f"  {f}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Identify code quality hotspots")
    parser.add_argument("--top", type=int, default=10, help="Top N files per category")
    parser.add_argument("--output", default="reports/quality/hotspots.json")
    args = parser.parse_args()
    generate_hotspot_report(args.top, args.output)
