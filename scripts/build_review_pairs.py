#!/usr/bin/env python3
"""
scripts/build_review_pairs.py
──────────────────────────────
Strategy 4: Code review pairs — bad/smelly code → refactored version.

Scans Python files in backend/, detects common issues (functions >50 lines,
broad except clauses, missing type hints, deeply nested logic), and creates
before/after training pairs.

Modes:
  --raw     Flag issues and generate teaching notes (no LLM)
  --ollama  Ask Ollama to write the improved version

Usage:
  python scripts/build_review_pairs.py --raw
  python scripts/build_review_pairs.py --ollama
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

SCAN_DIRS = ["backend/agents", "backend/tools", "backend/routes", "backend/orchestrator"]
SKIP_DIRS = {"__pycache__", "tests", ".venv"}


# ── code smell detectors ───────────────────────────────────────────────────────

def detect_smells(source: str, filepath: str) -> list[dict]:
    """Detect code quality issues in a Python source file."""
    issues = []
    lines = source.splitlines()

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return issues

    for node in ast.walk(tree):
        # Long function (>50 lines)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            func_lines = (node.end_lineno or node.lineno) - node.lineno
            if func_lines > 50:
                start = max(0, node.lineno - 1)
                end = min(len(lines), node.lineno + 60)
                issues.append({
                    "type": "long_function",
                    "name": node.name,
                    "line": node.lineno,
                    "length": func_lines,
                    "snippet": "\n".join(lines[start:end]),
                    "description": f"Function `{node.name}` is {func_lines} lines long — consider splitting into smaller functions",
                })

        # Broad except clause
        if isinstance(node, ast.ExceptHandler):
            if node.type is None:
                start = max(0, node.lineno - 3)
                end = min(len(lines), node.lineno + 8)
                issues.append({
                    "type": "broad_except",
                    "name": "except:",
                    "line": node.lineno,
                    "length": 0,
                    "snippet": "\n".join(lines[start:end]),
                    "description": "Bare `except:` clause catches everything including KeyboardInterrupt and SystemExit — use `except Exception:` or more specific types",
                })

        # Missing return type annotation on public functions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and node.returns is None:
                start = max(0, node.lineno - 1)
                end = min(len(lines), node.lineno + 15)
                issues.append({
                    "type": "missing_return_type",
                    "name": node.name,
                    "line": node.lineno,
                    "length": 0,
                    "snippet": "\n".join(lines[start:end]),
                    "description": f"Public function `{node.name}` missing return type annotation — add `-> ReturnType:` for type safety",
                })

    # Deeply nested code (4+ levels of indentation)
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if indent >= 16 and stripped and not stripped.startswith("#"):  # 4 levels = 16 spaces
            issues.append({
                "type": "deep_nesting",
                "name": f"line {i+1}",
                "line": i + 1,
                "length": 0,
                "snippet": "\n".join(lines[max(0, i-5):min(len(lines), i+5)]),
                "description": f"Deep nesting at line {i+1} — consider early returns or extracting helper functions",
            })
            break  # only flag once per file

    return issues[:3]  # limit to 3 per file to avoid repetition


# ── pair builders ──────────────────────────────────────────────────────────────

def build_raw_review(issue: dict, filepath: str) -> tuple[str, str]:
    """Build Q/A pair from code smell without LLM."""
    question = (
        f"Review this Python code from `{filepath}` and identify any issues:\n\n"
        f"```python\n{issue['snippet'][:1200]}\n```\n\n"
        f"What problems do you see and how should it be improved?"
    )
    answer = (
        f"**Issue Found: {issue['type'].replace('_', ' ').title()}**\n\n"
        f"{issue['description']}\n\n"
        f"**Location:** `{filepath}` at line {issue['line']}\n\n"
        f"**How to fix:**\n"
    )

    if issue["type"] == "long_function":
        answer += (
            f"Break `{issue['name']}` into smaller focused functions:\n"
            f"1. Extract validation logic into a `_validate_*` helper\n"
            f"2. Extract the core business logic into a separate function\n"
            f"3. Keep the main function as an orchestrator under 20 lines\n"
            f"4. Each extracted function should have a single clear responsibility\n\n"
            f"**Rule of thumb:** If a function needs sections with comments to explain "
            f"what's happening, those sections should be separate functions."
        )
    elif issue["type"] == "broad_except":
        answer += (
            f"Replace `except:` with `except Exception as e:` at minimum:\n"
            f"```python\n"
            f"# Before (dangerous)\n"
            f"try:\n    result = risky_operation()\nexcept:\n    pass\n\n"
            f"# After (safe)\n"
            f"try:\n    result = risky_operation()\n"
            f"except ValueError as e:\n    logger.warning(f'Validation error: {{e}}')\n    return None\n"
            f"except Exception as e:\n    logger.error(f'Unexpected error: {{e}}', exc_info=True)\n    raise\n"
            f"```\n\n"
            f"Log the exception so you can debug it. Don't silently swallow errors."
        )
    elif issue["type"] == "missing_return_type":
        answer += (
            f"Add return type annotation to `{issue['name']}`:\n"
            f"```python\n"
            f"# Before\ndef {issue['name']}(...):\n    ...\n\n"
            f"# After\nfrom typing import Optional\ndef {issue['name']}(...) -> Optional[str]:  # or dict, list, None etc\n    ...\n"
            f"```\n\n"
            f"With `pyright` or `mypy`, type annotations catch bugs at edit time rather than runtime. "
            f"The entire Agentop backend uses `pyrightconfig.json` for type checks."
        )
    elif issue["type"] == "deep_nesting":
        answer += (
            f"Flatten the nesting using early returns (guard clauses):\n"
            f"```python\n"
            f"# Before (4 levels deep)\n"
            f"def process(data):\n    if data:\n        if data.get('key'):\n            if validate(data['key']):\n                result = compute(data['key'])\n                return result\n"
            f"\n# After (flat with guard clauses)\n"
            f"def process(data) -> Optional[Result]:\n    if not data:\n        return None\n"
            f"    if not data.get('key'):\n        return None\n"
            f"    if not validate(data['key']):\n        return None\n"
            f"    return compute(data['key'])\n"
            f"```\n\n"
            f"The flat version is easier to read, test, and extend."
        )

    return question, answer


def ollama_review(issue: dict, filepath: str) -> tuple[str, str]:
    """Ask Ollama to write an improved version of the problematic code."""
    question = (
        f"Review this Python code from `{filepath}` (a FastAPI/LangGraph backend):\n\n"
        f"```python\n{issue['snippet'][:1200]}\n```\n\n"
        f"Identified issue: {issue['description']}\n\n"
        f"Show the refactored version with an explanation of each improvement."
    )
    try:
        import requests
    except ImportError:
        q, a = build_raw_review(issue, filepath)
        return question, a

    prompt = f"""Review this Python code from a production FastAPI service:

