#!/usr/bin/env python3
"""
scripts/build_tool_selection_pairs.py
─────────────────────────────────────
Strategy 11 — Tool Selection Training Data for Lex.

Teaches Lex to select the right tools for a given task,
considering tool types (READ_ONLY, STATE_MODIFY, ARCH_MODIFY),
risk levels, and governance constraints.

Usage:
  python scripts/build_tool_selection_pairs.py
  python scripts/build_tool_selection_pairs.py --augment
"""
from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Tool Registry (mirrors backend/tools/__init__.py) ────────────────────
TOOLS = {
    "safe_shell": {"type": "STATE_MODIFY", "desc": "Execute whitelisted shell commands", "risk": "medium"},
    "file_reader": {"type": "READ_ONLY", "desc": "Read file contents safely", "risk": "low"},
    "doc_updater": {"type": "ARCH_MODIFY", "desc": "Update governance documentation", "risk": "high"},
    "system_info": {"type": "READ_ONLY", "desc": "Retrieve system information", "risk": "low"},
    "webhook_send": {"type": "STATE_MODIFY", "desc": "HTTP POST to external endpoints", "risk": "medium"},
    "git_ops": {"type": "READ_ONLY", "desc": "Whitelisted git subcommands", "risk": "low"},
    "health_check": {"type": "READ_ONLY", "desc": "HTTP reachability check", "risk": "low"},
    "log_tail": {"type": "READ_ONLY", "desc": "Tail N lines from a log file", "risk": "low"},
    "alert_dispatch": {"type": "STATE_MODIFY", "desc": "Write structured alert to shared events", "risk": "medium"},
    "secret_scanner": {"type": "READ_ONLY", "desc": "8-pattern regex scan for secrets", "risk": "low"},
    "db_query": {"type": "READ_ONLY", "desc": "SELECT/PRAGMA against local SQLite", "risk": "low"},
    "process_restart": {"type": "STATE_MODIFY", "desc": "Restart whitelisted processes", "risk": "high"},
}

TOOL_SELECTION_SCHEMA = """{
  "primary_tool": "<tool_name>",
  "secondary_tools": ["<tool_name>", ...],
  "reasoning": "<why these tools>",
  "risk_level": "<low|medium|high>",
  "requires_governance_check": <true|false>,
  "estimated_steps": <int>
}"""

