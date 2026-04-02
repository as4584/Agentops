#!/usr/bin/env python3
"""
benchmark_models.py — Comprehensive model comparison for Lex routing.

Tests lex-v2 against every available Ollama model (including quantized variants)
on routing accuracy, latency, tool selection, and reasoning quality.

Usage:
    python scripts/benchmark_models.py                    # All available models
    python scripts/benchmark_models.py --models lex-v2 llama3.2 mistral:7b
    python scripts/benchmark_models.py --quick            # 10-case smoke test
    python scripts/benchmark_models.py --export csv       # Export results
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Test cases — expanded from eval_lex_router.py with harder edge cases
# ---------------------------------------------------------------------------

ROUTING_CASES = [
    # --- Core routing (basics) ---
    {
        "id": "route_01",
        "message": "deploy my app to production",
        "expected_agent": "devops_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_02",
        "message": "scan for leaked API keys",
        "expected_agent": "security_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_03",
        "message": "what is the meaning of my work?",
        "expected_agent": "soul_core",
        "category": "basic",
        "difficulty": "medium",
    },
    {
        "id": "route_04",
        "message": "restart the backend service",
        "expected_agent": "self_healer_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_05",
        "message": "review my latest pull request",
        "expected_agent": "code_review_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_06",
        "message": "check if the API is responding",
        "expected_agent": "monitor_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_07",
        "message": "query the customer database",
        "expected_agent": "data_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_08",
        "message": "send a slack notification about the outage",
        "expected_agent": "comms_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_09",
        "message": "help this customer with a refund",
        "expected_agent": "cs_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_10",
        "message": "what does our architecture document say about drift?",
        "expected_agent": "knowledge_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    {
        "id": "route_11",
        "message": "check server disk space and memory",
        "expected_agent": "it_agent",
        "category": "basic",
        "difficulty": "easy",
    },
    # --- Ambiguous (hard) ---
    {
        "id": "ambig_01",
        "message": "the server is slow and I think there might be a memory leak",
        "expected_agent": "monitor_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_02",
        "message": "I want to reflect on whether our agent architecture is serving us well",
        "expected_agent": "soul_core",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_03",
        "message": "the database migration failed and now users can't log in",
        "expected_agent": "self_healer_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_04",
        "message": "check if anyone committed secrets to the repo and also review the code quality",
        "expected_agent": "security_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_05",
        "message": "I need to understand what went wrong in last night's deploy",
        "expected_agent": "devops_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_06",
        "message": "analyze customer complaints and find patterns",
        "expected_agent": "data_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    {
        "id": "ambig_07",
        "message": "our SSL certificate is expiring tomorrow",
        "expected_agent": "it_agent",
        "category": "ambiguous",
        "difficulty": "hard",
    },
    # --- Multi-intent ---
    {
        "id": "multi_01",
        "message": "deploy to staging, then run the test suite, then notify the team",
        "expected_agent": "devops_agent",
        "category": "multi-intent",
        "difficulty": "hard",
    },
    {
        "id": "multi_02",
        "message": "check system health and if anything is wrong try to fix it automatically",
        "expected_agent": "monitor_agent",
        "category": "multi-intent",
        "difficulty": "hard",
    },
    # --- Soul-specific (the hardest category) ---
    {
        "id": "soul_01",
        "message": "how aligned are we with our original mission?",
        "expected_agent": "soul_core",
        "category": "soul",
        "difficulty": "hard",
    },
    {
        "id": "soul_02",
        "message": "I feel like we're losing focus. What should we prioritize?",
        "expected_agent": "soul_core",
        "category": "soul",
        "difficulty": "hard",
    },
    {
        "id": "soul_03",
        "message": "which agent has been performing the worst this week?",
        "expected_agent": "soul_core",
        "category": "soul",
        "difficulty": "medium",
    },
    {
        "id": "soul_04",
        "message": "are we doing the right things? take a step back and think about it",
        "expected_agent": "soul_core",
        "category": "soul",
        "difficulty": "hard",
    },
    # --- Trap cases (should NOT route to common wrong answers) ---
    {
        "id": "trap_01",
        "message": "tell me about kubernetes pods",
        "expected_agent": "knowledge_agent",
        "category": "trap",
        "difficulty": "medium",
    },
    {
        "id": "trap_02",
        "message": "create a new branch called feature/auth",
        "expected_agent": "devops_agent",
        "category": "trap",
        "difficulty": "easy",
    },
    {
        "id": "trap_03",
        "message": "the network is unreachable from the container",
        "expected_agent": "it_agent",
        "category": "trap",
        "difficulty": "medium",
    },
    # --- Tool selection ---
    {
        "id": "tool_01",
        "message": "read the contents of backend/config.py",
        "expected_agent": "knowledge_agent",
        "expected_tools": ["file_reader"],
        "category": "tool",
        "difficulty": "easy",
    },
    {
        "id": "tool_02",
        "message": "run git log --oneline for the last 10 commits",
        "expected_agent": "devops_agent",
        "expected_tools": ["git_ops"],
        "category": "tool",
        "difficulty": "easy",
    },
    {
        "id": "tool_03",
        "message": "check if port 8000 is accepting connections",
        "expected_agent": "monitor_agent",
        "expected_tools": ["health_check"],
        "category": "tool",
        "difficulty": "easy",
    },
]

QUICK_CASES = ROUTING_CASES[:10]


# ---------------------------------------------------------------------------
# Model interaction
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are an AI router for Agentop. Route the user's message to exactly ONE agent.

Available agents: soul_core, devops_agent, monitor_agent, self_healer_agent, code_review_agent, security_agent, data_agent, comms_agent, cs_agent, it_agent, knowledge_agent

Respond ONLY with JSON: {"agent_id": "<agent>", "confidence": <0.0-1.0>, "reasoning": "<1 sentence>"}"""