```python
{issue['snippet'][:1200]}
```

Issue identified: {issue['description']}

Provide:
1. A clear explanation of why this is a problem
2. The refactored version with TypeScript annotations, proper error handling, and clean structure
3. Key principles demonstrated (single responsibility, fail fast, etc.)

Use Agentop conventions: Pydantic for models, structured logging, `ToolResult` for tool returns."""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are a senior Python engineer doing code review for a production AI service. Give practical, actionable feedback with concrete refactored code.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 700},
    }
    try:
        import requests as req
        resp = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=90)
        resp.raise_for_status()
        answer = resp.json()["message"]["content"].strip()
        return question, answer
    except Exception as e:
        q, a = build_raw_review(issue, filepath)
        return question, a


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Code review pairs for fine-tuning.")
    parser.add_argument("--raw", action="store_true", help="Teach review patterns (no LLM)")
    parser.add_argument("--ollama", action="store_true", help="Refactored version via Ollama")
    parser.add_argument("--max-files", type=int, default=30, help="Max files to scan")
    args = parser.parse_args()

    if not args.raw and not args.ollama:
        print("Defaulting to --raw mode.")
        args.raw = True

    # Scan Python files
    py_files = []
    for dir_rel in SCAN_DIRS:
        d = ROOT / dir_rel
        if d.exists():
            for f in d.rglob("*.py"):
                if not any(skip in f.parts for skip in SKIP_DIRS):
                    py_files.append(f)

    py_files = py_files[:args.max_files]
    print(f"[review] Scanning {len(py_files)} Python files for code smells")

    all_issues = []
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            if not source.strip():
                continue
            rel = str(path.relative_to(ROOT))
            smells = detect_smells(source, rel)
            for smell in smells:
                all_issues.append((rel, smell))
        except Exception:
            continue

    print(f"[review] Found {len(all_issues)} code smell instances")

    pairs = []
    for i, (filepath, issue) in enumerate(all_issues):
        if args.ollama:
            print(f"  [{i+1:2d}/{len(all_issues)}] {filepath:<50} [{issue['type']}]", end="  ", flush=True)
            q, a = ollama_review(issue, filepath)
            print(f"→ {len(a)} chars")
            time.sleep(0.2)
        else:
            q, a = build_raw_review(issue, filepath)
            print(f"  [{i+1:2d}/{len(all_issues)}] {filepath:<50} [{issue['type']}]")

        pairs.append(pair_to_sharegpt(q, a))

    if not pairs:
        print("[info] No code smells found — codebase is clean! Creating a best-practices pair.")
        pairs = [pair_to_sharegpt(
            "What Python coding standards does Agentop enforce?",
            "Agentop enforces production Python standards: Pydantic models for all API contracts, "
            "explicit return types on all public functions, specific exception handlers (never bare `except:`), "
            "functions under 50 lines with single responsibilities, and structured logging via `get_logger(__name__)`. "
            "Tooling: `ruff` for linting, `pyright` for type checking, `pytest` with >60% coverage requirement. "
            "See `pyrightconfig.json` and `.github/prompts/python-patterns.prompt.md` for the full spec."
        )]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "ollama" if args.ollama else "raw"
    out_path = OUT_DIR / f"review_pairs_{mode}_{timestamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(pairs)} review pairs → {out_path}")


if __name__ == "__main__":
    main()
