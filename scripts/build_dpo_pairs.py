#!/usr/bin/env python3
"""
Strategy 9 — DPO (Direct Preference Optimization) Preference Pairs
============================================================
Takes existing training pairs (the "good" answers) and uses Ollama
to generate a "rejected" version (vague, incomplete, unhelpful).

Output format:
  {"prompt": "...", "chosen": "...", "rejected": "..."}

DPO trains the model to prefer `chosen` over `rejected`, making it
less likely to give lazy/vague answers.

Usage:
  python scripts/build_dpo_pairs.py               # from combined JSONL
  python scripts/build_dpo_pairs.py --limit 30    # limit pairs processed
  python scripts/build_dpo_pairs.py --source data/training/spec_pairs*.jsonl
  python scripts/build_dpo_pairs.py --raw         # use rule-based rejected (no LLM)
"""

import argparse
import glob
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from datetime import datetime

import requests

# ---------------------------------------------------------------------------
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
OUT_DIR      = Path("data/training")
OUT_DPO      = Path("data/dpo")

OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_DPO.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ollama_chat(prompt: str, system: str = "", max_tokens: int = 600) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model":    OLLAMA_MODEL,
                "messages": messages,
                "stream":   False,
                "options":  {"num_predict": max_tokens, "temperature": 0.8},
            },
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Ollama error: {e}]"


def load_source_pairs(pattern: str | None, limit: int) -> list[dict]:
    """Load SFT pairs from JSONL files, excluding combined/dpo files."""
    if pattern:
        files = sorted(glob.glob(pattern))
    else:
        files = sorted(OUT_DIR.glob("*.jsonl"))
        # skip combined outputs and any dpo files
        files = [f for f in files if "combined" not in f.name and "dpo" not in f.name]

    pairs = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    convs = rec.get("conversations", [])
                    if len(convs) >= 2:
                        human = next((c["value"] for c in convs if c["from"] == "human"), None)
                        gpt   = next((c["value"] for c in convs if c["from"] == "gpt"),   None)
                        if human and gpt and len(gpt) > 100:
                            pairs.append({"prompt": human, "chosen": gpt, "_source": str(f)})
                except json.JSONDecodeError:
                    pass

    random.shuffle(pairs)
    return pairs[:limit]


# ---------------------------------------------------------------------------
# Rejected response generators
# ---------------------------------------------------------------------------

_DEGRADATION_PROMPTS = [
    # vague non-answer
    "Give a very vague, one-sentence answer to this question that doesn't actually help: {q}",
    # wrong methodology  
    "Answer this question but suggest an incorrect or suboptimal approach: {q}",
    # over-generic
    "Answer this question as if you know nothing specific about the codebase or technology, giving only generic advice: {q}",
    # missing code
    "Answer this question with only prose, no code examples, and be brief (2-3 sentences): {q}",
]


def generate_rejected_ollama(prompt: str) -> str:
    """Ask Ollama to generate a degraded/unhelpful version of the answer."""
    style = random.choice(_DEGRADATION_PROMPTS).format(q=prompt)
    system = (
        "You are generating INTENTIONALLY POOR answers for machine learning training data. "
        "The goal is to create 'rejected' responses that are vague, incomplete, or misleading "
        "so a model can learn to avoid them. Do NOT be helpful — be brief and uninformative."
    )
    return ollama_chat(style, system=system, max_tokens=150)


def generate_rejected_raw(prompt: str, chosen: str) -> str:
    """
    Rule-based degradation — no LLM needed.
    Takes the chosen answer and strips out the most informative parts.
    """
    lines = chosen.split("\n")

    # Remove code blocks entirely
    in_code = False
    clean_lines = []
    for line in lines:
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        clean_lines.append(line)

    # Take only first 2 non-empty sentences of the remaining prose
    prose = " ".join(clean_lines).strip()
    # Split on sentence boundaries
    sentences = re.split(r"(?<=[.!?])\s+", prose)
    sentences = [s for s in sentences if len(s.strip()) > 20]

    if len(sentences) >= 2:
        degraded = " ".join(sentences[:2])
    elif sentences:
        degraded = sentences[0]
    else:
        degraded = "This depends on your implementation. Check the documentation for details."

    # Cap at 200 chars to ensure it's clearly less informative than chosen
    if len(degraded) > 200:
        degraded = degraded[:200].rsplit(" ", 1)[0] + "..."

    return degraded


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def build_dpo_pairs(
    source_pattern: str | None,
    limit: int,
    use_raw: bool,
    verbose: bool,
) -> list[dict]:
    pairs = load_source_pairs(source_pattern, limit)
    if not pairs:
        print("No source pairs found. Run data collection scripts first.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(pairs)} source pairs → generating rejected responses...")
    dpo_pairs = []

    for i, p in enumerate(pairs):
        prompt  = p["prompt"]
        chosen  = p["chosen"]
        source  = p["_source"]

        if use_raw:
            rejected = generate_rejected_raw(prompt, chosen)
        else:
            rejected = generate_rejected_ollama(prompt)
            time.sleep(0.3)  # gentle rate limiting

        # Skip if rejected is too similar to chosen (raw mode edge case)
        if rejected.strip() == chosen.strip()[:len(rejected.strip())]:
            rejected = generate_rejected_raw(prompt, chosen)

        entry = {
            "prompt":   prompt,
            "chosen":   chosen,
            "rejected": rejected,
        }
        dpo_pairs.append(entry)

        if verbose:
            print(f"\n[{i+1}/{len(pairs)}] source: {Path(source).name}")
            print(f"  PROMPT:   {prompt[:80]}...")
            print(f"  CHOSEN:   {chosen[:80]}...")
            print(f"  REJECTED: {rejected[:80]}...")
        else:
            status = "raw" if use_raw else "ollama"
            print(f"  [{i+1}/{len(pairs)}] {status} → {len(rejected)} chars rejected", end="\r")

    if not verbose:
        print()

    return dpo_pairs


