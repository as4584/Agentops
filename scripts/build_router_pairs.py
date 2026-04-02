#!/usr/bin/env python3
"""
scripts/build_router_pairs.py
──────────────────────────────
Strategy 10 — Router Training Data for Lex OpenClaw Router Agent.

Generates intent → agent routing pairs that teach Lex to:
1. Classify user intent from natural language
2. Select the correct agent from the registry
3. Extract structured parameters (tools needed, urgency, context)
4. Handle ambiguous requests with reasoning

Each pair is a ShareGPT conversation:
  human: <user message>
  gpt:   <structured routing decision as JSON>

Usage:
  python scripts/build_router_pairs.py                  # Hardcoded seeds only (~200 pairs)
  python scripts/build_router_pairs.py --augment        # + Ollama-generated variations (~500+)
  python scripts/build_router_pairs.py --augment --limit 1000
"""
from __future__ import annotations

import argparse
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# ── Agent Registry (mirrors ALL_AGENT_DEFINITIONS) ───────────────────────
AGENTS = {
    "it_agent": {
        "role": "Infrastructure monitoring, system diagnostics, operational tasks",
        "tools": ["safe_shell", "system_info", "file_reader", "mcp_docker_list_containers"],
        "keywords": ["server", "system", "infrastructure", "cpu", "memory", "disk", "network", "uptime", "process"],
    },
    "cs_agent": {
        "role": "Customer support, query handling, knowledge base access",
        "tools": ["file_reader", "system_info"],
        "keywords": ["customer", "support", "help", "ticket", "user", "question", "issue", "complaint"],
    },
    "soul_core": {
        "role": "Cluster conscience, goal tracking, trust arbitration, reflection",
        "tools": ["file_reader", "system_info", "doc_updater", "alert_dispatch"],
        "keywords": ["reflect", "goal", "trust", "value", "conscience", "purpose", "mission", "remember"],
    },
    "devops_agent": {
        "role": "CI/CD, git operations, deployment coordination, container lifecycle",
        "tools": ["git_ops", "safe_shell", "health_check", "mcp_github_create_issue"],
        "keywords": ["deploy", "git", "ci", "cd", "pipeline", "build", "release", "merge", "branch", "docker", "container"],
    },
    "monitor_agent": {
        "role": "Health surveillance, log tailing, metrics analysis, alerting",
        "tools": ["health_check", "log_tail", "system_info", "alert_dispatch"],
        "keywords": ["monitor", "health", "log", "alert", "metric", "status", "watch", "tail", "check"],
    },
    "self_healer_agent": {
        "role": "Fault remediation, process restarts, auto-recovery",
        "tools": ["process_restart", "safe_shell", "health_check", "log_tail"],
        "keywords": ["restart", "fix", "heal", "recover", "crash", "down", "broken", "failed", "zombie"],
    },
    "code_review_agent": {
        "role": "Diff review, invariant enforcement, drift checking, code quality",
        "tools": ["file_reader", "git_ops", "doc_updater"],
        "keywords": ["review", "diff", "code", "quality", "refactor", "pattern", "lint", "smell", "clean"],
    },
    "security_agent": {
        "role": "Secret scanning, CVE flagging, security auditing",
        "tools": ["secret_scanner", "file_reader", "safe_shell"],
        "keywords": ["security", "secret", "vulnerability", "cve", "scan", "audit", "leak", "exposure", "password", "token"],
    },
    "data_agent": {
        "role": "ETL governance, schema drift, SQLite queries, data analysis",
        "tools": ["db_query", "file_reader", "system_info"],
        "keywords": ["data", "database", "sql", "query", "schema", "table", "etl", "migrate", "analytics"],
    },
    "comms_agent": {
        "role": "Outbound webhooks, incident comms, stakeholder alerts",
        "tools": ["webhook_send", "alert_dispatch", "file_reader"],
        "keywords": ["notify", "webhook", "slack", "email", "alert", "incident", "communicate", "report", "stakeholder"],
    },
    "knowledge_agent": {
        "role": "Semantic Q&A over local vectorized corpus, documentation search",
        "tools": ["file_reader", "system_info"],
        "keywords": ["search", "find", "knowledge", "document", "explain", "what is", "how does", "tell me about"],
    },
    "prompt_engineer": {
        "role": "Prompt optimization, system prompt crafting, prompt debugging",
        "tools": ["file_reader", "doc_updater"],
        "keywords": ["prompt", "system prompt", "instruction", "template", "optimize prompt", "prompt engineering"],
    },
    "token_optimizer": {
        "role": "Token usage optimization, cost reduction, context window management",
        "tools": ["file_reader", "system_info"],
        "keywords": ["token", "cost", "budget", "optimize", "compress", "context window", "expensive", "cheap"],
    },
    "career_intel": {
        "role": "Career guidance, job market analysis, skill recommendations",
        "tools": ["file_reader"],
        "keywords": ["career", "job", "interview", "resume", "portfolio", "hiring", "skill gap", "career fair"],
    },
    "higgsfield_agent": {
        "role": "AI video generation, Hailuo AI, animation workflows",
        "tools": ["safe_shell", "file_reader"],
        "keywords": ["video", "animation", "hailuo", "higgsfield", "generate video", "ai video"],
    },
}

