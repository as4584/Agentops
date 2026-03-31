#!/usr/bin/env python3
"""
scripts/eval_model.py
─────────────────────────────────────────────────────────────────────────────
Benchmark your Ollama model against a fixed eval set.
Run this BEFORE and AFTER fine-tuning to see the improvement.

Metrics tracked per run:
  • Response length (richness)
  • Code inclusion rate
  • Agentop-specific term accuracy (does it mention the right architecture terms?)
  • Response latency
  • Overall eval score 0–100

Results are saved to data/eval/eval_<model>_<timestamp>.json so you can
compare runs over time.

Usage:
  # Benchmark base model (before fine-tuning)
  python scripts/eval_model.py --model llama3.2

  # After fine-tuning, benchmark your custom model
  python scripts/eval_model.py --model lex_7b

  # Compare two model runs side by side
  python scripts/eval_model.py --compare

  # Show all historical eval scores
  python scripts/eval_model.py --history
"""
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

ROOT     = Path(__file__).resolve().parent.parent
EVAL_DIR = ROOT / "data" / "eval"
EVAL_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# Colors
G = "\033[0;32m"; B = "\033[0;34m"; Y = "\033[1;33m"; R = "\033[0;31m"
C = "\033[0;36m"; M = "\033[0;35m"; BOLD = "\033[1m"; DIM = "\033[2m"; RST = "\033[0m"

# ── Fixed eval prompts ────────────────────────────────────────────────────────
# These never change — run against every model version for fair comparison.
# Topics: Agentop architecture, web dev, Python patterns, 3D web

EVAL_SET = [
    {
        "id": "arch_routing",
        "category": "Agentop Architecture",
        "prompt": "Explain how Agentop routes a user message from the VS Code extension to the correct agent.",
        "expected_terms": ["gatekeeper", "langgraph", "orchestrator", "soul", "drift guard", "fastapi"],
        "expect_code": False,
    },
    {
        "id": "arch_tool",
        "category": "Agentop Architecture",
        "prompt": "What is the difference between a native tool and an MCP tool in Agentop? Give an example of each.",
        "expected_terms": ["native", "mcp", "docker", "safe_shell", "file_reader", "bridge"],
        "expect_code": False,
    },
    {
        "id": "arch_driftguard",
        "category": "Agentop Architecture",
        "prompt": "What does Drift Guard do and why is it important for agent governance?",
        "expected_terms": ["middleware", "tool type", "audit", "invariant", "state_modify", "read_only"],
        "expect_code": False,
    },
    {
        "id": "python_fastapi",
        "category": "Python/FastAPI",
        "prompt": "Write a FastAPI route that handles a POST request to /chat, validates the request body with Pydantic, and returns a StreamingResponse.",
        "expected_terms": ["fastapi", "pydantic", "streamingresponse", "asyncgenerator", "basemodel"],
        "expect_code": True,
    },
    {
        "id": "python_async",
        "category": "Python Patterns",
        "prompt": "What's the right way to run multiple async tasks concurrently in Python and collect all their results?",
        "expected_terms": ["asyncio.gather", "await", "async def", "coroutine", "task"],
        "expect_code": True,
    },
    {
        "id": "three_js_particles",
        "category": "3D Web",
        "prompt": "Write a Three.js BufferGeometry particle system hero section with 2000 animated particles.",
        "expected_terms": ["buffergeometry", "bufferattribute", "points", "float32array", "requestanimationframe"],
        "expect_code": True,
    },
    {
        "id": "gsap_scroll",
        "category": "3D Web",
        "prompt": "How do I pin a section and create a horizontal scroll gallery with GSAP ScrollTrigger?",
        "expected_terms": ["scrolltrigger", "pin", "scrub", "gsap.to", "end"],
        "expect_code": True,
    },
    {
        "id": "webgl_gradient",
        "category": "3D Web",
        "prompt": "Explain how to build an animated WebGL gradient background using a fragment shader with simplex noise.",
        "expected_terms": ["fragment shader", "uniform", "gl_fragcolor", "noise", "webgl"],
        "expect_code": True,
    },
    {
        "id": "ibds_component",
        "category": "IBDS Dashboard",
        "prompt": "Write a TypeScript React component called SpendTracker using Mantine v7 that shows a monthly cost breakdown.",
        "expected_terms": ["use client", "mantine", "typescript", "interface", "usestate", "rem("],
        "expect_code": True,
    },
    {
        "id": "agent_add",
        "category": "Agentop Architecture",
        "prompt": "Walk me through the exact steps to add a new agent called marketing_agent to Agentop.",
        "expected_terms": ["all_agent_definitions", "docs/agent_registry", "docs/source_of_truth", "drift guard", "system prompt"],
        "expect_code": False,
    },
]