# ---------------------------------------------------------------------------
# Quality check
# ---------------------------------------------------------------------------

def quality_check(dpo_pairs: list[dict]) -> dict:
    """Ensure chosen is always significantly better than rejected."""
    issues = 0
    for p in dpo_pairs:
        c_len = len(p["chosen"])
        r_len = len(p["rejected"])
        # Good rejected answers should be clearly shorter/worse
        if r_len >= c_len * 0.7:
            issues += 1

    return {
        "total":          len(dpo_pairs),
        "quality_issues": issues,
        "avg_chosen_len": int(sum(len(p["chosen"]) for p in dpo_pairs) / len(dpo_pairs)) if dpo_pairs else 0,
        "avg_reject_len": int(sum(len(p["rejected"]) for p in dpo_pairs) / len(dpo_pairs)) if dpo_pairs else 0,
        "ratio_ok":       issues == 0,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Build DPO preference pairs (Strategy 9)")
    parser.add_argument("--source",  default=None,  help="Glob pattern for source JSONL files")
    parser.add_argument("--limit",   type=int, default=50,  help="Max pairs to process (default 50)")
    parser.add_argument("--raw",     action="store_true",   help="Use rule-based rejection (no Ollama)")
    parser.add_argument("--verbose", action="store_true",   help="Show each pair as it's generated")
    parser.add_argument("--check",   action="store_true",   help="Quality check only (no generation)")
    args = parser.parse_args()

    # Quality check existing file
    if args.check:
        existing = sorted(OUT_DPO.glob("dpo_pairs_*.jsonl"))
        if not existing:
            print("No DPO files found. Run without --check first.")
            return
        latest = existing[-1]
        pairs = [json.loads(l) for l in open(latest) if l.strip()]
        stats = quality_check(pairs)
        print(f"\nDPO Quality Check: {latest.name}")
        print(f"  Total pairs:      {stats['total']}")
        print(f"  Avg chosen len:   {stats['avg_chosen_len']} chars")
        print(f"  Avg rejected len: {stats['avg_reject_len']} chars")
        print(f"  Issues (too similar): {stats['quality_issues']}")
        ratio = stats['avg_chosen_len'] / max(stats['avg_reject_len'], 1)
        print(f"  Chosen/Rejected ratio: {ratio:.1f}x  {'✓ Good' if ratio >= 2.0 else '⚠ Too similar'}")
        return

    dpo_pairs = build_dpo_pairs(
        source_pattern=args.source,
        limit=args.limit,
        use_raw=args.raw,
        verbose=args.verbose,
    )

    # Save
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = OUT_DPO / f"dpo_pairs_{timestamp}.jsonl"
    with open(out_file, "w") as f:
        for entry in dpo_pairs:
            f.write(json.dumps(entry) + "\n")

    # Stats
    stats = quality_check(dpo_pairs)
    ratio = stats["avg_chosen_len"] / max(stats["avg_reject_len"], 1)

    print(f"\n{'='*55}")
    print(f"  DPO Pairs Generated: {stats['total']}")
    print(f"  Avg chosen length:   {stats['avg_chosen_len']} chars")
    print(f"  Avg rejected length: {stats['avg_reject_len']} chars")
    print(f"  Quality ratio:       {ratio:.1f}x  {'✓' if ratio >= 2.0 else '⚠ run --check'}")
    print(f"  Saved to:            {out_file}")
    print(f"{'='*55}")
    print()
    print("Next steps:")
    print("  python scripts/build_dpo_pairs.py --check   # quality review")
    print("  python scripts/train_dpo.py                 # train with DPO")
    print()
    print("DPO trains the model to PREFER chosen over rejected — this is")
    print("how alignment works (same idea as RLHF but simpler).")


if __name__ == "__main__":
    main()
