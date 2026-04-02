#!/usr/bin/env python3
"""
scripts/eval_lex_router.py
──────────────────────────
Evaluate Lex's routing accuracy as an OpenClaw router agent.

Tests whether Lex correctly:
  1. Classifies user intent → correct agent_id
  2. Selects appropriate tools for each task
  3. Produces valid structured JSON routing decisions
  4. Handles ambiguous / multi-agent requests with reasoning
  5. Rejects out-of-scope requests gracefully

Usage:
  python scripts/eval_lex_router.py                         # Eval against Ollama 'lex'
  python scripts/eval_lex_router.py --model llama3.2        # Eval a different model
  python scripts/eval_lex_router.py --quick                 # 20-case smoke test
  python scripts/eval_lex_router.py --report                # Full report + JSON export
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ── Eval Cases ────────────────────────────────────────────────────────────


@dataclass
class RouterEvalCase:
    """A single routing evaluation case."""

    case_id: str
    prompt: str
    expected_agent: str
    expected_tools: list[str] = field(default_factory=list)
    category: str = ""  # intent category
    difficulty: str = "easy"  # easy | medium | hard
    ambiguous: bool = False  # multi-agent ambiguity expected


# Comprehensive eval suite — covers every agent + edge cases
EVAL_CASES: list[RouterEvalCase] = [
    # ── soul_core ──
    RouterEvalCase("soul_01", "What is the purpose of Agentop?", "soul_core", category="reflection"),
    RouterEvalCase("soul_02", "Reflect on our progress this week", "soul_core", category="reflection"),
    RouterEvalCase(
        "soul_03", "What are the trust scores for each agent?", "soul_core", ["file_reader"], category="trust"
    ),
    RouterEvalCase("soul_04", "Remember to prioritize security work next sprint", "soul_core", category="memory"),
    # ── devops_agent ──
    RouterEvalCase(
        "devops_01",
        "Deploy the latest build to production",
        "devops_agent",
        ["git_ops", "safe_shell"],
        category="deploy",
    ),
    RouterEvalCase(
        "devops_02",
        "Create a GitHub issue for the CORS bug",
        "devops_agent",
        ["mcp_github_create_issue"],
        category="github",
    ),
    RouterEvalCase("devops_03", "What branches are currently active?", "devops_agent", ["git_ops"], category="git"),
    RouterEvalCase("devops_04", "Run the CI pipeline on dev branch", "devops_agent", ["safe_shell"], category="ci"),
    RouterEvalCase("devops_05", "Merge feature/turbo-quant into dev", "devops_agent", ["git_ops"], category="git"),
    # ── monitor_agent ──
    RouterEvalCase(
        "monitor_01", "Check if all services are healthy", "monitor_agent", ["health_check"], category="health"
    ),
    RouterEvalCase(
        "monitor_02", "Tail the last 50 lines of system.jsonl", "monitor_agent", ["log_tail"], category="logs"
    ),
    RouterEvalCase(
        "monitor_03", "Set up an alert if CPU goes above 90%", "monitor_agent", ["alert_dispatch"], category="alerting"
    ),
    RouterEvalCase(
        "monitor_04", "What's the status of the backend server?", "monitor_agent", ["health_check"], category="health"
    ),
    # ── self_healer_agent ──
    RouterEvalCase(
        "healer_01", "The backend crashed, restart it", "self_healer_agent", ["process_restart"], category="recovery"
    ),
    RouterEvalCase(
        "healer_02",
        "There's a zombie process eating CPU",
        "self_healer_agent",
        ["process_restart", "safe_shell"],
        category="recovery",
    ),
    RouterEvalCase(
        "healer_03",
        "Auto-fix the failed Ollama connection",
        "self_healer_agent",
        ["process_restart", "health_check"],
        category="recovery",
    ),
    # ── code_review_agent ──
    RouterEvalCase(
        "review_01",
        "Review the latest diff in backend/routes/",
        "code_review_agent",
        ["file_reader", "git_ops"],
        category="review",
    ),
    RouterEvalCase(
        "review_02", "Check for drift guard violations", "code_review_agent", ["file_reader"], category="drift"
    ),
    RouterEvalCase(
        "review_03", "Is this code following our patterns?", "code_review_agent", ["file_reader"], category="review"
    ),
    # ── security_agent ──
    RouterEvalCase(
        "sec_01", "Scan the repo for exposed API keys", "security_agent", ["secret_scanner"], category="secrets"
    ),
    RouterEvalCase(
        "sec_02", "Check for known CVEs in our dependencies", "security_agent", ["safe_shell"], category="cve"
    ),
    RouterEvalCase(
        "sec_03",
        "Audit the authentication middleware",
        "security_agent",
        ["file_reader", "secret_scanner"],
        category="audit",
    ),
    # ── data_agent ──
    RouterEvalCase("data_01", "How many customers are in the database?", "data_agent", ["db_query"], category="query"),
    RouterEvalCase(
        "data_02", "Show me the schema of the GSD tasks table", "data_agent", ["db_query"], category="schema"
    ),
    RouterEvalCase(
        "data_03", "Run an ETL job to update analytics", "data_agent", ["db_query", "file_reader"], category="etl"
    ),
    # ── comms_agent ──
    RouterEvalCase(
        "comms_01",
        "Send a webhook notification about the deployment",
        "comms_agent",
        ["webhook_send"],
        category="webhook",
    ),
    RouterEvalCase(
        "comms_02",
        "Alert the team about the outage",
        "comms_agent",
        ["webhook_send", "alert_dispatch"],
        category="incident",
    ),
    # ── cs_agent ──
    RouterEvalCase("cs_01", "A customer is asking about pricing", "cs_agent", ["file_reader"], category="support"),
    RouterEvalCase("cs_02", "Handle this support ticket: account login issue", "cs_agent", category="support"),
    # ── it_agent ──
    RouterEvalCase(
        "it_01", "What's the current CPU and memory usage?", "it_agent", ["system_info"], category="metrics"
    ),
    RouterEvalCase("it_02", "List all running Docker containers", "it_agent", ["safe_shell"], category="infra"),
    RouterEvalCase("it_03", "Check disk space on the server", "it_agent", ["system_info"], category="metrics"),
    # ── knowledge_agent ──
    RouterEvalCase(
        "know_01", "Search the docs for drift guard invariants", "knowledge_agent", ["file_reader"], category="search"
    ),
    RouterEvalCase(
        "know_02",
        "What does the SOURCE_OF_TRUTH.md say about tools?",
        "knowledge_agent",
        ["file_reader"],
        category="qa",
    ),
    # ── Ambiguous / Hard Cases ──
    RouterEvalCase(
        "hard_01",
        "The server seems slow, check logs and restart if needed",
        "self_healer_agent",  # Primary — needs action, not just monitoring
        ["log_tail", "health_check", "process_restart"],
        category="multi",
        difficulty="hard",
        ambiguous=True,
    ),
    RouterEvalCase(
        "hard_02",
        "Review the security of the new webhook endpoint",
        "security_agent",  # Security takes precedence over code review
        ["file_reader", "secret_scanner"],
        category="multi",
        difficulty="hard",
        ambiguous=True,
    ),
    RouterEvalCase(
        "hard_03",
        "Document the new API changes and deploy them",
        "devops_agent",  # Deploy takes precedence (docs come with it)
        ["git_ops", "safe_shell"],
        category="multi",
        difficulty="hard",
        ambiguous=True,
    ),
    RouterEvalCase(
        "hard_04",
        "Hey what's up?",
        "soul_core",  # Casual greeting → soul handles
        category="casual",
        difficulty="medium",
    ),
    RouterEvalCase(
        "hard_05",
        "Make me a website for a pizza shop",
        "soul_core",  # WebGen pipeline, but routed through soul for orchestration
        category="webgen",
        difficulty="medium",
    ),
]


# ── Ollama Interface ──────────────────────────────────────────────────────

ROUTER_SYSTEM_PROMPT = """You are Lex, the OpenClaw router agent for Agentop.
Given a user request, output a JSON routing decision:
{
  "agent_id": "<agent to route to>",
  "reasoning": "<brief explanation>",
  "tools_needed": ["<tool1>", "<tool2>"],
  "urgency": "<low|medium|high>",
  "confidence": <0.0-1.0>
}

