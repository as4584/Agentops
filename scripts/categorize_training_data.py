#!/usr/bin/env python3
"""
scripts/categorize_training_data.py
────────────────────────────────────
Auto-assign `difficulty` labels to unlabeled routing records in data/training/.

Rules (applied in priority order):
  1. expected_agent/chosen_agent == BLOCKED → red_line
  2. boundary_agents non-empty            → hard
  3. rejected_agents non-empty AND any pair is in WEAK_BOUNDARIES → hard
  4. rejected_agents count >= 2           → hard
  5. message matches HARD_KEYWORDS regex  → hard
  6. records with only `conversations` key (SFT) → skip (no routing label needed)
  7. trajectories with chosen_agent but no rejected_agents → easy

Writes updated records in-place; backs up originals to <file>.bak.

Usage:
  python scripts/categorize_training_data.py               # auto-label all
  python scripts/categorize_training_data.py --dry-run     # stats only
  python scripts/categorize_training_data.py --dir data/training/gold
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VALID_AGENTS = {
    "soul_core", "devops_agent", "monitor_agent", "self_healer_agent",
    "code_review_agent", "security_agent", "data_agent", "comms_agent",
    "cs_agent", "it_agent", "knowledge_agent", "ocr_agent", "BLOCKED",
}

# Agent pairs where the boundary is known to be ambiguous
WEAK_BOUNDARIES: set[frozenset[str]] = {
    frozenset(["knowledge_agent", "soul_core"]),
    frozenset(["monitor_agent", "it_agent"]),
    frozenset(["code_review_agent", "security_agent"]),
    frozenset(["devops_agent", "self_healer_agent"]),
    frozenset(["cs_agent", "knowledge_agent"]),
    frozenset(["it_agent", "self_healer_agent"]),
    frozenset(["comms_agent", "monitor_agent"]),
    frozenset(["data_agent", "knowledge_agent"]),
}

# Patterns in user messages that signal ambiguity / hard routing
HARD_RE = re.compile(
    r"\b("
    r"also|both|and then|maybe|either|or\b|unclear|confused|"
    r"not sure|redirect|escalate|depends|might|could\b|which agent|"
    r"who should|should i|after.*deploy|after.*build|after.*restart|"
    r"restart.*(deploy|build|ci)|deploy.*(restart|kill|crash)|"
    r"review.*(secret|cve|vuln)|secret.*(review|code)|"
    r"monitor.*(diagnos|fix|restart|repair)|diagnos.*(monitor|alert)|"
    r"knowledge.*(soul|reflect|purpose|why)|purpose.*(search|knowledge)|"
    r"report.*incident|alert.*fix|log.*crash"
    r")\b",
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════
# Classification logic
# ══════════════════════════════════════════════════════════════════════════


def classify(record: dict) -> str | None:
    """Return a difficulty label or None (meaning: skip this record).

    Returns None when:
    - The record already has a non-placeholder label
    - The record has no routing signal (pure SFT conversation)
    """
    existing = record.get("difficulty") or record.get("type")
    if existing and existing not in ("?", "", None):
        return None  # already labeled — don't overwrite

    agent = record.get("chosen_agent") or record.get("expected_agent")
    if not agent:
        return None  # pure SFT / no routing signal

    if agent == "BLOCKED":
        return "red_line"

    msg = (record.get("user_message") or record.get("task") or "").lower()

    boundary_agents: list[str] = record.get("boundary_agents", [])
    rejected: list[str] = record.get("rejected_agents", [])

    # 1. boundary_agents populated → hard (was flagged as boundary at capture time)
    if boundary_agents:
        return "hard"

    # 2. rejected_agents × WEAK_BOUNDARIES → hard
    if rejected:
        for r_agent in rejected:
            # rejected_agents may be a string or a dict with an "agent" key
            if isinstance(r_agent, dict):
                r_agent = r_agent.get("agent") or r_agent.get("agent_id") or ""
            if not isinstance(r_agent, str):
                continue
            if frozenset([agent, r_agent]) in WEAK_BOUNDARIES:
                return "hard"
        if len(rejected) >= 2:
            return "hard"

    # 3. Message signals ambiguity
    if HARD_RE.search(msg):
        return "hard"

    return "easy"


# ══════════════════════════════════════════════════════════════════════════
# File processing
# ══════════════════════════════════════════════════════════════════════════


def process_file(path: Path, dry_run: bool) -> tuple[int, int, int]:
    """Process one JSONL file.  Returns (labeled, already_had_label, skipped)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    newly_labeled = 0
    already_labeled = 0
    skipped = 0

    for raw in lines:
        raw = raw.strip()
        if not raw:
            new_lines.append("")
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            new_lines.append(raw)
            skipped += 1
            continue

        label = classify(rec)
        if label is not None:
            rec["difficulty"] = label
            newly_labeled += 1
        else:
            existing = rec.get("difficulty") or rec.get("type")
            if existing and existing not in ("?", ""):
                already_labeled += 1
            else:
                skipped += 1

        new_lines.append(json.dumps(rec, ensure_ascii=False))

    if newly_labeled > 0 and not dry_run:
        bak = path.with_suffix(".jsonl.bak")
        shutil.copy2(path, bak)
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return newly_labeled, already_labeled, skipped


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Auto-label difficulty on unlabeled routing training records"
    )
    p.add_argument(
        "--dir",
        type=Path,
        default=ROOT / "data" / "training",
        help="Root directory to scan (default: data/training)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print stats without writing any files",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file results",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    data_dir: Path = args.dir

    if not data_dir.exists():
        print(f"[ERROR] Directory not found: {data_dir}")
        sys.exit(1)

    total_labeled = total_already = total_skipped = 0

    for jsonl in sorted(data_dir.rglob("*.jsonl")):
        if "golden_eval" in str(jsonl) or jsonl.suffix == ".bak":
            continue
        labeled, already, skipped = process_file(jsonl, args.dry_run)
        total_labeled += labeled
        total_already += already
        total_skipped += skipped
        if args.verbose and labeled:
            rel = jsonl.relative_to(data_dir)
            print(f"  {rel}: +{labeled} labeled  ({already} had label, {skipped} skipped)")

    verb = "Would label" if args.dry_run else "Labeled"
    print(f"\n{verb}: {total_labeled} records")
    print(f"Already labeled : {total_already}")
    print(f"Skipped (no routing signal): {total_skipped}")
    if args.dry_run:
        print("\n(dry-run: no files written — re-run without --dry-run to apply)")


if __name__ == "__main__":
    main()