# ── Training Seeds ───────────────────────────────────────────────────────
TOOL_SEEDS: list[tuple[str, dict]] = [
    # READ_ONLY operations
    (
        "Read the contents of backend/config.py",
        {"primary_tool": "file_reader", "secondary_tools": [], "reasoning": "Simple file read — file_reader is the correct READ_ONLY tool", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "What's the current system memory usage?",
        {"primary_tool": "system_info", "secondary_tools": [], "reasoning": "System metrics retrieval — system_info provides CPU/memory/disk data", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "Check the git log for recent commits",
        {"primary_tool": "git_ops", "secondary_tools": [], "reasoning": "Git history is read-only — git_ops handles whitelisted git subcommands", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "Is the backend server responding on port 8000?",
        {"primary_tool": "health_check", "secondary_tools": [], "reasoning": "HTTP reachability check — health_check pings the endpoint", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "Show the last 100 lines of system.jsonl",
        {"primary_tool": "log_tail", "secondary_tools": [], "reasoning": "Log file tailing — log_tail reads N lines from end of file", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "Scan for any exposed API keys in the codebase",
        {"primary_tool": "secret_scanner", "secondary_tools": ["file_reader"], "reasoning": "Secret scanning with regex patterns. May need file_reader for deeper inspection of flagged files.", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 2},
    ),
    (
        "How many rows are in the customers table?",
        {"primary_tool": "db_query", "secondary_tools": [], "reasoning": "SQL count query — db_query handles SELECT against SQLite", "risk_level": "low", "requires_governance_check": False, "estimated_steps": 1},
    ),

    # STATE_MODIFY operations
    (
        "Run the test suite with pytest",
        {"primary_tool": "safe_shell", "secondary_tools": ["log_tail"], "reasoning": "Executing pytest requires shell access. Log tail useful for capturing output.", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 2},
    ),
    (
        "Send a webhook notification to the team Slack channel",
        {"primary_tool": "webhook_send", "secondary_tools": [], "reasoning": "Outbound HTTP POST — webhook_send for external communication", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 1},
    ),
    (
        "Dispatch a critical alert about the database outage",
        {"primary_tool": "alert_dispatch", "secondary_tools": ["health_check", "log_tail"], "reasoning": "Alert dispatch writes to shared events. Health check confirms outage. Log tail for evidence.", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 3},
    ),
    (
        "Restart the Ollama service",
        {"primary_tool": "process_restart", "secondary_tools": ["health_check"], "reasoning": "Process restart is high-risk STATE_MODIFY. Health check to verify recovery after restart.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 2},
    ),

    # ARCH_MODIFY operations
    (
        "Update the SOURCE_OF_TRUTH.md with the new agent definition",
        {"primary_tool": "doc_updater", "secondary_tools": ["file_reader"], "reasoning": "Documentation update is ARCH_MODIFY — requires drift guard check. Read current doc first.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 2},
    ),
    (
        "Add the new API endpoint documentation to CHANGE_LOG.md",
        {"primary_tool": "doc_updater", "secondary_tools": ["file_reader"], "reasoning": "Change log update is ARCH_MODIFY. Must read existing log to append correctly.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 2},
    ),

    # Multi-tool workflows
    (
        "Diagnose why the backend is returning 500 errors",
        {"primary_tool": "health_check", "secondary_tools": ["log_tail", "system_info", "safe_shell"], "reasoning": "Multi-step diagnosis: 1) health_check confirms 500, 2) log_tail finds error, 3) system_info checks resources, 4) safe_shell for deeper inspection if needed.", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 4},
    ),
    (
        "Run a full security audit of the project",
        {"primary_tool": "secret_scanner", "secondary_tools": ["file_reader", "git_ops", "db_query"], "reasoning": "Comprehensive audit: 1) secret_scanner for leaked keys, 2) file_reader for config files, 3) git_ops for sensitive history, 4) db_query for stored credentials.", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 4},
    ),
    (
        "Deploy the application: run tests, build, then alert the team",
        {"primary_tool": "safe_shell", "secondary_tools": ["health_check", "git_ops", "webhook_send", "doc_updater"], "reasoning": "Multi-step deployment: 1) safe_shell runs tests+build, 2) git_ops for version tagging, 3) health_check verifies deployment, 4) webhook_send notifies team, 5) doc_updater logs the release.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 5},
    ),
    (
        "A process crashed and we need to recover — restart it, check health, alert the team, and log the incident",
        {"primary_tool": "process_restart", "secondary_tools": ["health_check", "log_tail", "alert_dispatch", "doc_updater"], "reasoning": "Incident response workflow: 1) process_restart for recovery, 2) health_check confirms restoration, 3) log_tail captures crash evidence, 4) alert_dispatch notifies, 5) doc_updater logs incident.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 5},
    ),

    # Governance-aware decisions
    (
        "Delete the old log files to free up space",
        {"primary_tool": "safe_shell", "secondary_tools": ["system_info"], "reasoning": "File deletion via shell is STATE_MODIFY. Check disk usage with system_info first. Deletion of logs should be cautious — verify they're not needed.", "risk_level": "medium", "requires_governance_check": False, "estimated_steps": 2},
    ),
    (
        "Modify the agent registry to add a new agent",
        {"primary_tool": "doc_updater", "secondary_tools": ["file_reader"], "reasoning": "Adding an agent requires AGENT_REGISTRY.md update FIRST (docs-first governance). This is ARCH_MODIFY and requires drift guard approval.", "risk_level": "high", "requires_governance_check": True, "estimated_steps": 3},
    ),
]


def _format_tool_pair(task: str, selection: dict) -> dict:
    """Format a tool selection training pair in ShareGPT conversation format."""
    system_prompt = (
        "You are Lex, the OpenClaw Tool Selection Engine. Given a task description, "
        "select the optimal tools from the Agentop tool registry.\n\n"
        f"Available tools:\n"
        + "\n".join(f"- {name}: {info['desc']} [{info['type']}] (risk: {info['risk']})" for name, info in TOOLS.items())
        + f"\n\nResponse format:\n{TOOL_SELECTION_SCHEMA}\n\n"
        "Rules:\n"
        "- Prefer READ_ONLY tools over STATE_MODIFY when possible\n"
        "- ARCH_MODIFY tools always require governance_check=true\n"
        "- Multi-step workflows should list tools in execution order\n"
        "- Set risk_level to the HIGHEST risk among selected tools"
    )
    return {
        "conversations": [
            {"from": "system", "value": system_prompt},
            {"from": "human", "value": task},
            {"from": "gpt", "value": json.dumps(selection, indent=2)},
        ]
    }


def build_tool_selection_pairs(augment: bool = False) -> Path:
    """Build tool selection training data."""
    pairs: list[dict] = []

    print(f"Phase 1: {len(TOOL_SEEDS)} hardcoded tool selection seeds")
    for task, selection in TOOL_SEEDS:
        pairs.append(_format_tool_pair(task, selection))

    # Phase 2: Variations
    print("Phase 2: Generating variations...")
    for task, selection in TOOL_SEEDS:
        rephrases = [
            task.replace("Read", "Show me").replace("Check", "Verify"),
            "I need to: " + task.lower(),
            "Can you " + task[0].lower() + task[1:] + "?",
        ]
        for rephrase in rephrases:
            varied = selection.copy()
            pairs.append(_format_tool_pair(rephrase, varied))

    # Deduplicate
    seen = set()
    unique = []
    for p in pairs:
        key = p["conversations"][1]["value"]
        if key not in seen:
            seen.add(key)
            unique.append(p)

    random.shuffle(unique)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"tool_selection_pairs_{ts}.jsonl"
    with open(out_path, "w") as f:
        for pair in unique:
            f.write(json.dumps(pair) + "\n")

    print(f"\nWrote {len(unique)} tool selection training pairs to {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build tool selection training data for Lex")
    parser.add_argument("--augment", action="store_true", help="Use Ollama augmentation")
    args = parser.parse_args()
    build_tool_selection_pairs(augment=args.augment)


if __name__ == "__main__":
    main()