Available agents: soul_core, devops_agent, monitor_agent, self_healer_agent,
code_review_agent, security_agent, data_agent, comms_agent, cs_agent,
it_agent, knowledge_agent.

Available tools: safe_shell, file_reader, doc_updater, system_info,
webhook_send, git_ops, health_check, log_tail, alert_dispatch,
secret_scanner, db_query, process_restart.

Respond ONLY with valid JSON."""


def query_ollama(prompt: str, model: str) -> tuple[str, float]:
    """Send a prompt to Ollama, return (response_text, latency_ms).

    If model name starts with 'lex', skip the external system prompt so the
    Modelfile's embedded system prompt (with few-shot examples) is used.
    """
    start = time.monotonic()
    try:
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1, "num_predict": 512},
        }
        # Only inject eval system prompt for models without built-in routing prompt
        if not model.startswith("lex"):
            payload["system"] = ROUTER_SYSTEM_PROMPT
        resp = httpx.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        data = resp.json()
        latency = (time.monotonic() - start) * 1000
        return data.get("response", ""), latency
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return f"ERROR: {e}", latency


def parse_routing_decision(text: str) -> dict | None:
    """Try to parse JSON from the model's response."""
    text = text.strip()
    # Handle markdown code blocks
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if start != end:
            inner = text[start:end]
            # Strip language identifier
            inner = inner.lstrip("`").lstrip("json").strip()
            text = inner

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    return None