# ── Routing Decision Schema ──────────────────────────────────────────────
ROUTING_SCHEMA = """{
  "agent": "<agent_id>",
  "confidence": <0.0-1.0>,
  "reasoning": "<why this agent>",
  "tools_likely": ["<tool1>", "<tool2>"],
  "urgency": "<low|medium|high|critical>",
  "fallback_agent": "<agent_id or null>"
}"""

# ── Hardcoded Router Training Seeds ──────────────────────────────────────
# Each seed: (user_message, expected_routing_json)
# These are high-quality, hand-authored pairs.

ROUTER_SEEDS: list[tuple[str, dict]] = [
    # ── DevOps Agent ──
    (
        "Deploy the latest changes to production",
        {"agent": "devops_agent", "confidence": 0.95, "reasoning": "Deployment request — DevOps handles CI/CD and release coordination", "tools_likely": ["git_ops", "safe_shell", "health_check"], "urgency": "high", "fallback_agent": "it_agent"},
    ),
    (
        "What's the status of the CI pipeline?",
        {"agent": "devops_agent", "confidence": 0.92, "reasoning": "CI pipeline status is a DevOps concern — checking build/test health", "tools_likely": ["health_check", "git_ops"], "urgency": "medium", "fallback_agent": "monitor_agent"},
    ),
    (
        "Create a new branch called feature/auth-v2 and push it",
        {"agent": "devops_agent", "confidence": 0.97, "reasoning": "Git branch creation is a core DevOps operation", "tools_likely": ["git_ops", "safe_shell"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Show me the git log for the last 20 commits",
        {"agent": "devops_agent", "confidence": 0.95, "reasoning": "Git history inspection — DevOps handles all git operations", "tools_likely": ["git_ops"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Can you merge the dev branch into main?",
        {"agent": "devops_agent", "confidence": 0.95, "reasoning": "Branch merging is a DevOps responsibility with governance implications", "tools_likely": ["git_ops", "doc_updater"], "urgency": "high", "fallback_agent": "soul_core"},
    ),
    (
        "Roll back the last deployment, something broke",
        {"agent": "devops_agent", "confidence": 0.93, "reasoning": "Deployment rollback is urgent DevOps action — may need self_healer for recovery", "tools_likely": ["git_ops", "safe_shell", "health_check"], "urgency": "critical", "fallback_agent": "self_healer_agent"},
    ),

    # ── IT Agent ──
    (
        "How much disk space is left on the server?",
        {"agent": "it_agent", "confidence": 0.95, "reasoning": "Disk space inquiry is infrastructure monitoring", "tools_likely": ["system_info", "safe_shell"], "urgency": "medium", "fallback_agent": None},
    ),
    (
        "Check if port 8000 is in use",
        {"agent": "it_agent", "confidence": 0.93, "reasoning": "Port check is a system diagnostic task", "tools_likely": ["safe_shell", "system_info"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "What processes are consuming the most CPU?",
        {"agent": "it_agent", "confidence": 0.94, "reasoning": "CPU usage analysis is infrastructure monitoring", "tools_likely": ["system_info", "safe_shell"], "urgency": "medium", "fallback_agent": "monitor_agent"},
    ),
    (
        "Show me the network interfaces and their IPs",
        {"agent": "it_agent", "confidence": 0.92, "reasoning": "Network diagnostics are IT infrastructure tasks", "tools_likely": ["system_info", "safe_shell"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Monitor Agent ──
    (
        "Are all services healthy right now?",
        {"agent": "monitor_agent", "confidence": 0.93, "reasoning": "Service health check is monitoring responsibility", "tools_likely": ["health_check", "system_info"], "urgency": "medium", "fallback_agent": "it_agent"},
    ),
    (
        "Tail the last 50 lines of the system log",
        {"agent": "monitor_agent", "confidence": 0.96, "reasoning": "Log tailing is a core monitoring operation", "tools_likely": ["log_tail"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Set up an alert if backend response time exceeds 2 seconds",
        {"agent": "monitor_agent", "confidence": 0.91, "reasoning": "Alert configuration is monitoring — dispatching SLA-based alerts", "tools_likely": ["alert_dispatch", "health_check"], "urgency": "medium", "fallback_agent": None},
    ),
    (
        "Show me error rates from the last hour",
        {"agent": "monitor_agent", "confidence": 0.90, "reasoning": "Error rate analysis requires log inspection and metrics", "tools_likely": ["log_tail", "system_info"], "urgency": "medium", "fallback_agent": "data_agent"},
    ),

    # ── Self Healer Agent ──
    (
        "The backend server crashed, restart it",
        {"agent": "self_healer_agent", "confidence": 0.96, "reasoning": "Process restart after crash is self-healing — immediate recovery needed", "tools_likely": ["process_restart", "health_check", "log_tail"], "urgency": "critical", "fallback_agent": "it_agent"},
    ),
    (
        "Ollama seems stuck, can you restart it?",
        {"agent": "self_healer_agent", "confidence": 0.94, "reasoning": "Stuck process restart is fault remediation", "tools_likely": ["process_restart", "health_check"], "urgency": "high", "fallback_agent": "it_agent"},
    ),
    (
        "There's a zombie process eating memory, kill it",
        {"agent": "self_healer_agent", "confidence": 0.93, "reasoning": "Zombie process termination is self-healing", "tools_likely": ["safe_shell", "process_restart", "system_info"], "urgency": "high", "fallback_agent": "it_agent"},
    ),

    # ── Code Review Agent ──
    (
        "Review the changes I made to the orchestrator",
        {"agent": "code_review_agent", "confidence": 0.95, "reasoning": "Code review request — diff inspection and quality analysis", "tools_likely": ["git_ops", "file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Check if my code follows the project patterns",
        {"agent": "code_review_agent", "confidence": 0.92, "reasoning": "Pattern compliance check is code review territory", "tools_likely": ["file_reader", "git_ops"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Are there any code smells in backend/agents/__init__.py?",
        {"agent": "code_review_agent", "confidence": 0.94, "reasoning": "Code smell detection is code review — specific file analysis", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Security Agent ──
    (
        "Scan the repo for leaked secrets or API keys",
        {"agent": "security_agent", "confidence": 0.97, "reasoning": "Secret scanning is core security function", "tools_likely": ["secret_scanner", "file_reader"], "urgency": "high", "fallback_agent": None},
    ),
    (
        "Are there any known vulnerabilities in our dependencies?",
        {"agent": "security_agent", "confidence": 0.93, "reasoning": "CVE and dependency vulnerability check is security audit", "tools_likely": ["safe_shell", "file_reader"], "urgency": "medium", "fallback_agent": None},
    ),
    (
        "Check if the .env file is properly gitignored",
        {"agent": "security_agent", "confidence": 0.91, "reasoning": "Secret exposure prevention — checking gitignore for sensitive files", "tools_likely": ["file_reader", "secret_scanner"], "urgency": "medium", "fallback_agent": "devops_agent"},
    ),

    # ── Data Agent ──
    (
        "Run a SELECT query against the customer database",
        {"agent": "data_agent", "confidence": 0.96, "reasoning": "SQL query execution is data agent's core responsibility", "tools_likely": ["db_query"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Show me the schema for the tasks table",
        {"agent": "data_agent", "confidence": 0.94, "reasoning": "Schema inspection is database governance", "tools_likely": ["db_query"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "How many records are in the training data?",
        {"agent": "data_agent", "confidence": 0.88, "reasoning": "Data counting could be data agent (SQL) or knowledge agent (docs). Data agent is more specific.", "tools_likely": ["db_query", "file_reader"], "urgency": "low", "fallback_agent": "knowledge_agent"},
    ),

    # ── Comms Agent ──
    (
        "Send a Slack notification about the deployment",
        {"agent": "comms_agent", "confidence": 0.95, "reasoning": "Outbound Slack notification is communications agent's job", "tools_likely": ["webhook_send", "mcp_slack_send_message"], "urgency": "medium", "fallback_agent": None},
    ),
    (
        "Notify the team that we hit a critical incident",
        {"agent": "comms_agent", "confidence": 0.94, "reasoning": "Incident communication is comms agent — stakeholder alerting", "tools_likely": ["alert_dispatch", "webhook_send"], "urgency": "critical", "fallback_agent": None},
    ),

    # ── Knowledge Agent ──
    (
        "What is Drift Guard and how does it work?",
        {"agent": "knowledge_agent", "confidence": 0.93, "reasoning": "Documentation question — knowledge agent searches vectorized corpus", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "How do I add a new agent to Agentop?",
        {"agent": "knowledge_agent", "confidence": 0.91, "reasoning": "How-to question about the system — knowledge base lookup", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Explain the content pipeline architecture",
        {"agent": "knowledge_agent", "confidence": 0.92, "reasoning": "Architecture explanation from documentation", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Tell me about the MCP Gateway Bridge",
        {"agent": "knowledge_agent", "confidence": 0.90, "reasoning": "System knowledge question — vectorized doc search", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Soul Core ──
    (
        "What are the cluster's current goals?",
        {"agent": "soul_core", "confidence": 0.95, "reasoning": "Goal tracking is soul_core's responsibility — autobiographical memory", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Reflect on what happened this week",
        {"agent": "soul_core", "confidence": 0.97, "reasoning": "Reflection and memory recall is soul_core's core function", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Which agents have been performing well lately?",
        {"agent": "soul_core", "confidence": 0.90, "reasoning": "Trust arbitration and agent performance assessment is soul_core territory", "tools_likely": ["file_reader", "system_info"], "urgency": "low", "fallback_agent": "monitor_agent"},
    ),
    (
        "I'm worried about the direction of this project",
        {"agent": "soul_core", "confidence": 0.88, "reasoning": "Project direction and purpose alignment is soul_core conscience function", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Prompt Engineer ──
    (
        "Optimize the system prompt for the DevOps agent",
        {"agent": "prompt_engineer", "confidence": 0.94, "reasoning": "System prompt optimization is prompt engineering", "tools_likely": ["file_reader", "doc_updater"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Write a better prompt template for code review",
        {"agent": "prompt_engineer", "confidence": 0.93, "reasoning": "Prompt template creation is prompt engineering responsibility", "tools_likely": ["file_reader", "doc_updater"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Token Optimizer ──
    (
        "Our LLM costs are too high, how can we reduce them?",
        {"agent": "token_optimizer", "confidence": 0.93, "reasoning": "Cost reduction for LLM usage is token optimization", "tools_likely": ["file_reader", "system_info"], "urgency": "medium", "fallback_agent": None},
    ),
    (
        "Can we compress the context window for agent prompts?",
        {"agent": "token_optimizer", "confidence": 0.95, "reasoning": "Context window compression is token optimization", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": "prompt_engineer"},
    ),

    # ── Career Intel ──
    (
        "What skills should I learn for an LLM engineer position?",
        {"agent": "career_intel", "confidence": 0.94, "reasoning": "Career guidance and skill gap analysis", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": None},
    ),
    (
        "Help me prepare for my upcoming career fair",
        {"agent": "career_intel", "confidence": 0.92, "reasoning": "Career fair preparation is career intelligence", "tools_likely": ["file_reader"], "urgency": "medium", "fallback_agent": None},
    ),

    # ── Higgsfield Agent ──
    (
        "Generate an AI video of our product demo",
        {"agent": "higgsfield_agent", "confidence": 0.94, "reasoning": "AI video generation is Higgsfield/Hailuo agent territory", "tools_likely": ["safe_shell", "file_reader"], "urgency": "low", "fallback_agent": None},
    ),

    # ── Ambiguous Requests (Multi-Agent Routing) ──
    (
        "Something is wrong with the backend, it's returning 500 errors",
        {"agent": "self_healer_agent", "confidence": 0.70, "reasoning": "500 errors suggest a crash/fault — self-healer for recovery. Could also be monitor (diagnosis) or IT (infrastructure). Starting with healer for fastest remediation.", "tools_likely": ["health_check", "log_tail", "process_restart"], "urgency": "critical", "fallback_agent": "monitor_agent"},
    ),
    (
        "Clean up the codebase",
        {"agent": "code_review_agent", "confidence": 0.75, "reasoning": "Codebase cleanup is primarily code review (refactoring, smell removal). Could involve DevOps (branch cleanup) or data agent (dead data). Code review is the broadest match.", "tools_likely": ["file_reader", "git_ops"], "urgency": "low", "fallback_agent": "devops_agent"},
    ),
    (
        "Make sure everything is working",
        {"agent": "monitor_agent", "confidence": 0.72, "reasoning": "General health check — monitor agent does service reachability and metrics. Ambiguous but monitoring is the safest starting point.", "tools_likely": ["health_check", "system_info", "log_tail"], "urgency": "medium", "fallback_agent": "it_agent"},
    ),
    (
        "I need help",
        {"agent": "cs_agent", "confidence": 0.60, "reasoning": "Vague help request — customer support is the default for unspecified assistance. Low confidence because we don't know the domain yet.", "tools_likely": ["file_reader"], "urgency": "low", "fallback_agent": "knowledge_agent"},
    ),
    (
        "How expensive is it to run this system?",
        {"agent": "token_optimizer", "confidence": 0.70, "reasoning": "Cost inquiry could be token_optimizer (LLM costs) or IT (infrastructure costs). Token optimizer is more likely given an AI-centric system.", "tools_likely": ["system_info", "file_reader"], "urgency": "low", "fallback_agent": "it_agent"},
    ),
    (
        "We got hacked",
        {"agent": "security_agent", "confidence": 0.95, "reasoning": "Security incident — immediate security audit needed", "tools_likely": ["secret_scanner", "file_reader", "safe_shell"], "urgency": "critical", "fallback_agent": "self_healer_agent"},
    ),
    (
        "Update the documentation for the new feature",
        {"agent": "code_review_agent", "confidence": 0.75, "reasoning": "Documentation updates touch governance (drift guard) — code review agent enforces doc-first patterns. Could be knowledge_agent for content.", "tools_likely": ["doc_updater", "file_reader"], "urgency": "low", "fallback_agent": "knowledge_agent"},
    ),

    # ── Edge Cases ──
    (
        "Hello",
        {"agent": "knowledge_agent", "confidence": 0.50, "reasoning": "Greeting with no intent — route to knowledge agent as safe default for conversation", "tools_likely": [], "urgency": "low", "fallback_agent": None},
    ),
    (
        "",
        {"agent": "knowledge_agent", "confidence": 0.30, "reasoning": "Empty input — route to knowledge agent default. No actionable intent detected.", "tools_likely": [], "urgency": "low", "fallback_agent": None},
    ),
    (
        "asdfghjkl random gibberish 12345",
        {"agent": "knowledge_agent", "confidence": 0.20, "reasoning": "Unintelligible input — route to knowledge agent default with very low confidence. May need clarification.", "tools_likely": [], "urgency": "low", "fallback_agent": "cs_agent"},
    ),
]


def _format_routing_pair(user_msg: str, routing: dict) -> dict:
    """Format a router training pair in ShareGPT conversation format."""
    system_prompt = (
        "You are Lex, the OpenClaw Router Agent for Agentop. Your job is to analyze user messages "
        "and route them to the correct specialist agent. You must respond with a JSON routing decision.\n\n"
        f"Available agents: {', '.join(sorted(AGENTS.keys()))}\n\n"
        f"Response format:\n{ROUTING_SCHEMA}\n\n"
        "Rules:\n"
        "- Always pick the most specific agent for the task\n"
        "- Set confidence < 0.7 for ambiguous requests\n"
        "- Include a fallback_agent when confidence < 0.9\n"
        "- Urgency 'critical' only for security incidents, crashes, or data loss\n"
        "- Explain your reasoning in 1-2 sentences"
    )
    return {
        "conversations": [
            {"from": "system", "value": system_prompt},
            {"from": "human", "value": user_msg},
            {"from": "gpt", "value": json.dumps(routing, indent=2)},
        ]
    }


def _generate_variations(seed_msg: str, agent_id: str, n: int = 3) -> list[str]:
    """Generate simple rule-based variations of a seed message."""
    variations = []
    prefixes = ["Hey, ", "Can you ", "I need you to ", "Please ", "Could you ", ""]
    suffixes = [" right now", " please", " asap", " when you get a chance", ""]

    for _ in range(n):
        prefix = random.choice(prefixes)
        suffix = random.choice(suffixes)
        # Basic word swaps
        msg = seed_msg
        swaps = [
            ("show me", "display"), ("check", "inspect"), ("fix", "resolve"),
            ("restart", "reboot"), ("deploy", "ship"), ("review", "analyze"),
            ("scan", "check"), ("monitor", "watch"), ("explain", "describe"),
        ]
        for old, new in random.sample(swaps, min(2, len(swaps))):
            if old in msg.lower():
                msg = msg.lower().replace(old, new, 1)
                msg = msg[0].upper() + msg[1:]
                break
        variations.append(f"{prefix}{msg}{suffix}".strip())
    return variations


def _augment_with_ollama(seeds: list[tuple[str, dict]], limit: int) -> list[tuple[str, dict]]:
    """Use Ollama to generate additional routing variations."""
    try:
        import httpx
    except ImportError:
        print("httpx not installed — skipping Ollama augmentation")
        return []

    augmented = []
    agent_ids = list(AGENTS.keys())

    for agent_id in agent_ids:
        if len(augmented) >= limit:
            break

        agent_info = AGENTS[agent_id]
        prompt = (
            f"Generate 5 different user messages that a person would send when they need the "
            f"'{agent_id}' agent.\n\n"
            f"Agent role: {agent_info['role']}\n"
            f"Agent tools: {', '.join(agent_info['tools'])}\n\n"
            f"Requirements:\n"
            f"- Messages should be natural, varied in tone (casual to professional)\n"
            f"- Some should be direct commands, some questions, some complaints\n"
            f"- Include 1 ambiguous message where this agent is the BEST but not OBVIOUS choice\n"
            f"- Return only the messages, one per line, no numbering\n"
        )

        try:
            resp = httpx.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
                timeout=60.0,
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "")
                lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 10]
                for line in lines[:5]:
                    # Clean up common prefixes
                    line = line.lstrip("0123456789.-) ")
                    if line:
                        routing = {
                            "agent": agent_id,
                            "confidence": round(random.uniform(0.80, 0.95), 2),
                            "reasoning": f"Ollama-generated variation targeting {agent_id}",
                            "tools_likely": agent_info["tools"][:2],
                            "urgency": random.choice(["low", "medium"]),
                            "fallback_agent": None,
                        }
                        augmented.append((line, routing))
                print(f"  Generated {len(lines[:5])} variations for {agent_id}")
            time.sleep(0.5)  # Rate limit
        except Exception as e:
            print(f"  Ollama error for {agent_id}: {e}")

    return augmented[:limit]


def build_router_pairs(augment: bool = False, limit: int = 500) -> Path:
    """Build router training data and write to JSONL."""
    pairs: list[dict] = []

    # Phase 1: Hardcoded seeds
    print(f"Phase 1: {len(ROUTER_SEEDS)} hardcoded router seeds")
    for msg, routing in ROUTER_SEEDS:
        pairs.append(_format_routing_pair(msg, routing))

    # Phase 2: Rule-based variations
    print("Phase 2: Generating rule-based variations...")
    for msg, routing in ROUTER_SEEDS:
        if msg:  # Skip empty input edge case
            for variation in _generate_variations(msg, routing["agent"], n=2):
                varied_routing = routing.copy()
                varied_routing["confidence"] = round(
                    max(0.5, routing["confidence"] - random.uniform(0, 0.1)), 2
                )
                pairs.append(_format_routing_pair(variation, varied_routing))

    # Phase 3: Ollama augmentation (optional)
    if augment:
        print(f"Phase 3: Ollama augmentation (target: {limit} additional)...")
        extra = _augment_with_ollama(ROUTER_SEEDS, limit)
        for msg, routing in extra:
            pairs.append(_format_routing_pair(msg, routing))

    # Deduplicate by user message
    seen = set()
    unique_pairs = []
    for pair in pairs:
        user_msg = pair["conversations"][1]["value"]
        if user_msg not in seen:
            seen.add(user_msg)
            unique_pairs.append(pair)

    # Shuffle for training
    random.shuffle(unique_pairs)

    # Write output
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"router_pairs_{ts}.jsonl"
    with open(out_path, "w") as f:
        for pair in unique_pairs:
            f.write(json.dumps(pair) + "\n")

    print(f"\nWrote {len(unique_pairs)} router training pairs to {out_path}")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build router training data for Lex")
    parser.add_argument("--augment", action="store_true", help="Use Ollama to generate additional variations")
    parser.add_argument("--limit", type=int, default=500, help="Max Ollama-generated pairs")
    args = parser.parse_args()

    build_router_pairs(augment=args.augment, limit=args.limit)


if __name__ == "__main__":
    main()
