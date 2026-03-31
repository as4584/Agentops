#!/usr/bin/env python3
"""
scripts/dataset_stats.py
─────────────────────────────────────────────────────────────────────────────
Quantify training data growth — run this any time to see where you stand.

Shows:
  • Total pairs + growth over time (by run)
  • Per-strategy breakdown with ASCII bar chart
  • Quality signals (answer richness, code coverage, diversity)
  • Quality score 0–100 for each batch file
  • Projection to fine-tune readiness (500 pairs = ready to train)

Usage:
  python scripts/dataset_stats.py            # summary view
  python scripts/dataset_stats.py --detail   # per-file breakdown
  python scripts/dataset_stats.py --history  # growth timeline
  python scripts/dataset_stats.py --quality  # deep quality analysis
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"

# Terminal colors
G = "\033[0;32m"
B = "\033[0;34m"
Y = "\033[1;33m"
R = "\033[0;31m"
C = "\033[0;36m"
M = "\033[0;35m"
BOLD = "\033[1m"
DIM = "\033[2m"
RST = "\033[0m"

# Map filename prefix → Strategy label
STRATEGY_MAP = {
    "architecture_pairs": "Strategy 1 · Architecture Q&A",
    "spec_pairs":         "Strategy 2 · IBDS Component Specs",
    "git_pairs":          "Strategy 3 · Git Commit History",
    "pytest_pairs":       "Strategy 4 · Pytest Failure Pairs",
    "review_pairs":       "Strategy 5 · Code Review / Refactoring",
    "3d-web":             "Strategy 6 · 3D Web (Three.js/GSAP)",
    "agentop":            "Strategy 7 · Agentop Backend Synthesis",
    "ibds":               "Strategy 8 · IBDS Dashboard Synthesis",
}

FINE_TUNE_TARGET = 500   # pairs needed to start fine-tuning
QUALITY_TARGET   = 200   # avg chars per GPT answer for "good" quality


# ── data loading ───────────────────────────────────────────────────────────────

def load_all(exclude_combined: bool = True) -> list[dict]:
    """Load all JSONL records, optionally excluding combined.jsonl."""
    records = []
    for path in sorted(OUT_DIR.glob("*.jsonl")):
        if exclude_combined and path.stem.startswith("combined"):
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                rec["_source"] = path.name
                records.append(rec)
            except json.JSONDecodeError:
                continue
    return records


def get_strategy(filename: str) -> str:
    for prefix, label in STRATEGY_MAP.items():
        if filename.startswith(prefix):
            return label
    return "Other"


def parse_timestamp(filename: str) -> datetime | None:
    m = re.search(r"(\d{8}_\d{6})", filename)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return None


# ── quality metrics ────────────────────────────────────────────────────────────

def analyze_pair(rec: dict) -> dict:
    """Extract quality signals from a single ShareGPT record."""
    turns = rec.get("conversations", [])
    human = next((t["value"] for t in turns if t.get("from") == "human"), "")
    gpt   = next((t["value"] for t in turns if t.get("from") == "gpt"), "")

    has_code   = "```" in gpt
    code_lines = sum(1 for l in gpt.splitlines() if l.strip().startswith(("    ", "\t")) or "```" in l)
    has_list   = bool(re.search(r"^\s*[\*\-\d]", gpt, re.MULTILINE))
    has_steps  = bool(re.search(r"\d\.\s", gpt))
    word_count = len(gpt.split())
    diversity  = len(set(human.lower().split()[:8]))  # unique words in first 8 words of question

    # Richness score 0–100
    richness = min(100, int(
        (min(len(gpt), 2000) / 2000) * 40 +  # length (40pts)
        (20 if has_code  else 0) +             # has code (20pts)
        (15 if has_list  else 0) +             # has list/structure (15pts)
        (10 if has_steps else 0) +             # has numbered steps (10pts)
        (min(word_count, 300) / 300) * 15      # word count bonus (15pts)
    ))

    return {
        "q_len":    len(human),
        "a_len":    len(gpt),
        "word_count": word_count,
        "has_code": has_code,
        "has_list": has_list,
        "has_steps": has_steps,
        "code_lines": code_lines,
        "diversity": diversity,
        "richness":  richness,
    }


# ── ASCII chart helpers ────────────────────────────────────────────────────────

def bar(value: int, max_val: int, width: int = 30, char: str = "█") -> str:
    filled = round(value / max_val * width) if max_val > 0 else 0
    return char * filled + DIM + "░" * (width - filled) + RST


def sparkline(values: list[int]) -> str:
    chars = " ▁▂▃▄▅▆▇█"
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo or 1
    return "".join(chars[min(8, int((v - lo) / span * 8))] for v in values)


def progress_bar(value: int, total: int, width: int = 40) -> str:
    pct = value / total if total > 0 else 0
    filled = int(pct * width)
    color = G if pct >= 1 else (Y if pct >= 0.5 else R)
    return (
        f"[{color}{'█' * filled}{RST}{'░' * (width - filled)}] "
        f"{color}{BOLD}{value:3d}/{total}{RST} ({pct*100:.0f}%)"
    )


# ── views ─────────────────────────────────────────────────────────────────────

def print_summary(records: list[dict]) -> None:
    total = len(records)
    by_strategy: dict[str, int] = defaultdict(int)
    for r in records:
        by_strategy[get_strategy(r["_source"])] += 1

    analyses = [analyze_pair(r) for r in records]
    avg_a_len   = sum(a["a_len"]    for a in analyses) / max(1, len(analyses))
    avg_richness= sum(a["richness"] for a in analyses) / max(1, len(analyses))
    code_pct    = sum(1 for a in analyses if a["has_code"]) / max(1, len(analyses)) * 100

    print(f"\n{BOLD}{'═'*62}{RST}")
    print(f"{BOLD}  Agentop ML Training Dataset — {datetime.now():%Y-%m-%d %H:%M}{RST}")
    print(f"{BOLD}{'═'*62}{RST}\n")

    # Overall progress to fine-tune readiness
    print(f"  {BOLD}Fine-Tune Readiness{RST}")
    print(f"  {progress_bar(total, FINE_TUNE_TARGET)}\n")

    # Strategy breakdown
    max_count = max(by_strategy.values()) if by_strategy else 1
    print(f"  {BOLD}Pairs by Strategy{RST}")
    for strategy, count in sorted(by_strategy.items(), key=lambda x: -x[1]):
        b = bar(count, max_count, width=22)
        print(f"  {C}{strategy:<40}{RST} {b} {BOLD}{count:>3}{RST}")

    # Quality signals
    print(f"\n  {BOLD}Quality Signals{RST}")
    q_color = G if avg_richness >= 70 else (Y if avg_richness >= 40 else R)
    c_color = G if code_pct >= 40 else (Y if code_pct >= 20 else R)
    l_color = G if avg_a_len >= QUALITY_TARGET else (Y if avg_a_len >= 100 else R)
    print(f"  Avg answer richness score  {q_color}{BOLD}{avg_richness:5.1f}/100{RST}")
    print(f"  Avg answer length          {l_color}{BOLD}{avg_a_len:6.0f} chars{RST}")
    print(f"  Code inclusion rate        {c_color}{BOLD}{code_pct:5.1f}%{RST}")
    print(f"  Total pairs collected      {G}{BOLD}{total:>5}{RST}")

    # Gap to target
    needed = max(0, FINE_TUNE_TARGET - total)
    if needed > 0:
        print(f"\n  {Y}Need {needed} more pairs to hit {FINE_TUNE_TARGET} fine-tune target.{RST}")
        print(f"  {DIM}Run: ./scripts/run_ml_training.sh --ollama{RST}")
        est_ollama_pairs = 4  # avg pairs per Ollama call
        est_calls = math.ceil(needed / est_ollama_pairs)
        print(f"  {DIM}Estimated: ~{est_calls} Ollama chunks (--budget {est_calls}){RST}")
    else:
        print(f"\n  {G}{BOLD}✓ Dataset ready for fine-tuning!{RST}")
        print(f"  {DIM}See docs/ML_TRAINING_PLAN.md for Unsloth commands.{RST}")

    print(f"\n{BOLD}{'═'*62}{RST}\n")


def print_history(records: list[dict]) -> None:
    """Show growth timeline ordered by run timestamp."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_file[r["_source"]].append(r)

    # Sort files by embedded timestamp
    runs: list[tuple[datetime, str, int, float]] = []
    for fname, recs in by_file.items():
        ts = parse_timestamp(fname) or datetime(2000, 1, 1)
        analyses = [analyze_pair(r) for r in recs]
        avg_rich = sum(a["richness"] for a in analyses) / max(1, len(analyses))
        runs.append((ts, fname, len(recs), avg_rich))

    runs.sort(key=lambda x: x[0])

    print(f"\n{BOLD}{'─'*62}{RST}")
    print(f"{BOLD}  Growth Timeline{RST}")
    print(f"{BOLD}{'─'*62}{RST}")
    print(f"  {DIM}{'Date/Time':<20} {'File':<36} {'Pairs':>5} {'Quality':>8}{RST}")
    print(f"  {'─'*20} {'─'*36} {'─'*5} {'─'*8}")

    running_total = 0
    pair_counts = []
    for ts, fname, count, quality in runs:
        running_total += count
        pair_counts.append(running_total)
        q_color = G if quality >= 70 else (Y if quality >= 40 else R)
        ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts.year > 2000 else "n/a"
        print(f"  {ts_str:<20} {fname:<36} {BOLD}{count:>5}{RST}  {q_color}{quality:>6.1f}/100{RST}")

    print(f"\n  Cumulative growth: {sparkline(pair_counts)}  (each char = one run)")
    print(f"  Total: {BOLD}{G}{running_total}{RST} pairs across {len(runs)} runs")
    print(f"{BOLD}{'─'*62}{RST}\n")