# ── Ollama call ───────────────────────────────────────────────────────────────

def ask_ollama(model: str, prompt: str) -> tuple[str, float]:
    """Returns (response_text, latency_seconds). Empty string on failure."""
    try:
        import requests
    except ImportError:
        return "", 0.0

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are Lex Santiago — NJIT CS student, founder of Agentop, a production "
                    "multi-agent system with FastAPI + LangGraph + Ollama backend. You answer "
                    "technical questions with precise, opinionated detail and working code examples."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 1024},
    }
    t0 = time.time()
    try:
        import requests as req
        resp = req.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        latency = time.time() - t0
        return resp.json()["message"]["content"].strip(), latency
    except Exception as e:
        return f"[ERROR: {e}]", time.time() - t0


# ── scoring ───────────────────────────────────────────────────────────────────

def score_response(response: str, item: dict) -> dict:
    """Score a single response against the eval item expectations."""
    response_lower = response.lower()

    # Term coverage (40 pts)
    terms_found  = [t for t in item["expected_terms"] if t in response_lower]
    term_score   = len(terms_found) / len(item["expected_terms"]) * 40

    # Length / richness (30 pts)
    char_len     = len(response)
    length_score = min(30, int(char_len / 2000 * 30))

    # Code presence if expected (20 pts)
    has_code     = "```" in response
    code_score   = (20 if has_code else 5) if item["expect_code"] else 20

    # Structure (10 pts) — has headers or lists
    has_struct   = bool(
        "##" in response or "- " in response or
        "1. " in response or "**" in response
    )
    struct_score = 10 if has_struct else 0

    total = term_score + length_score + code_score + struct_score

    return {
        "total":        round(total, 1),
        "term_score":   round(term_score, 1),
        "length_score": round(length_score, 1),
        "code_score":   code_score,
        "struct_score": struct_score,
        "terms_found":  terms_found,
        "terms_missed": [t for t in item["expected_terms"] if t not in response_lower],
        "char_len":     char_len,
        "has_code":     has_code,
    }


# ── views ──────────────────────────────────────────────────────────────────────

def bar(v: float, max_v: float = 100, width: int = 20, char: str = "█") -> str:
    filled = round(v / max_v * width) if max_v > 0 else 0
    return char * filled + DIM + "░" * (width - filled) + RST