# ── Scoring ───────────────────────────────────────────────────────────────


@dataclass
class CaseResult:
    case_id: str
    prompt: str
    expected_agent: str
    actual_agent: str
    agent_correct: bool
    tools_precision: float
    tools_recall: float
    valid_json: bool
    has_reasoning: bool
    confidence: float
    latency_ms: float
    difficulty: str
    raw_response: str


def score_case(case: RouterEvalCase, model: str) -> CaseResult:
    """Run one eval case through the model and score it."""
    response_text, latency_ms = query_ollama(case.prompt, model)
    decision = parse_routing_decision(response_text)

    if decision is None:
        return CaseResult(
            case_id=case.case_id,
            prompt=case.prompt,
            expected_agent=case.expected_agent,
            actual_agent="PARSE_ERROR",
            agent_correct=False,
            tools_precision=0.0,
            tools_recall=0.0,
            valid_json=False,
            has_reasoning=False,
            confidence=0.0,
            latency_ms=latency_ms,
            difficulty=case.difficulty,
            raw_response=response_text[:500],
        )

    actual_agent = (decision.get("agent_id") or "").strip()
    actual_tools = set(decision.get("tools_needed") or [])
    expected_tools = set(case.expected_tools)
    reasoning = decision.get("reasoning") or ""
    confidence = decision.get("confidence") or 0.0

    # Agent correctness (exact match or acceptable for ambiguous)
    agent_correct = actual_agent == case.expected_agent

    # Tool precision/recall
    if expected_tools and actual_tools:
        intersection = expected_tools & actual_tools
        precision = len(intersection) / len(actual_tools) if actual_tools else 0.0
        recall = len(intersection) / len(expected_tools) if expected_tools else 0.0
    elif not expected_tools:
        precision = 1.0
        recall = 1.0
    else:
        precision = 0.0
        recall = 0.0

    return CaseResult(
        case_id=case.case_id,
        prompt=case.prompt,
        expected_agent=case.expected_agent,
        actual_agent=actual_agent,
        agent_correct=agent_correct,
        tools_precision=precision,
        tools_recall=recall,
        valid_json=True,
        has_reasoning=bool(reasoning.strip()),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else 0.0,
        latency_ms=latency_ms,
        difficulty=case.difficulty,
        raw_response=response_text[:500],
    )