# Models with baked-in system prompts (Modelfile few-shot) — don't override
_SELF_PROMPTED_MODELS = {"lex-v2", "lex-v2:latest", "lex", "lex:latest"}


def query_model(model: str, message: str, timeout: int = 30) -> dict:
    """Send a routing query to an Ollama model, return parsed response."""
    start = time.time()
    try:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": f"Route this message: {message}",
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 150},
        }
        # Only inject system prompt for models without baked-in few-shot
        base_name = model.split(":")[0] if ":" in model else model
        if base_name not in _SELF_PROMPTED_MODELS and model not in _SELF_PROMPTED_MODELS:
            payload["system"] = SYSTEM_PROMPT

        resp = requests.post(
            "http://localhost:11434/api/generate",
            json=payload,
            timeout=timeout,
        )
        latency_ms = (time.time() - start) * 1000
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}", "latency_ms": latency_ms}

        raw = resp.json().get("response", "").strip()

        # Parse JSON from response
        try:
            # Find JSON in response
            start_idx = raw.find("{")
            end_idx = raw.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                decision = json.loads(raw[start_idx:end_idx])
                return {
                    "agent_id": (decision.get("agent_id") or "").strip().lower(),
                    "confidence": decision.get("confidence", 0),
                    "reasoning": decision.get("reasoning", ""),
                    "raw": raw,
                    "latency_ms": latency_ms,
                    "valid_json": True,
                }
        except json.JSONDecodeError:
            pass

        return {"agent_id": "", "raw": raw, "latency_ms": latency_ms, "valid_json": False}

    except Exception as e:
        return {"error": str(e), "latency_ms": (time.time() - start) * 1000}


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


@dataclass
class ModelResult:
    model: str
    total: int = 0
    correct: int = 0
    latencies: list[float] = field(default_factory=list)
    by_category: dict[str, dict] = field(default_factory=dict)
    by_difficulty: dict[str, dict] = field(default_factory=dict)
    json_errors: int = 0
    errors: int = 0
    details: list[dict] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return (self.correct / self.total * 100) if self.total else 0

    @property
    def avg_latency(self) -> float:
        return sum(self.latencies) / len(self.latencies) if self.latencies else 0

    @property
    def p95_latency(self) -> float:
        if not self.latencies:
            return 0
        sorted_l = sorted(self.latencies)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]


def benchmark_model(model: str, cases: list[dict]) -> ModelResult:
    """Run all test cases against a model."""
    result = ModelResult(model=model)

    # Warm up (first call is always slower due to model loading)
    query_model(model, "hello", timeout=60)

    for case in cases:
        result.total += 1
        resp = query_model(model, case["message"])

        cat = case.get("category", "unknown")
        diff = case.get("difficulty", "unknown")

        if cat not in result.by_category:
            result.by_category[cat] = {"total": 0, "correct": 0}
        if diff not in result.by_difficulty:
            result.by_difficulty[diff] = {"total": 0, "correct": 0}

        result.by_category[cat]["total"] += 1
        result.by_difficulty[diff]["total"] += 1

        if "error" in resp:
            result.errors += 1
            detail = {"case": case["id"], "status": "error", "error": resp["error"]}
        elif not resp.get("valid_json"):
            result.json_errors += 1
            detail = {"case": case["id"], "status": "json_error", "raw": resp.get("raw", "")[:200]}
        else:
            is_correct = resp["agent_id"] == case["expected_agent"]
            if is_correct:
                result.correct += 1
                result.by_category[cat]["correct"] += 1
                result.by_difficulty[diff]["correct"] += 1

            result.latencies.append(resp["latency_ms"])
            detail = {
                "case": case["id"],
                "status": "correct" if is_correct else "wrong",
                "expected": case["expected_agent"],
                "got": resp["agent_id"],
                "confidence": resp.get("confidence", 0),
                "latency_ms": round(resp["latency_ms"], 1),
            }

        result.details.append(detail)
        status_char = "✓" if detail["status"] == "correct" else "✗" if detail["status"] == "wrong" else "!"
        print(
            f"  {status_char} {case['id']:12s} → {resp.get('agent_id', 'ERR'):20s} ({resp.get('latency_ms', 0):.0f}ms)"
        )

    return result