def print_eval_results(results: list[dict], model: str, elapsed: float) -> None:
    by_cat: dict[str, list[dict]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    total_score = sum(r["score"]["total"] for r in results) / len(results)
    code_pct    = sum(1 for r in results if r["score"]["has_code"]) / len(results) * 100
    avg_len     = sum(r["score"]["char_len"] for r in results) / len(results)
    avg_latency = sum(r["latency"] for r in results) / len(results)

    print(f"\n{BOLD}{'═'*62}{RST}")
    print(f"{BOLD}  Model Eval: {C}{model}{RST}   {DIM}{datetime.now():%Y-%m-%d %H:%M}{RST}")
    print(f"{BOLD}{'═'*62}{RST}\n")

    # Overall score
    score_color = G if total_score >= 70 else (Y if total_score >= 45 else R)
    print(f"  {BOLD}Overall Score: {score_color}{BOLD}{total_score:.1f}/100{RST}  {bar(total_score)}")
    print(f"  Code inclusion:  {G if code_pct>=50 else Y}{code_pct:.0f}%{RST}")
    print(f"  Avg response:    {avg_len:.0f} chars")
    print(f"  Avg latency:     {avg_latency:.1f}s")
    print()

    # Per-category breakdown
    print(f"  {BOLD}Category Breakdown:{RST}")
    for cat, cat_results in by_cat.items():
        cat_avg = sum(r["score"]["total"] for r in cat_results) / len(cat_results)
        cat_color = G if cat_avg >= 70 else (Y if cat_avg >= 45 else R)
        print(f"  {C}{cat:<32}{RST} {cat_color}{BOLD}{cat_avg:5.1f}{RST}  {bar(cat_avg, width=18)}")

    # Per-question results
    print(f"\n  {BOLD}Per-Question Results:{RST}")
    print(f"  {DIM}{'ID':<22} {'Score':>5} {'Len':>6} {'Code':<5} {'Terms':>12}{RST}")
    print(f"  {'─'*22} {'─'*5} {'─'*6} {'─'*5} {'─'*12}")
    for r in results:
        s = r["score"]
        score_c = G if s["total"] >= 70 else (Y if s["total"] >= 45 else R)
        found_ratio = f"{len(s['terms_found'])}/{len(s['terms_found'])+len(s['terms_missed'])}"
        print(
            f"  {r['id']:<22} {score_c}{s['total']:>5.1f}{RST} "
            f"{s['char_len']:>6} {'✓' if s['has_code'] else '✗':<5} {found_ratio:>12}"
        )
        if s["terms_missed"]:
            print(f"  {DIM}    missed: {', '.join(s['terms_missed'])}{RST}")

    print(f"\n{BOLD}{'═'*62}{RST}\n")


def print_history() -> None:
    """Show all previous eval runs sorted by score."""
    runs = []
    for f in EVAL_DIR.glob("eval_*.json"):
        try:
            data = json.loads(f.read_text())
            runs.append(data)
        except Exception:
            continue

    if not runs:
        print(f"{Y}No eval history found yet. Run once to establish a baseline.{RST}")
        return

    runs.sort(key=lambda x: x.get("timestamp", ""))

    print(f"\n{BOLD}{'─'*70}{RST}")
    print(f"{BOLD}  Eval History — All Model Runs{RST}")
    print(f"{BOLD}{'─'*70}{RST}")
    print(f"  {DIM}{'Date':<17} {'Model':<22} {'Score':>6} {'Code%':>6} {'AvgLen':>7} {'Latency':>8}{RST}")
    print(f"  {'─'*17} {'─'*22} {'─'*6} {'─'*6} {'─'*7} {'─'*8}")

    scores = []
    for run in runs:
        ts = run.get("timestamp", "")[:16].replace("T", " ")
        model = run.get("model", "?")[:22]
        score = run.get("overall_score", 0)
        code_pct = run.get("code_pct", 0)
        avg_len  = run.get("avg_len", 0)
        avg_lat  = run.get("avg_latency", 0)
        scores.append(score)
        score_c = G if score >= 70 else (Y if score >= 45 else R)
        print(f"  {ts:<17} {model:<22} {score_c}{BOLD}{score:>6.1f}{RST} {code_pct:>5.0f}% {avg_len:>7.0f} {avg_lat:>7.1f}s")

    if len(scores) > 1:
        delta = scores[-1] - scores[0]
        delta_c = G if delta > 0 else R
        print(f"\n  Score delta (first → last): {delta_c}{BOLD}{delta:+.1f} points{RST}")

    print(f"{BOLD}{'─'*70}{RST}\n")


def print_compare() -> None:
    """Side-by-side comparison of the two most recent eval runs."""
    runs = sorted(EVAL_DIR.glob("eval_*.json"))
    if len(runs) < 2:
        print(f"{Y}Need at least 2 eval runs to compare. Run eval on base model and fine-tuned model.{RST}")
        return

    a_data = json.loads(runs[-2].read_text())
    b_data = json.loads(runs[-1].read_text())
    a_results = {r["id"]: r for r in a_data.get("results", [])}
    b_results = {r["id"]: r for r in b_data.get("results", [])}

    print(f"\n{BOLD}{'─'*70}{RST}")
    print(f"{BOLD}  Side-by-Side Comparison{RST}")
    print(f"  A: {C}{a_data.get('model', '?')}{RST}  (score: {a_data.get('overall_score', 0):.1f})")
    print(f"  B: {C}{b_data.get('model', '?')}{RST}  (score: {b_data.get('overall_score', 0):.1f})")
    print(f"{BOLD}{'─'*70}{RST}")
    print(f"  {DIM}{'ID':<22} {'A score':>8} {'B score':>8} {'Delta':>8}{RST}")
    print(f"  {'─'*22} {'─'*8} {'─'*8} {'─'*8}")

    for qid in a_results:
        if qid not in b_results:
            continue
        a_s = a_results[qid]["score"]["total"]
        b_s = b_results[qid]["score"]["total"]
        delta = b_s - a_s
        dc = G if delta > 0 else (R if delta < 0 else DIM)
        print(f"  {qid:<22} {a_s:>8.1f} {b_s:>8.1f} {dc}{BOLD}{delta:>+8.1f}{RST}")

    overall_delta = b_data.get("overall_score", 0) - a_data.get("overall_score", 0)
    dc = G if overall_delta > 0 else R
    print(f"  {'─'*22} {'─'*8} {'─'*8} {'─'*8}")
    print(f"  {'OVERALL':<22} {a_data.get('overall_score',0):>8.1f} {b_data.get('overall_score',0):>8.1f} {dc}{BOLD}{overall_delta:>+8.1f}{RST}")
    print(f"{BOLD}{'─'*70}{RST}\n")


# ── main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark an Ollama model against the Agentop eval set.")
    parser.add_argument("--model",   default=OLLAMA_MODEL, help="Ollama model name (default: $OLLAMA_MODEL)")
    parser.add_argument("--history", action="store_true",  help="Show all previous eval runs")
    parser.add_argument("--compare", action="store_true",  help="Compare the two most recent runs")
    parser.add_argument("--quick",   action="store_true",  help="Run only 3 questions (fast sanity check)")
    args = parser.parse_args()

    if args.history:
        print_history()
        return

    if args.compare:
        print_compare()
        return

    questions = EVAL_SET[:3] if args.quick else EVAL_SET
    print(f"\n{BOLD}Running {len(questions)} eval questions against {C}{args.model}{RST}{BOLD}...{RST}")
    print(f"{DIM}(Ctrl+C to abort — partial results will not be saved){RST}\n")

    # Check Ollama is reachable
    try:
        import requests
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        available_models = [m["name"] for m in r.json().get("models", [])]
        if args.model not in available_models and args.model + ":latest" not in available_models:
            print(f"{Y}Warning: model '{args.model}' not found in Ollama. Available: {available_models}{RST}")
            print(f"{DIM}Pull with: ollama pull {args.model}{RST}\n")
    except Exception:
        print(f"{R}Cannot reach Ollama at {OLLAMA_URL}. Start with: ollama serve{RST}")
        return

    results = []
    t_start = time.time()

    for i, item in enumerate(questions):
        print(f"  [{i+1:2d}/{len(questions)}] {C}{item['id']}{RST}", end="  ", flush=True)
        response, latency = ask_ollama(args.model, item["prompt"])
        score = score_response(response, item)
        score_c = G if score["total"] >= 70 else (Y if score["total"] >= 45 else R)
        print(f"→ {score_c}{score['total']:.1f}/100{RST}  {latency:.1f}s  {len(response)} chars")

        results.append({
            "id":       item["id"],
            "category": item["category"],
            "prompt":   item["prompt"],
            "response": response,
            "score":    score,
            "latency":  round(latency, 2),
        })

    elapsed = time.time() - t_start
    overall_score = sum(r["score"]["total"] for r in results) / len(results)
    code_pct      = sum(1 for r in results if r["score"]["has_code"]) / len(results) * 100
    avg_len       = sum(r["score"]["char_len"] for r in results) / len(results)
    avg_latency   = sum(r["latency"] for r in results) / len(results)

    print_eval_results(results, args.model, elapsed)

    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path  = EVAL_DIR / f"eval_{args.model.replace(':', '_')}_{timestamp}.json"
    out_path.write_text(json.dumps({
        "model":         args.model,
        "timestamp":     datetime.now().isoformat(),
        "overall_score": round(overall_score, 1),
        "code_pct":      round(code_pct, 1),
        "avg_len":       round(avg_len, 1),
        "avg_latency":   round(avg_latency, 2),
        "question_count": len(results),
        "results":       results,
    }, indent=2, ensure_ascii=False))

    print(f"  Results saved → {out_path.relative_to(ROOT)}")
    print(f"  Run again after fine-tuning:  python scripts/eval_model.py --model lex_7b")
    print(f"  Compare:                      python scripts/eval_model.py --compare\n")


if __name__ == "__main__":
    main()
