#!/usr/bin/env python3
"""
scripts/eval_lex.py
───────────────────
Evaluate lex-v2 vs lex-v3 routing accuracy on the held-out eval split.

Sends each message from output/lex-finetune/eval_split.jsonl to both
models via Ollama, compares predicted agent_id against the ground-truth,
and saves a detailed report plus summary to data/benchmarks/.

Usage:
  python scripts/eval_lex.py
  python scripts/eval_lex.py --v2 lex-v2 --v3 lex-v3 --limit 100
  python scripts/eval_lex.py --input data/training/routing.jsonl --limit 50

Environment:
  OLLAMA_HOST   Ollama base URL (default: http://localhost:11434)
  EVAL_TIMEOUT  Per-request timeout in seconds (default: 30)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_EVAL_SPLIT = ROOT / "output" / "lex-finetune" / "eval_split.jsonl"
BENCHMARKS_DIR = ROOT / "data" / "benchmarks"

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
EVAL_TIMEOUT = int(os.getenv("EVAL_TIMEOUT", "30"))

# Valid agent IDs (from copilot-instructions.md)
VALID_AGENTS = {
    "soul_core",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "cs_agent",
    "it_agent",
    "knowledge_agent",
    "BLOCKED",
}


# ══════════════════════════════════════════════════════════════════════════
# Ollama client
# ══════════════════════════════════════════════════════════════════════════


def query_ollama(model: str, prompt: str, timeout: int = EVAL_TIMEOUT) -> str:
    """Send a prompt to an Ollama model and return the response text."""
    import urllib.error
    import urllib.request

    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            return data.get("response", "").strip()
    except urllib.error.URLError as e:
        return f"ERROR: {e}"
    except TimeoutError:
        return "ERROR: timeout"


def extract_agent_id(response: str) -> str | None:
    """Extract agent_id from a model response.

    Handles both JSON responses and plain-text agent names.
    """
    # Try JSON first
    try:
        obj = json.loads(response)
        return obj.get("agent_id") or obj.get("agent")
    except (json.JSONDecodeError, AttributeError):
        pass

    # Try JSON embedded in text
    match = re.search(r'"agent_id"\s*:\s*"([^"]+)"', response)
    if match:
        return match.group(1)

    # Try plain agent name on a line
    for line in response.splitlines():
        candidate = line.strip().lower().replace("-", "_")
        if candidate in VALID_AGENTS:
            return candidate

    return None


# ══════════════════════════════════════════════════════════════════════════
# Eval helpers
# ══════════════════════════════════════════════════════════════════════════

ROUTING_PROMPT_TEMPLATE = """\
You are Lex, the Agentop router. Given the user message below, respond with \
a JSON object containing "agent_id" (one of: {agents}) and "reasoning" (brief).