# ── Report ────────────────────────────────────────────────────────────────


def run_eval(model: str, cases: list[RouterEvalCase], verbose: bool = False) -> list[CaseResult]:
    """Run all eval cases and return results."""
    print("\n═══ Lex Router Evaluation ═══")
    print(f"  Model: {model}")
    print(f"  Cases: {len(cases)}")
    print(f"  Ollama: {OLLAMA_URL}\n")

    results: list[CaseResult] = []
    for i, case in enumerate(cases, 1):
        result = score_case(case, model)
        results.append(result)

        status = "✓" if result.agent_correct else "✗"
        print(
            f"  [{i:02d}/{len(cases)}] {status} {case.case_id:<12} "
            f"expected={case.expected_agent:<20} got={result.actual_agent:<20} "
            f"json={'Y' if result.valid_json else 'N'} "
            f"{result.latency_ms:.0f}ms"
        )

        if verbose and not result.agent_correct:
            print(f"           Prompt: {case.prompt[:80]}")
            print(f"           Response: {result.raw_response[:120]}")

    return results


def compute_metrics(results: list[CaseResult]) -> dict:
    """Compute aggregate metrics from eval results."""
    n = len(results)
    if n == 0:
        return {}

    agent_correct = sum(1 for r in results if r.agent_correct)
    valid_json = sum(1 for r in results if r.valid_json)
    has_reasoning = sum(1 for r in results if r.has_reasoning)
    avg_latency = sum(r.latency_ms for r in results) / n
    avg_precision = sum(r.tools_precision for r in results) / n
    avg_recall = sum(r.tools_recall for r in results) / n
    avg_confidence = sum(r.confidence for r in results if r.valid_json) / max(valid_json, 1)

    # Per-difficulty breakdown
    difficulty_breakdown = {}
    for diff in ("easy", "medium", "hard"):
        diff_results = [r for r in results if r.difficulty == diff]
        if diff_results:
            difficulty_breakdown[diff] = {
                "total": len(diff_results),
                "correct": sum(1 for r in diff_results if r.agent_correct),
                "accuracy": sum(1 for r in diff_results if r.agent_correct) / len(diff_results),
            }

    # Per-agent breakdown
    agent_breakdown: dict[str, dict] = {}
    for r in results:
        agent = r.expected_agent
        if agent not in agent_breakdown:
            agent_breakdown[agent] = {"total": 0, "correct": 0}
        agent_breakdown[agent]["total"] += 1
        if r.agent_correct:
            agent_breakdown[agent]["correct"] += 1
    for agent in agent_breakdown:
        ab = agent_breakdown[agent]
        ab["accuracy"] = ab["correct"] / ab["total"] if ab["total"] > 0 else 0.0

    return {
        "total_cases": n,
        "agent_accuracy": agent_correct / n,
        "agent_correct": agent_correct,
        "valid_json_rate": valid_json / n,
        "reasoning_rate": has_reasoning / n,
        "avg_tool_precision": avg_precision,
        "avg_tool_recall": avg_recall,
        "avg_latency_ms": avg_latency,
        "avg_confidence": avg_confidence,
        "by_difficulty": difficulty_breakdown,
        "by_agent": agent_breakdown,
    }


