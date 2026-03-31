#!/usr/bin/env python3
"""
scripts/build_pytest_pairs.py
──────────────────────────────
Strategy 2: Real pytest failures → error diagnosis + fix pairs.

Runs the test suite, captures actual failures with full tracebacks,
reads the failing source code, and creates fine-tuning pairs that teach
the model how to diagnose and fix real errors from this codebase.

Modes:
  --raw          Capture failures and format with traceback context (no LLM)
  --ollama       Send each failure to Ollama for diagnosis + proposed fix
  --multi-turn   Create multi-turn debug conversations (needs --ollama)

Usage:
  python scripts/build_pytest_pairs.py --raw
  python scripts/build_pytest_pairs.py --ollama
  python scripts/build_pytest_pairs.py --ollama --multi-turn
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")


# ── pytest runner ──────────────────────────────────────────────────────────────

def run_pytest(test_dir: str = "backend/tests") -> str:
    """Run pytest and return full stdout."""
    print(f"[pytest] Running tests in {test_dir}...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", test_dir, "-v", "--tb=short", "-q",
         "--no-header", "--color=no", "--timeout=30"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        errors="ignore",
        timeout=300,
    )
    return result.stdout + result.stderr


# ── failure parser ─────────────────────────────────────────────────────────────

def parse_failures(output: str) -> list[dict]:
    """Parse pytest output and extract structured failure info."""
    failures = []
    # Split on FAILED or ERROR sections
    # pytest --tb=short format: === FAILURES === then ____test_name____ blocks
    failure_blocks = re.split(r"_{10,}", output)

    current_fail: Optional[dict] = None

    for block in failure_blocks:
        block = block.strip()
        if not block:
            continue

        # Header line: "test_module.py::TestClass::test_function"
        lines = block.splitlines()
        if not lines:
            continue

        header = lines[0].strip()
        # Match test path patterns
        test_match = re.search(
            r"([\w/]+\.py)::([\w]+)(?:::([\w]+))?",
            header
        )
        if not test_match and current_fail is None:
            continue

        if test_match:
            current_fail = {
                "test_file": test_match.group(1),
                "test_class": test_match.group(2),
                "test_name": test_match.group(3) or test_match.group(2),
                "traceback": "\n".join(lines[1:]),
                "error_type": "",
                "error_message": "",
            }
            # Find error type from traceback
            for line in reversed(lines):
                err_match = re.match(r"([\w.]+Error|[\w.]+Exception|AssertionError): (.+)", line.strip())
                if err_match:
                    current_fail["error_type"] = err_match.group(1)
                    current_fail["error_message"] = err_match.group(2)[:200]
                    break
            failures.append(current_fail)
        elif current_fail and block:
            # Continuation block — add to traceback
            current_fail["traceback"] += "\n" + block

    return failures[:50]  # cap for safety


def read_test_source(test_file: str, test_name: str) -> str:
    """Read the relevant test function from the test file."""
    try:
        path = ROOT / test_file
        if not path.exists():
            return ""
        source = path.read_text(encoding="utf-8", errors="ignore")
        # Try to extract just the test function
        lines = source.splitlines()
        start = -1
        end = len(lines)
        for i, line in enumerate(lines):
            if re.match(rf"\s*def {re.escape(test_name)}\s*\(", line):
                start = i
            elif start >= 0 and i > start and re.match(r"\s*def \w+\s*\(", line):
                end = i
                break
        if start >= 0:
            return "\n".join(lines[start:end])[:1500]
        return source[:1500]
    except Exception:
        return ""


# ── Ollama call ────────────────────────────────────────────────────────────────

def ollama_diagnose(failure: dict, source: str) -> str:
    """Ask Ollama to explain the failure and propose a fix."""
    try:
        import requests
    except ImportError:
        return build_raw_answer(failure, source)

    prompt = f"""A pytest test is failing. Here's the failure information:

**Test:** `{failure['test_file']}::{failure['test_name']}`
**Error type:** `{failure['error_type'] or 'Unknown'}`
**Error message:** `{failure['error_message'] or 'See traceback'}`

**Traceback:**
```
{failure['traceback'][:1500]}
```

**Test source code:**
```python
{source[:800]}
```

Diagnose the root cause of this failure and explain:
1. Why the test is failing (root cause, not just symptoms)
2. The exact code change needed to fix it
3. How to prevent this type of error in the future
4. If it's a test-side issue vs a code-side issue