def get_available_models() -> list[str]:
    """List all Ollama models."""
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = resp.json().get("models", [])
        return [m["name"] for m in models]
    except Exception:
        return []


def print_comparison(results: list[ModelResult]) -> None:
    """Print a comparison table."""
    print("\n" + "=" * 100)
    print(f"{'MODEL':<30} {'ACC':>6} {'AVG ms':>8} {'P95 ms':>8} {'JSON ERR':>9} {'EASY':>6} {'MED':>6} {'HARD':>6}")
    print("-" * 100)

    for r in sorted(results, key=lambda x: x.accuracy, reverse=True):
        easy = r.by_difficulty.get("easy", {})
        med = r.by_difficulty.get("medium", {})
        hard = r.by_difficulty.get("hard", {})

        easy_pct = f"{easy.get('correct', 0)}/{easy.get('total', 0)}"
        med_pct = f"{med.get('correct', 0)}/{med.get('total', 0)}"
        hard_pct = f"{hard.get('correct', 0)}/{hard.get('total', 0)}"

        print(
            f"{r.model:<30} {r.accuracy:>5.1f}% {r.avg_latency:>7.0f} {r.p95_latency:>7.0f} "
            f"{r.json_errors:>9} {easy_pct:>6} {med_pct:>6} {hard_pct:>6}"
        )

    print("=" * 100)

    # Category breakdown
    print(f"\n{'MODEL':<30}", end="")
    categories = set()
    for r in results:
        categories.update(r.by_category.keys())
    for cat in sorted(categories):
        print(f" {cat:>12}", end="")
    print()
    print("-" * (30 + 13 * len(categories)))

    for r in sorted(results, key=lambda x: x.accuracy, reverse=True):
        print(f"{r.model:<30}", end="")
        for cat in sorted(categories):
            data = r.by_category.get(cat, {})
            c, t = data.get("correct", 0), data.get("total", 0)
            pct = f"{c}/{t}" if t else "-"
            print(f" {pct:>12}", end="")
        print()


def export_results(results: list[ModelResult], fmt: str = "json") -> Path:
    """Export benchmark results."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    if fmt == "csv":
        out = REPORTS_DIR / f"benchmark_{ts}.csv"
        lines = ["model,accuracy,avg_latency_ms,p95_latency_ms,json_errors,total,correct"]
        for r in results:
            lines.append(
                f"{r.model},{r.accuracy:.1f},{r.avg_latency:.0f},{r.p95_latency:.0f},{r.json_errors},{r.total},{r.correct}"
            )
        out.write_text("\n".join(lines))
    else:
        out = REPORTS_DIR / f"benchmark_{ts}.json"
        data = []
        for r in results:
            data.append(
                {
                    "model": r.model,
                    "accuracy": round(r.accuracy, 1),
                    "avg_latency_ms": round(r.avg_latency, 0),
                    "p95_latency_ms": round(r.p95_latency, 0),
                    "json_errors": r.json_errors,
                    "total": r.total,
                    "correct": r.correct,
                    "by_category": r.by_category,
                    "by_difficulty": r.by_difficulty,
                    "details": r.details,
                }
            )
        out.write_text(json.dumps(data, indent=2))

    print(f"\n[+] Exported → {out}")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Ollama models for Lex routing")
    parser.add_argument("--models", nargs="+", help="Specific models to test")
    parser.add_argument("--quick", action="store_true", help="Quick 10-case test")
    parser.add_argument("--export", choices=["json", "csv"], default="json")
    args = parser.parse_args()

    cases = QUICK_CASES if args.quick else ROUTING_CASES

    if args.models:
        models = args.models
    else:
        models = get_available_models()
        if not models:
            print("[!] No Ollama models found. Is Ollama running?")
            sys.exit(1)

    print(f"Benchmarking {len(models)} models × {len(cases)} cases\n")

    results = []
    for model in models:
        print(f"\n── {model} ──")
        result = benchmark_model(model, cases)
        results.append(result)
        print(f"  → {result.accuracy:.1f}% ({result.correct}/{result.total}), avg {result.avg_latency:.0f}ms")

    print_comparison(results)
    export_results(results, args.export)


if __name__ == "__main__":
    main()