def print_report(metrics: dict, model: str) -> None:
    """Print a formatted eval report."""
    print(f"\n{'=' * 60}")
    print(f"  LEX ROUTER EVAL REPORT — {model}")
    print(f"{'=' * 60}")
    print(
        f"  Agent Routing Accuracy:  {metrics['agent_accuracy']:.1%} ({metrics['agent_correct']}/{metrics['total_cases']})"
    )
    print(f"  Valid JSON Rate:         {metrics['valid_json_rate']:.1%}")
    print(f"  Reasoning Present:       {metrics['reasoning_rate']:.1%}")
    print(f"  Avg Tool Precision:      {metrics['avg_tool_precision']:.2f}")
    print(f"  Avg Tool Recall:         {metrics['avg_tool_recall']:.2f}")
    print(f"  Avg Latency:             {metrics['avg_latency_ms']:.0f}ms")
    print(f"  Avg Confidence:          {metrics['avg_confidence']:.2f}")

    print("\n  By Difficulty:")
    for diff, data in metrics.get("by_difficulty", {}).items():
        print(f"    {diff:<8}: {data['accuracy']:.0%} ({data['correct']}/{data['total']})")

    print("\n  By Agent:")
    for agent, data in sorted(metrics.get("by_agent", {}).items()):
        bar = "█" * int(data["accuracy"] * 10)
        print(f"    {agent:<22}: {data['accuracy']:.0%} {bar} ({data['correct']}/{data['total']})")
    print(f"{'=' * 60}\n")


def export_report(results: list[CaseResult], metrics: dict, model: str) -> Path:
    """Export full report as JSON."""
    report = {
        "model": model,
        "timestamp": datetime.now(UTC).isoformat(),
        "metrics": metrics,
        "cases": [asdict(r) for r in results],
    }
    path = REPORT_DIR / f"lex_router_eval_{model}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(report, indent=2))
    print(f"  Report exported to {path}")
    return path


def log_to_experiment_tracker(metrics: dict, model: str) -> None:
    """Log eval results to ExperimentTracker."""
    try:
        from backend.ml.experiment_tracker import ExperimentTracker

        tracker = ExperimentTracker()
        run_id = tracker.start_run(
            experiment_name="lex_router_eval",
            hyperparameters={"model": model, "n_cases": metrics["total_cases"]},
            model_type="router_eval",
            dataset_version=f"eval_suite_v1_{metrics['total_cases']}cases",
            tags={"eval_type": "router", "model": model},
        )
        tracker.log_metric(run_id, "agent_accuracy", metrics["agent_accuracy"])
        tracker.log_metric(run_id, "valid_json_rate", metrics["valid_json_rate"])
        tracker.log_metric(run_id, "avg_tool_precision", metrics["avg_tool_precision"])
        tracker.log_metric(run_id, "avg_tool_recall", metrics["avg_tool_recall"])
        tracker.log_metric(run_id, "avg_latency_ms", metrics["avg_latency_ms"])
        tracker.end_run(run_id, status="completed")
        print(f"  Tracked as experiment run: {run_id}")
    except ImportError:
        pass


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Lex's routing accuracy")
    parser.add_argument("--model", type=str, default="lex", help="Ollama model to evaluate")
    parser.add_argument("--quick", action="store_true", help="Run quick 20-case smoke test")
    parser.add_argument("--report", action="store_true", help="Export JSON report")
    parser.add_argument("--verbose", action="store_true", help="Show details on failures")
    args = parser.parse_args()

    cases = EVAL_CASES[:20] if args.quick else EVAL_CASES

    results = run_eval(args.model, cases, verbose=args.verbose)
    metrics = compute_metrics(results)
    print_report(metrics, args.model)

    if args.report:
        export_report(results, metrics, args.model)

    log_to_experiment_tracker(metrics, args.model)

    # Exit code based on accuracy threshold
    threshold = 0.70
    if metrics["agent_accuracy"] < threshold:
        print(f"  ⚠ Agent accuracy {metrics['agent_accuracy']:.0%} below {threshold:.0%} threshold")
        sys.exit(1)


if __name__ == "__main__":
    main()
