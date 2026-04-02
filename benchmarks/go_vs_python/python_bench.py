"""
Python benchmark — same operations as Go, for direct comparison.

Measures: keyword routing, red line check, JSON parse, message split,
validation, and full pipeline.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

# ── Same test messages as Go ────────────────────────────────────────

TEST_MESSAGES = [
    "Deploy the latest build to production",
    "Scan the codebase for leaked API keys and secrets",
    "Monitor CPU and memory usage on the production server",
    "Restart the crashed worker process",
    "Review the latest pull request diff for security issues",
    "Query the customer database for recent orders",
    "Send a webhook notification about the deployment",
    "Help me fix a customer support ticket",
    "Check disk usage and network latency",
    "Search the knowledge base for API documentation",
    "Reflect on our team goals and mission purpose",
    "What is the current system health status?",
    "Build and release version 2.0 to staging",
    "The database schema needs migration",
    "Audit the application for CVE vulnerabilities",
    "My service keeps crashing randomly, fix it",
    "I need infrastructure diagnostics on the network",
    "Find documentation about our deployment process",
    "Set up continuous integration for the new module",
    "Check if there are any leaked tokens in the repo",
]

# ── Keyword routing (exact Python impl from lex_router.py) ─────────

KEYWORD_MAP = [
    (
        ["deploy", "ci", "cd", "pipeline", "build", "release", "merge", "branch", "docker", "container", "git"],
        "devops_agent",
    ),
    (["monitor", "health", "log", "alert", "metric", "status", "watch", "tail"], "monitor_agent"),
    (["restart", "fix", "heal", "recover", "crash", "down", "broken", "failed", "zombie"], "self_healer_agent"),
    (["review", "diff", "code quality", "refactor", "lint", "smell"], "code_review_agent"),
    (["security", "secret", "vulnerability", "cve", "scan", "audit", "leak", "password", "token"], "security_agent"),
    (["database", "query", "sql", "schema", "etl", "table", "row", "column"], "data_agent"),
    (["webhook", "notify", "incident", "stakeholder", "slack"], "comms_agent"),
    (["customer", "support", "ticket", "help desk", "complaint"], "cs_agent"),
    (["cpu", "memory", "disk", "network", "uptime", "process", "system info", "infrastructure"], "it_agent"),
    (["search", "docs", "knowledge", "documentation", "source of truth"], "knowledge_agent"),
    (["reflect", "goal", "trust", "purpose", "mission", "remember", "soul"], "soul_core"),
]


def keyword_route(message: str) -> str:
    msg_lower = message.lower()
    scores: dict[str, int] = {}
    for keywords, agent_id in KEYWORD_MAP:
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[agent_id] = scores.get(agent_id, 0) + score
    if scores:
        return max(scores, key=scores.get)  # type: ignore
    return "soul_core"


# ── Red line check (exact patterns from fast_route.c) ──────────────

RED_LINE_PATTERNS = [
    re.compile(r"rm\s+-rf\b", re.IGNORECASE),
    re.compile(r"drop\s+table\b", re.IGNORECASE),
    re.compile(r"force\s+push|--force\b", re.IGNORECASE),
    re.compile(r"dd\s+if=", re.IGNORECASE),
    re.compile(r"chmod\s+777", re.IGNORECASE),
    re.compile(r"curl.*\|\s*bash", re.IGNORECASE),
    re.compile(r"exfiltrate|steal.*data", re.IGNORECASE),
    re.compile(r"disable.*firewall", re.IGNORECASE),
]


def check_red_line(message: str) -> bool:
    for pat in RED_LINE_PATTERNS:
        if pat.search(message):
            return True
    return False


# ── JSON parse (exact impl from lex_router.py) ────────────────────


def parse_response(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[^}]+\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Message split ──────────────────────────────────────────────────


def split_message(text: str, max_len: int = 2000) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while len(text) > max_len:
        split = max_len
        idx = text.rfind("\n", 0, max_len)
        if idx > max_len // 2:
            split = idx + 1
        chunks.append(text[:split])
        text = text[split:]
    if text:
        chunks.append(text)
    return chunks


# ── Validation ─────────────────────────────────────────────────────

VALID_AGENTS = {
    "auto",
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
}


def validate_input(agent_id: str, message: str) -> str | None:
    if not message:
        return "message is required"
    if len(message) > 10000:
        return "message too long"
    if agent_id and agent_id not in VALID_AGENTS:
        return f"invalid agent_id: {agent_id}"
    return None


# ── Benchmark runner ───────────────────────────────────────────────


def bench(name: str, func, iterations: int = 10000):
    start = time.perf_counter()
    for _ in range(iterations):
        func()
    elapsed = time.perf_counter() - start
    us_per_op = (elapsed * 1_000_000) / iterations
    print(f"{name:20s}: {elapsed * 1000:.1f}ms total, {us_per_op:.3f} µs/op")
    return us_per_op


def main():
    iterations = 10000
    resp_json = '{"agent_id": "devops_agent", "confidence": 0.95, "reasoning": "deploy"}'
    long_msg = "This is a test message with some content.\n" * 200

    print(f"\n=== Python Timing Results ({iterations:,} iterations) ===")

    py_route = bench("Keyword route", lambda: [keyword_route(m) for m in TEST_MESSAGES], iterations)
    py_redline = bench("Red line check", lambda: [check_red_line(m) for m in TEST_MESSAGES], iterations)
    py_json = bench("JSON parse", lambda: [parse_response(resp_json) for _ in range(4)], iterations)
    py_split = bench("Message split", lambda: split_message(long_msg), iterations)
    py_validate = bench("Validation", lambda: [validate_input("auto", m) for m in TEST_MESSAGES], iterations)

    def full_pipeline():
        for msg in TEST_MESSAGES:
            validate_input("auto", msg)
            if check_red_line(msg):
                continue
            keyword_route(msg)
            parse_response(resp_json)

    py_full = bench("Full pipeline", full_pipeline, iterations)

    # Output JSON for comparison script
    results = {
        "language": "python",
        "iterations": iterations,
        "results": {
            "keyword_route_us": py_route,
            "red_line_check_us": py_redline,
            "json_parse_us": py_json,
            "message_split_us": py_split,
            "validation_us": py_validate,
            "full_pipeline_us": py_full,
        },
    }
    with open("python_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print("\nResults saved to python_results.json")


if __name__ == "__main__":
    main()
