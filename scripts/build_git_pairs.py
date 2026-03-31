#!/usr/bin/env python3
"""
scripts/build_git_pairs.py
──────────────────────────
Strategy 1: Git commit history → before/after training pairs.

Every commit in this repo is a lesson: something was broken or missing,
then it was fixed or built. This script extracts those diffs and turns
them into ShareGPT Q&A pairs ready for Unsloth fine-tuning.

Modes:
  --raw     Formats diffs directly as pairs (no LLM). Fast, offline.
  --ollama  Sends each diff to Ollama for a richer natural-language explanation.

Usage:
  python scripts/build_git_pairs.py --raw --limit 50
  python scripts/build_git_pairs.py --ollama --limit 100
  python scripts/build_git_pairs.py --raw             # all commits
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Only include code file diffs (skip lock files, images, etc.)
INCLUDE_EXTS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml",
                ".toml", ".html", ".css", ".sh", ".json"}
SKIP_FILENAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml",
                  "poetry.lock", "requirements.txt"}

MAX_DIFF_CHARS = 3_500  # keep prompts within context window


def git(cmd: list[str]) -> str:
    result = subprocess.run(
        ["git"] + cmd, cwd=ROOT, capture_output=True, text=True, errors="ignore"
    )
    return result.stdout.strip()


def get_commits(limit: int) -> list[dict]:
    """Return list of {hash, subject, body} dicts."""
    sep = "|||"
    log = git(["log", f"--format=%H{sep}%s{sep}%b{sep}%ai", f"-{limit}"])
    commits = []
    for line in log.split("\n"):
        parts = line.split(sep)
        if len(parts) >= 2:
            commits.append({
                "hash": parts[0].strip(),
                "subject": parts[1].strip(),
                "body": parts[2].strip() if len(parts) > 2 else "",
                "date": parts[3].strip() if len(parts) > 3 else "",
            })
    return [c for c in commits if c["hash"]]


def get_diff(commit_hash: str) -> tuple[str, list[str]]:
    """Return (filtered_diff, changed_files) for a commit."""
    # Get list of changed files
    files_raw = git(["diff-tree", "--no-commit-id", "-r", "--name-only", commit_hash])
    changed_files = [f for f in files_raw.splitlines() if f.strip()]

    # Filter to code files only
    code_files = [
        f for f in changed_files
        if Path(f).suffix.lower() in INCLUDE_EXTS
        and Path(f).name not in SKIP_FILENAMES
    ]
    if not code_files:
        return "", changed_files

    # Get actual diff, limited to code files
    diff = git(["show", "--no-color", "--stat", commit_hash] + ["--"] + code_files[:10])
    return diff[:MAX_DIFF_CHARS], code_files


def ollama_explain(diff: str, subject: str, files: list[str]) -> str:
    """Ask Ollama to explain the diff as a senior engineer would."""
    try:
        import requests
    except ImportError:
        return f"[Ollama unavailable] {subject}"

    prompt = f"""A developer made a commit with this message: "{subject}"

Here are the files changed: {', '.join(files[:5])}

Here's the code diff:
```
{diff[:2500]}
```

As a senior software engineer, explain:
1. What problem or task this commit addresses
2. The key code changes made and why
3. What a junior dev should learn from this pattern
4. Any gotchas or edge cases to be aware of

Be concrete and technical. Reference specific file names and code patterns."""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a senior software engineer explaining code commits to help train a coding AI assistant. Be technical, specific, and educational.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.5, "num_predict": 600},
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Ollama error: {e}] {subject}"


def build_raw_answer(commit: dict, files: list[str]) -> str:
    """Build a structured answer from commit metadata alone (no LLM)."""
    lines = [f"**Commit:** {commit['subject']}"]
    if commit["body"]:
        lines.append(f"\n**Details:** {commit['body']}")
    lines.append(f"\n**Changed files ({len(files)}):**")
    for f in files[:8]:
        lines.append(f"  - `{f}`")
    if len(files) > 8:
        lines.append(f"  - ... and {len(files) - 8} more")
    lines.append(
        "\n**What this teaches:** Study the diff to understand what was added, "
        "fixed, or refactored. Pay attention to how error handling, "
        "imports, and type annotations evolve across commits."
    )
    return "\n".join(lines)


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def format_question(commit: dict, diff: str, files: list[str]) -> str:
    file_summary = ", ".join(files[:4])
    if len(files) > 4:
        file_summary += f" +{len(files)-4} more"
    return (
        f"Here's a git commit from the Agentop multi-agent system repository.\n\n"
        f"**Commit message:** {commit['subject']}\n"
        f"**Files changed:** {file_summary}\n\n"
        f"```diff\n{diff[:2000]}\n```\n\n"
        f"Explain what this code change accomplishes, why it was needed, "
        f"and what patterns a developer should learn from it."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract git commit pairs for fine-tuning.")
    parser.add_argument("--raw", action="store_true", help="No LLM — use commit metadata as answer")
    parser.add_argument("--ollama", action="store_true", help="Use Ollama to explain each diff")
    parser.add_argument("--limit", type=int, default=0, help="Max commits to process (0 = all)")
    parser.add_argument("--min-diff", type=int, default=100, help="Min diff chars to include (default: 100)")
    args = parser.parse_args()

    if not args.raw and not args.ollama:
        print("Specify --raw or --ollama (or both). Defaulting to --raw.")
        args.raw = True

    limit = args.limit if args.limit > 0 else 9999
    commits = get_commits(limit)
    print(f"[git] Found {len(commits)} commits to process")

    pairs = []
    skipped = 0

    for i, commit in enumerate(commits):
        diff, files = get_diff(commit["hash"])

        if len(diff) < args.min_diff:
            skipped += 1
            continue

        question = format_question(commit, diff, files)

        if args.ollama:
            print(f"  [{i+1:3d}/{len(commits)}] {commit['subject'][:55]}", end="  ", flush=True)
            answer = ollama_explain(diff, commit["subject"], files)
            print(f"→ {len(answer)} chars")
            time.sleep(0.2)
        else:
            answer = build_raw_answer(commit, files)

        pairs.append(pair_to_sharegpt(question, answer))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "ollama" if args.ollama else "raw"
    out_path = OUT_DIR / f"git_pairs_{mode}_{timestamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(pairs)} git pairs → {out_path}")
    print(f"  Skipped {skipped} commits (diff too small or non-code changes)")


if __name__ == "__main__":
    main()
