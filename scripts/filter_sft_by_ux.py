"""
Filter SFT training data by UX law scores.
==========================================
Reads the raw ShareGPT jsonl, scores each HTML response,
keeps examples above a threshold, reports what was cut and why.

Usage:
    python scripts/filter_sft_by_ux.py
    python scripts/filter_sft_by_ux.py --min-score 60 --input data/training/webgen_pairs_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.webgen.agents.ux_scorer import score_html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/training/webgen_pairs_v1.jsonl")
    parser.add_argument("--output", default=None, help="defaults to <input>_filtered.jsonl")
    parser.add_argument("--min-score", type=int, default=50)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output) if args.output else input_path.with_suffix("").with_name(input_path.stem + "_filtered.jsonl")

    rows = [json.loads(l) for l in input_path.read_text().splitlines() if l.strip()]
    print(f"Loaded {len(rows)} examples from {input_path}")

    kept, dropped = [], []
    score_dist: Counter = Counter()
    violation_counts: Counter = Counter()

    for row in rows:
        convs = row.get("conversations", [])
        html = next((t["value"] for t in convs if t["from"] == "gpt"), "")
        ux = score_html(html)

        bucket = (ux.total // 10) * 10
        score_dist[f"{bucket}-{bucket+9}"] += 1

        row["ux_score"] = ux.total
        row["ux_breakdown"] = {
            "jakob": ux.jakob,
            "hick": ux.hick,
            "proximity": ux.proximity,
            "miller": ux.miller,
            "von_restorff": ux.von_restorff,
        }
        row["ux_violations"] = ux.violations

        for v in ux.violations:
            law = v.split(":")[0] if ":" in v else "other"
            violation_counts[law] += 1

        if ux.total >= args.min_score:
            kept.append(row)
        else:
            dropped.append((ux.total, ux.violations, html[:80]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        for row in kept:
            f.write(json.dumps(row) + "\n")

    print(f"\nResults:")
    print(f"  Kept:    {len(kept)} / {len(rows)} (min score {args.min_score})")
    print(f"  Dropped: {len(dropped)}")
    print(f"  Output:  {output_path}")

    print(f"\nScore distribution:")
    for bucket, count in sorted(score_dist.items()):
        bar = "█" * count
        print(f"  {bucket:6s} | {bar} ({count})")

    print(f"\nTop violations:")
    for law, count in violation_counts.most_common(8):
        print(f"  {count:3d}x  {law}")

    if dropped:
        print(f"\nWorst 5 dropped examples:")
        for score, viols, snippet in sorted(dropped)[:5]:
            print(f"  score={score:3d}  {viols[0] if viols else 'no violations logged'}")
            print(f"           html: {snippet!r}")


if __name__ == "__main__":
    main()