Provide a concrete, actionable answer with code examples where relevant."""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a senior Python engineer debugging test failures. Give precise, actionable diagnoses with concrete code fixes.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 700},
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Ollama error: {e}]\n\n{build_raw_answer(failure, source)}"


def build_raw_answer(failure: dict, source: str) -> str:
    """Build a structured answer from failure metadata (no LLM)."""
    parts = [
        f"**Error Type:** `{failure['error_type'] or 'Unknown'}`",
        f"**Error Message:** {failure['error_message'] or 'See traceback below'}",
        f"\n**Traceback:**\n```\n{failure['traceback'][:800]}\n```",
    ]
    if source:
        parts.append(f"\n**Test Source:**\n```python\n{source[:600]}\n```")
    parts.append(
        "\n**Debugging approach:**\n"
        "1. Read the error type — it tells you the category of problem\n"
        "2. Follow the traceback from bottom to top — the bottom line is where it crashed\n"
        "3. Check if it's an assertion failure (expected vs actual mismatch) or an exception\n"
        "4. Look at the test's setup (fixtures, mocks) if the error is in unexpected code\n"
        "5. Run the test in isolation: `pytest <file>::<test_name> -v --tb=long`"
    )
    return "\n".join(parts)


def build_multi_turn(failure: dict, source: str, explanation: str) -> dict:
    """Create a 3-turn debugging conversation."""
    return {
        "conversations": [
            {
                "from": "human",
                "value": f"My pytest test is failing:\n\n```\n{failure['traceback'][:800]}\n```\n\nWhat's going wrong?"
            },
            {
                "from": "gpt",
                "value": f"Looking at the traceback, the issue is a `{failure['error_type'] or 'test failure'}`. {explanation[:400]}"
            },
            {
                "from": "human",
                "value": "Can you show me exactly how to fix it?"
            },
            {
                "from": "gpt",
                "value": explanation
            }
        ]
    }


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Pytest failures → fine-tuning pairs.")
    parser.add_argument("--raw", action="store_true", help="No LLM — format traceback as answer")
    parser.add_argument("--ollama", action="store_true", help="Use Ollama to diagnose failures")
    parser.add_argument("--multi-turn", action="store_true", help="Create multi-turn debug conversations")
    parser.add_argument("--test-dir", default="backend/tests", help="Test directory to run")
    args = parser.parse_args()

    if not args.raw and not args.ollama:
        print("Defaulting to --raw mode.")
        args.raw = True

    # Run tests
    output = run_pytest(args.test_dir)
    failures = parse_failures(output)

    # Count total tests from output
    summary_match = re.search(r"(\d+) passed,? ?(\d+)? failed?", output)
    total_match = re.search(r"(\d+) failed", output)
    n_failed = int(total_match.group(1)) if total_match else len(failures)

    print(f"[pytest] {n_failed} failures detected, {len(failures)} parsed with context")

    if not failures:
        print("[info] No failures found — all tests passing! Creating a 'test suite healthy' pair.")
        pairs = [pair_to_sharegpt(
            "How do I know if the Agentop test suite is healthy?",
            f"Run `pytest backend/tests/ -v` — all {output.count('PASSED')} tests pass. "
            "The test suite covers native tools, Ollama client, knowledge store, and agent orchestration. "
            "A healthy run shows green across all modules with no failures or warnings about missing fixtures."
        )]
    else:
        pairs = []
        for i, failure in enumerate(failures):
            source = read_test_source(failure["test_file"], failure["test_name"])
            question = (
                f"This pytest test in `{failure['test_file']}` is failing:\n\n"
                f"```python\n{source[:600] if source else '# test source not found'}\n```\n\n"
                f"**Error:**\n```\n{failure['traceback'][:800]}\n```\n\n"
                f"What is the root cause and how do I fix it?"
            )

            if args.ollama:
                print(f"  [{i+1:2d}/{len(failures)}] {failure['test_name'][:50]}", end="  ", flush=True)
                explanation = ollama_diagnose(failure, source)
                print(f"→ {len(explanation)} chars")
                time.sleep(0.2)
            else:
                explanation = build_raw_answer(failure, source)

            if args.multi_turn and args.ollama:
                pairs.append(build_multi_turn(failure, source, explanation))
            else:
                pairs.append(pair_to_sharegpt(question, explanation))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "ollama" if args.ollama else "raw"
    out_path = OUT_DIR / f"pytest_pairs_{mode}_{timestamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(pairs)} pytest pairs → {out_path}")


if __name__ == "__main__":
    main()