User message: {message}"""


def build_routing_prompt(message: str) -> str:
    agents_list = ", ".join(sorted(VALID_AGENTS - {"BLOCKED"})) + ", BLOCKED"
    return ROUTING_PROMPT_TEMPLATE.format(agents=agents_list, message=message)


def load_eval_records(path: Path, limit: int | None = None) -> list[dict]:
    """Load evaluation records from a JSONL file.

    Supports:
    - ShareGPT format: {"conversations": [{"from": "human", "value": "..."}, ...]}
    - Routing format:  {"user_message": "...", "expected_agent": "..."}
    """
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                records.append(obj)
            except json.JSONDecodeError:
                continue
            if limit and len(records) >= limit:
                break
    return records


def extract_message_and_expected(record: dict) -> tuple[str | None, str | None]:
    """Extract (user_message, expected_agent) from a record in any known format."""
    # Direct routing format
    if "user_message" in record:
        return record["user_message"], record.get("expected_agent")

    # ShareGPT format — first human turn is the message,
    # look for expected_agent in metadata
    convs = record.get("conversations", [])
    if convs:
        first_human = next((c["value"] for c in convs if c.get("from") == "human"), None)
        expected = record.get("expected_agent") or record.get("metadata", {}).get("expected_agent")
        return first_human, expected

    return None, None


# ══════════════════════════════════════════════════════════════════════════
# Main eval loop
# ══════════════════════════════════════════════════════════════════════════


def run_eval(
    v2_model: str,
    v3_model: str,
    input_path: Path,
    limit: int | None,
    skip_v2: bool,
    skip_v3: bool,
) -> dict:
    """Run evaluation and return results dict."""
    records = load_eval_records(input_path, limit)
    if not records:
        print(f"[ERROR] No records found in {input_path}")
        sys.exit(1)

    print(f"Loaded {len(records)} eval records from {input_path.name}")
    print(f"Models: v2={v2_model}  v3={v3_model}\n")

    results = []
    v2_correct = 0
    v3_correct = 0
    v2_total = 0
    v3_total = 0

    for i, record in enumerate(records, 1):
        message, expected = extract_message_and_expected(record)
        if not message:
            continue

        prompt = build_routing_prompt(message)
        row: dict = {"index": i, "user_message": message, "expected": expected}

        # Query v2
        if not skip_v2:
            t0 = time.monotonic()
            v2_resp = query_ollama(v2_model, prompt)
            v2_latency = time.monotonic() - t0
            v2_pred = extract_agent_id(v2_resp)
            v2_match = expected and v2_pred and (v2_pred == expected)
            row["v2"] = {
                "predicted": v2_pred,
                "match": bool(v2_match),
                "latency_ms": round(v2_latency * 1000),
                "raw_response": v2_resp[:200],
            }
            v2_total += 1
            if v2_match:
                v2_correct += 1

        # Query v3
        if not skip_v3:
            t0 = time.monotonic()
            v3_resp = query_ollama(v3_model, prompt)
            v3_latency = time.monotonic() - t0
            v3_pred = extract_agent_id(v3_resp)
            v3_match = expected and v3_pred and (v3_pred == expected)
            row["v3"] = {
                "predicted": v3_pred,
                "match": bool(v3_match),
                "latency_ms": round(v3_latency * 1000),
                "raw_response": v3_resp[:200],
            }
            v3_total += 1
            if v3_match:
                v3_correct += 1

        results.append(row)

        # Progress
        v2_acc = f"{v2_correct}/{v2_total} ({100*v2_correct/v2_total:.0f}%)" if v2_total else "—"
        v3_acc = f"{v3_correct}/{v3_total} ({100*v3_correct/v3_total:.0f}%)" if v3_total else "—"
        v2_pred_str = row.get("v2", {}).get("predicted", "—")
        v3_pred_str = row.get("v3", {}).get("predicted", "—")
        status = "✓" if row.get("v3", {}).get("match") or row.get("v2", {}).get("match") else "✗"
        print(
            f"  [{i:3d}/{len(records)}] {status}  expected={expected or '?':20s} | "
            f"v2={v2_pred_str or '?':20s} | v3={v3_pred_str or '?':20s} | "
            f"acc v2={v2_acc}  v3={v3_acc}"
        )

    summary = {
        "timestamp": datetime.now(UTC).isoformat(),
        "eval_file": str(input_path),
        "n_records": len(results),
        "v2_model": v2_model,
        "v3_model": v3_model,
        "v2_accuracy": round(v2_correct / v2_total, 4) if v2_total else None,
        "v3_accuracy": round(v3_correct / v3_total, 4) if v3_total else None,
        "v2_correct": v2_correct,
        "v3_correct": v3_correct,
        "v2_total": v2_total,
        "v3_total": v3_total,
        "delta_accuracy": round(
            (v3_correct / v3_total) - (v2_correct / v2_total), 4
        )
        if (v2_total and v3_total)
        else None,
    }

    return {"summary": summary, "results": results}


# ══════════════════════════════════════════════════════════════════════════
# Output
# ══════════════════════════════════════════════════════════════════════════


def save_results(data: dict) -> None:
    BENCHMARKS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y%m%d_%H%M")

    detail_path = BENCHMARKS_DIR / f"lex_v2_vs_v3_{date_str}.jsonl"
    summary_path = BENCHMARKS_DIR / "lex_eval_summary.json"

    with open(detail_path, "w") as f:
        for row in data["results"]:
            json.dump(row, f)
            f.write("\n")

    with open(summary_path, "w") as f:
        json.dump(data["summary"], f, indent=2)

    print(f"\n  ✓ Detail report → {detail_path}")
    print(f"  ✓ Summary        → {summary_path}")


def print_summary(summary: dict) -> None:
    print("\n" + "═" * 60)
    print("  EVAL SUMMARY")
    print("═" * 60)
    print(f"  Records evaluated : {summary['n_records']}")
    if summary.get("v2_accuracy") is not None:
        print(f"  lex-v2 accuracy   : {summary['v2_accuracy']*100:.1f}%  ({summary['v2_correct']}/{summary['v2_total']})")
    if summary.get("v3_accuracy") is not None:
        print(f"  lex-v3 accuracy   : {summary['v3_accuracy']*100:.1f}%  ({summary['v3_correct']}/{summary['v3_total']})")
    if summary.get("delta_accuracy") is not None:
        delta = summary["delta_accuracy"]
        sign = "+" if delta >= 0 else ""
        print(f"  Δ accuracy        : {sign}{delta*100:.1f}%  (v3 vs v2)")
    print("═" * 60)


# ══════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Evaluate lex-v2 vs lex-v3 routing accuracy")
    p.add_argument("--v2", default="lex-v2", help="Ollama model name for lex-v2 (default: lex-v2)")
    p.add_argument("--v3", default="lex-v3", help="Ollama model name for lex-v3 (default: lex-v3)")
    p.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_EVAL_SPLIT,
        help=f"Path to eval JSONL (default: {DEFAULT_EVAL_SPLIT})",
    )
    p.add_argument("--limit", type=int, default=None, help="Max records to evaluate")
    p.add_argument("--skip-v2", action="store_true", help="Skip v2 evaluation (v3 only)")
    p.add_argument("--skip-v3", action="store_true", help="Skip v3 evaluation (v2 only)")
    p.add_argument("--no-save", action="store_true", help="Print results but don't save files")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if not args.input.exists():
        print(f"[ERROR] Eval file not found: {args.input}")
        print("  Run 'python scripts/finetune_lex.py --prep-only' to generate it.")
        sys.exit(1)

    data = run_eval(
        v2_model=args.v2,
        v3_model=args.v3,
        input_path=args.input,
        limit=args.limit,
        skip_v2=args.skip_v2,
        skip_v3=args.skip_v3,
    )

    print_summary(data["summary"])

    if not args.no_save:
        save_results(data)


if __name__ == "__main__":
    main()