def print_detail(records: list[dict]) -> None:
    """Per-file breakdown with quality scores."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_file[r["_source"]].append(r)

    print(f"\n{BOLD}{'─'*72}{RST}")
    print(f"{BOLD}  Per-File Detail{RST}")
    print(f"{BOLD}{'─'*72}{RST}")

    for fname in sorted(by_file.keys()):
        recs = by_file[fname]
        analyses = [analyze_pair(r) for r in recs]
        avg_rich    = sum(a["richness"]   for a in analyses) / len(analyses)
        avg_a_len   = sum(a["a_len"]      for a in analyses) / len(analyses)
        avg_q_len   = sum(a["q_len"]      for a in analyses) / len(analyses)
        code_pct    = sum(1 for a in analyses if a["has_code"]) / len(analyses) * 100
        list_pct    = sum(1 for a in analyses if a["has_list"]) / len(analyses) * 100
        strategy    = get_strategy(fname)

        q_color = G if avg_rich >= 70 else (Y if avg_rich >= 40 else R)
        print(f"\n  {BOLD}{fname}{RST}")
        print(f"    Strategy : {C}{strategy}{RST}")
        print(f"    Pairs    : {BOLD}{len(recs)}{RST}")
        print(f"    Quality  : {q_color}{BOLD}{avg_rich:.1f}/100{RST}  {bar(int(avg_rich), 100, width=20)}")
        print(f"    Avg Q len: {avg_q_len:>6.0f} chars")
        print(f"    Avg A len: {avg_a_len:>6.0f} chars")
        print(f"    Has code : {code_pct:>5.1f}%")
        print(f"    Has lists: {list_pct:>5.1f}%")

    print(f"\n{BOLD}{'─'*72}{RST}\n")


def print_quality(records: list[dict]) -> None:
    """Deep quality analysis — distribution of scores, worst/best pairs."""
    analyses = [{"rec": r, **analyze_pair(r)} for r in records]

    buckets = Counter()
    for a in analyses:
        score = a["richness"]
        if score >= 80: buckets["[80-100] Excellent"]  += 1
        elif score >= 60: buckets["[60-79]  Good"]     += 1
        elif score >= 40: buckets["[40-59]  Adequate"] += 1
        else:             buckets["[0-39]   Weak"]     += 1

    print(f"\n{BOLD}{'─'*62}{RST}")
    print(f"{BOLD}  Quality Distribution (Richness Score){RST}")
    print(f"{BOLD}{'─'*62}{RST}")

    total = len(analyses)
    for bucket, count in sorted(buckets.items()):
        pct = count / total * 100
        color = G if "Excellent" in bucket else (G if "Good" in bucket else (Y if "Adequate" in bucket else R))
        print(f"  {color}{bucket}{RST} {bar(count, total, width=24)} {BOLD}{count:>3}{RST} ({pct:.0f}%)")

    # Lowest quality pairs (candidates for improvement)
    worst = sorted(analyses, key=lambda x: x["richness"])[:3]
    best  = sorted(analyses, key=lambda x: -x["richness"])[:2]

    print(f"\n  {Y}{BOLD}Lowest quality pairs (improve these):{RST}")
    for i, a in enumerate(worst):
        turns = a["rec"].get("conversations", [])
        q = next((t["value"] for t in turns if t["from"] == "human"), "")[:80]
        print(f"  {i+1}. [{a['richness']:.0f}/100] {DIM}{a['rec']['_source']}{RST}")
        print(f"     Q: {q}...")

    print(f"\n  {G}{BOLD}Highest quality pairs (best examples):{RST}")
    for i, a in enumerate(best):
        turns = a["rec"].get("conversations", [])
        q = next((t["value"] for t in turns if t["from"] == "human"), "")[:80]
        print(f"  {i+1}. [{a['richness']:.0f}/100] {DIM}{a['rec']['_source']}{RST}")
        print(f"     Q: {q}...")

    # Strategy quality comparison
    by_strategy: dict[str, list[int]] = defaultdict(list)
    for a in analyses:
        by_strategy[get_strategy(a["rec"]["_source"])].append(a["richness"])

    print(f"\n  {BOLD}Average quality by strategy:{RST}")
    for strategy, scores in sorted(by_strategy.items(), key=lambda x: -sum(x[1])/len(x[1])):
        avg = sum(scores) / len(scores)
        q_color = G if avg >= 70 else (Y if avg >= 40 else R)
        print(f"  {strategy:<45} {q_color}{BOLD}{avg:5.1f}{RST} avg  {bar(int(avg), 100, width=15)}")

    print(f"\n{BOLD}{'─'*62}{RST}\n")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Quantify ML training data growth.")
    parser.add_argument("--detail",  action="store_true", help="Per-file breakdown")
    parser.add_argument("--history", action="store_true", help="Growth timeline by run")
    parser.add_argument("--quality", action="store_true", help="Deep quality analysis")
    parser.add_argument("--all",     action="store_true", help="Show all views")
    args = parser.parse_args()

    if not OUT_DIR.exists() or not list(OUT_DIR.glob("*.jsonl")):
        print(f"{R}No training data found in {OUT_DIR}{RST}")
        print("Run:  ./scripts/run_ml_training.sh")
        return

    records = load_all()
    if not records:
        print(f"{R}No valid pairs found.{RST}")
        return

    print_summary(records)

    if args.history or args.all:
        print_history(records)

    if args.detail or args.all:
        print_detail(records)

    if args.quality or args.all:
        print_quality(records)

    if not (args.history or args.detail or args.quality or args.all):
        print(f"{DIM}  Flags: --history  --detail  --quality  --all{RST}\n")


if __name__ == "__main__":
    main()
