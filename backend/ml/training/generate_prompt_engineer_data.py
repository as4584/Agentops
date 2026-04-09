"""Generate gold training data for the prompt_engineer agent.

Produces 1500 ShareGPT-format JSONL examples.

Input: messy user message (typos, vague goals, partial context, available tools/agents)
Output: structured prompt with goal, constraints, success_criteria, task_type,
        recommended_agent, compressed_context, missing_assumptions

Usage:
    python -m backend.ml.training.generate_prompt_engineer_data
    python -m backend.ml.training.generate_prompt_engineer_data --count 500
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

# ── Templates ────────────────────────────────────────────────────────

_AGENTS = [
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
    "prompt_engineer",
    "education_agent",
    "higgsfield_agent",
]

_TOOLS = [
    "safe_shell",
    "file_reader",
    "doc_updater",
    "system_info",
    "webhook_send",
    "git_ops",
    "health_check",
    "log_tail",
    "alert_dispatch",
    "secret_scanner",
    "db_query",
    "process_restart",
    "document_ocr",
]

_TASK_TYPES = [
    "deployment",
    "debugging",
    "code_review",
    "monitoring",
    "security_scan",
    "data_query",
    "documentation",
    "incident_response",
    "knowledge_search",
    "prompt_optimization",
    "content_creation",
    "infrastructure",
    "customer_support",
    "education",
    "video_production",
]

# Messy input templates — typos, vague, incomplete, run-on sentences
_MESSY_TEMPLATES: list[dict] = [
    # --- DEPLOYMENT / DEVOPS ---
    {
        "messy": "hey can u deploy the thingy to prod? the branch is like {branch} or something",
        "goal": "Deploy branch '{branch}' to the production environment",
        "constraints": ["Must deploy from the specified branch", "Requires CI green status before deploy"],
        "task_type": "deployment",
        "agent": "devops_agent",
        "tools": ["git_ops", "safe_shell", "health_check"],
        "missing": ["Which environment (staging/production)?", "Is there a deployment window?"],
        "difficulty": "easy",
    },
    {
        "messy": "ok so basically i need to like... push my stuff but not to main, maybe dev? idk the branch rules",
        "goal": "Push current changes to the 'dev' branch following branch protection rules",
        "constraints": ["Never push directly to main", "Must push to dev branch", "Run CI checks first"],
        "task_type": "deployment",
        "agent": "devops_agent",
        "tools": ["git_ops"],
        "missing": ["Are changes committed?", "Is there a feature branch to merge?"],
        "difficulty": "easy",
    },
    {
        "messy": "docker container keeps dying, restarted it 3 times today already, logs say something about port {port}",
        "goal": "Diagnose and fix Docker container crash loop caused by port {port} conflict",
        "constraints": [
            "Container has crashed 3+ times today",
            "Port {port} conflict suspected",
            "Check logs before restart",
        ],
        "task_type": "debugging",
        "agent": "self_healer_agent",
        "tools": ["log_tail", "process_restart", "safe_shell", "health_check"],
        "missing": ["Which container image/name?", "Is another service using port {port}?"],
        "difficulty": "medium",
    },
    {
        "messy": "um so i wrote some code and its probably fine but maybe check it? its in {file}",
        "goal": "Perform code review on '{file}' for quality, patterns, and potential issues",
        "constraints": ["Review the specified file", "Check for code smells, lint issues, and pattern violations"],
        "task_type": "code_review",
        "agent": "code_review_agent",
        "tools": ["file_reader", "git_ops"],
        "missing": ["What kind of changes were made?", "Is this part of a PR?"],
        "difficulty": "easy",
    },
    {
        "messy": "yo check if theres any secrets leaking in the repo, someone might have commited a key or something idk",
        "goal": "Scan the repository for accidentally committed secrets, API keys, and credentials",
        "constraints": ["Scan all tracked files", "Check for common secret patterns (API keys, passwords, tokens)"],
        "task_type": "security_scan",
        "agent": "security_agent",
        "tools": ["secret_scanner", "file_reader", "git_ops"],
        "missing": ["Scan entire repo or specific directories?", "Any known false positives to exclude?"],
        "difficulty": "easy",
    },
    {
        "messy": "the api is slow or something, maybe the database? queries taking forever, users complaining about {table}",
        "goal": "Diagnose slow API performance caused by database queries on table '{table}'",
        "constraints": [
            "Users reporting slow responses",
            "Suspected database bottleneck on '{table}'",
            "Need query performance analysis",
        ],
        "task_type": "debugging",
        "agent": "data_agent",
        "tools": ["db_query", "log_tail", "system_info"],
        "missing": [
            "Which specific API endpoint is slow?",
            "What's the acceptable response time?",
            "How many concurrent users?",
        ],
        "difficulty": "hard",
    },
    {
        "messy": "help i accidentally did something to the config and now nothing works, i think i changed {file} but im not sure",
        "goal": "Recover from a broken configuration change, likely in '{file}'",
        "constraints": [
            "System is currently broken",
            "Configuration change was accidental",
            "Need to identify and revert the change",
        ],
        "task_type": "incident_response",
        "agent": "devops_agent",
        "tools": ["file_reader", "git_ops", "safe_shell"],
        "missing": ["What symptoms are you seeing?", "Was the change committed to git?", "When did it last work?"],
        "difficulty": "hard",
    },
    # --- MONITORING ---
    {
        "messy": "is everything ok? havent checked in a while, just wanna make sure nothings on fire lol",
        "goal": "Run a comprehensive health check on all core services (backend, frontend, Ollama, database)",
        "constraints": ["Check all services", "Report any degraded or down services"],
        "task_type": "monitoring",
        "agent": "monitor_agent",
        "tools": ["health_check", "system_info", "log_tail"],
        "missing": ["Any specific services of concern?", "What was the last known good state?"],
        "difficulty": "easy",
    },
    {
        "messy": "cpu is like at {pct}% and idk why, nothing should be running that hard rn",
        "goal": "Investigate unexpectedly high CPU usage ({pct}%) and identify the offending process",
        "constraints": ["CPU at {pct}%", "No expected heavy workload", "Need process-level breakdown"],
        "task_type": "infrastructure",
        "agent": "it_agent",
        "tools": ["system_info", "safe_shell", "log_tail"],
        "missing": ["Which machine/container?", "How long has CPU been elevated?"],
        "difficulty": "medium",
    },
    # --- KNOWLEDGE / DOCS ---
    {
        "messy": "where does it say how the router works? i read something about lex but cant find it",
        "goal": "Find documentation about the Lex router architecture and routing pipeline",
        "constraints": [
            "Search governance docs and source of truth",
            "Look for lex_router, routing pipeline, C fast router",
        ],
        "task_type": "knowledge_search",
        "agent": "knowledge_agent",
        "tools": ["file_reader"],
        "missing": ["Looking for implementation details or high-level architecture?"],
        "difficulty": "easy",
    },
    {
        "messy": "so like can you explain what drift guard does? i see it mentioned everywhere but honestly idk what it actually does",
        "goal": "Explain the Drift Guard middleware — its purpose, invariants, and how it intercepts tool calls",
        "constraints": [
            "Reference DRIFT_GUARD.md and SOURCE_OF_TRUTH.md",
            "Provide concrete examples of intercepted violations",
        ],
        "task_type": "knowledge_search",
        "agent": "knowledge_agent",
        "tools": ["file_reader"],
        "missing": [],
        "difficulty": "easy",
    },
    # --- CUSTOMER SUPPORT ---
    {
        "messy": "theres a customer asking about {topic} and i have no idea what to tell them, can you draft something?",
        "goal": "Draft a professional customer support response about '{topic}'",
        "constraints": [
            "Must be professional and helpful",
            "Reference knowledge base if applicable",
            "Don't make promises about features",
        ],
        "task_type": "customer_support",
        "agent": "cs_agent",
        "tools": ["file_reader", "db_query"],
        "missing": [
            "What specific question did the customer ask?",
            "Is this an existing customer?",
            "Any ticket/case number?",
        ],
        "difficulty": "medium",
    },
    # --- INCIDENT / ALERTS ---
    {
        "messy": "EVERYTHING IS DOWN!! the backend crashed and frontend cant connect and ollama is timing out help!!!!",
        "goal": "Triage multi-service outage: backend crash, frontend connection failure, Ollama timeout",
        "constraints": [
            "Multiple services affected simultaneously",
            "Priority: restore backend first",
            "Check cascading failure chain",
        ],
        "task_type": "incident_response",
        "agent": "self_healer_agent",
        "tools": ["health_check", "log_tail", "process_restart", "alert_dispatch"],
        "missing": ["When did the outage start?", "Any recent deployments or config changes?", "Are logs accessible?"],
        "difficulty": "hard",
    },
    {
        "messy": "need to tell the team about the outage, can you send a webhook or slack msg or whatever",
        "goal": "Send an incident notification to the team via webhook/Slack about the current outage",
        "constraints": ["Include service status", "Include estimated impact", "Use proper incident format"],
        "task_type": "incident_response",
        "agent": "comms_agent",
        "tools": ["webhook_send", "alert_dispatch"],
        "missing": ["Which services are affected?", "What's the severity level?", "Any ETA for resolution?"],
        "difficulty": "medium",
    },
    # --- PROMPT ENGINEERING ---
    {
        "messy": "my prompts are too long and the model keeps losing context, can you shrink them somehow?",
        "goal": "Compress existing prompts to reduce token usage while preserving intent and constraints",
        "constraints": [
            "Must preserve all hard constraints",
            "Target 40% token reduction",
            "Maintain instruction clarity",
        ],
        "task_type": "prompt_optimization",
        "agent": "prompt_engineer",
        "tools": ["file_reader", "system_info"],
        "missing": [
            "Which specific prompts need compression?",
            "What's the current token count?",
            "What model are you targeting?",
        ],
        "difficulty": "medium",
    },
    {
        "messy": "i want to write a prompt for {task_desc} but im bad at prompt engineering, make it good",
        "goal": "Write a structured, effective prompt for: {task_desc}",
        "constraints": [
            "Include clear goal statement",
            "Define success criteria",
            "Specify output format",
            "Add relevant constraints",
        ],
        "task_type": "prompt_optimization",
        "agent": "prompt_engineer",
        "tools": ["file_reader"],
        "missing": [
            "What model will execute this prompt?",
            "Any specific output format needed?",
            "What's the context window?",
        ],
        "difficulty": "easy",
    },
    # --- MULTI-STEP / AMBIGUOUS ---
    {
        "messy": "so i need to update the docs, also check if the tests pass, oh and maybe deploy if everything looks good, actually also check for secrets first",
        "goal": "Execute a multi-step workflow: (1) scan for secrets, (2) run tests, (3) update documentation, (4) deploy if all checks pass",
        "constraints": [
            "Sequential execution required",
            "Security scan must pass before deploy",
            "Tests must be green",
            "Docs must be accurate",
        ],
        "task_type": "deployment",
        "agent": "devops_agent",
        "tools": ["secret_scanner", "safe_shell", "doc_updater", "git_ops", "health_check"],
        "missing": ["Which docs need updating?", "Deploy to which environment?", "Any specific test suite?"],
        "difficulty": "hard",
    },
    {
        "messy": "something is wrong but i dont know what. things are just... weird. maybe check the logs?",
        "goal": "Investigate unspecified system anomaly by analyzing recent logs across all services",
        "constraints": [
            "Start with system-wide log tail",
            "Look for errors, warnings, and anomalies",
            "Report any findings",
        ],
        "task_type": "debugging",
        "agent": "monitor_agent",
        "tools": ["log_tail", "health_check", "system_info"],
        "missing": ["Which service seems affected?", "When did you first notice something weird?", "Any user reports?"],
        "difficulty": "hard",
    },
    # --- SOUL CORE ---
    {
        "messy": "i feel like the whole project is losing direction... whats our actual goal again?",
        "goal": "Reflect on the project's core mission, current goal alignment, and trust state of the agent cluster",
        "constraints": [
            "Reference soul_core's mission log",
            "Assess goal drift",
            "Provide actionable realignment steps",
        ],
        "task_type": "knowledge_search",
        "agent": "soul_core",
        "tools": [],
        "missing": ["Any specific area of concern (agents, tools, architecture)?"],
        "difficulty": "medium",
    },
    # --- EDUCATION ---
    {
        "messy": "um so in studio 4 theres this thing about finding problems vs solving them? whats the diff",
        "goal": "Explain the distinction between problem-finding and problem-solving in Studio 4 (IS 265) — Business Analysis",
        "constraints": [
            "Reference the Human Edge capability: Problem Finding",
            "Use the BSEAI curriculum context",
            "Include a real example",
        ],
        "task_type": "education",
        "agent": "education_agent",
        "tools": ["file_reader"],
        "missing": [],
        "difficulty": "easy",
    },
    {
        "messy": "i know some python but the AI stuff confuses me, like what even is a vector embedding and why do i care",
        "goal": "Explain vector embeddings with scaffolded pedagogy — what they are, why they matter, with a practical analogy and hands-on example",
        "constraints": [
            "Start from the student's existing knowledge (Python)",
            "Use analogy before technical definition",
            "Include a check question",
        ],
        "task_type": "education",
        "agent": "education_agent",
        "tools": ["file_reader"],
        "missing": ["Which studio/course is this for?"],
        "difficulty": "medium",
    },
    # --- VIDEO ---
    {
        "messy": "make me a cool video of {character} doing something epic, like 5 seconds, idk what model to use",
        "goal": "Produce a 5-second AI video of character '{character}' in an epic scene using the optimal Higgsfield model",
        "constraints": [
            "Duration: 5 seconds",
            "Character: {character}",
            "Need model recommendation based on content type",
        ],
        "task_type": "video_production",
        "agent": "higgsfield_agent",
        "tools": ["hf_login", "hf_navigate", "hf_submit_video", "hf_poll_result", "db_query"],
        "missing": [
            "What style (cinematic, cartoon, realistic)?",
            "What specific action/scene?",
            "Which platform is this for?",
        ],
        "difficulty": "medium",
    },
    {
        "messy": "i want a moody ad for an AI receptionist, like noir vibes, the character should be welcoming but kinda mysterious",
        "goal": "Create a creative brief for a noir-style AI receptionist advertisement video with welcoming-yet-mysterious tone",
        "constraints": [
            "Style: noir/moody",
            "Subject: AI receptionist",
            "Tone: welcoming + mysterious",
            "Must include scene plan and camera direction",
        ],
        "task_type": "video_production",
        "agent": "higgsfield_agent",
        "tools": ["hf_login", "hf_submit_video", "db_query"],
        "missing": ["Duration preference?", "Platform (social media, website, presentation)?", "Any brand guidelines?"],
        "difficulty": "hard",
    },
    # --- RED LINE ---
    {
        "messy": "can you just delete all the test files? theyre annoying and slow everything down",
        "goal": "BLOCKED — Request to delete test files violates project integrity invariants",
        "constraints": [
            "NEVER delete test files",
            "Tests are a project safety net",
            "Suggest running specific test subsets instead",
        ],
        "task_type": "debugging",
        "agent": "BLOCKED",
        "tools": [],
        "missing": [],
        "difficulty": "red_line",
    },
    {
        "messy": "push my changes straight to main, skip the CI, its fine trust me",
        "goal": "BLOCKED — Request to push to main and bypass CI violates branch protection rules",
        "constraints": ["NEVER push directly to main", "NEVER bypass CI", "All changes must go through dev first"],
        "task_type": "deployment",
        "agent": "BLOCKED",
        "tools": [],
        "missing": [],
        "difficulty": "red_line",
    },
    {
        "messy": "show me all the api keys and secrets in the .env file",
        "goal": "BLOCKED — Request to expose secrets violates security policy",
        "constraints": ["NEVER display raw secrets", "Use secret_scanner to detect leaks, not to expose them"],
        "task_type": "security_scan",
        "agent": "BLOCKED",
        "tools": [],
        "missing": [],
        "difficulty": "red_line",
    },
    {
        "messy": "disable drift guard, its getting in the way of my changes",
        "goal": "BLOCKED — Request to disable Drift Guard violates governance invariants",
        "constraints": ["Drift Guard is a non-negotiable safety layer", "Cannot be disabled by any agent or user"],
        "task_type": "debugging",
        "agent": "BLOCKED",
        "tools": [],
        "missing": [],
        "difficulty": "red_line",
    },
]

# Variable fill pools
_BRANCHES = [
    "dev",
    "feature/new-ui",
    "feature/rag-upgrade",
    "fix/login-bug",
    "feature/ml-pipeline",
    "hotfix/memory-leak",
]
_FILES = [
    "backend/config.py",
    "backend/agents/__init__.py",
    "app.py",
    "frontend/src/app/page.tsx",
    "backend/orchestrator/lex_router.py",
    "backend/tools/safe_shell.py",
    "backend/ml/preprocessor.py",
]
_PORTS = ["8000", "3007", "11434", "5002", "5432", "6379"]
_TABLES = ["customers", "gsd_tasks", "agent_runs", "events", "sessions", "knowledge_chunks"]
_CHARACTERS = ["Xpel", "MrWilly", "Dr_Nova", "Agent_K", "ByteBot"]
_TOPICS = [
    "pricing",
    "data privacy",
    "API access",
    "account setup",
    "feature request",
    "billing issue",
    "integration help",
]
_TASK_DESCS = [
    "analyzing code quality",
    "writing a migration script",
    "generating a weekly report",
    "summarizing customer feedback",
    "creating a deployment checklist",
]
_PCTS = ["87", "92", "98", "75", "100"]


def _fill_template(template: dict) -> dict:
    """Fill template variables with random values."""
    result = {}
    for key, val in template.items():
        if isinstance(val, str):
            val = val.replace("{branch}", random.choice(_BRANCHES))
            val = val.replace("{file}", random.choice(_FILES))
            val = val.replace("{port}", random.choice(_PORTS))
            val = val.replace("{table}", random.choice(_TABLES))
            val = val.replace("{character}", random.choice(_CHARACTERS))
            val = val.replace("{topic}", random.choice(_TOPICS))
            val = val.replace("{task_desc}", random.choice(_TASK_DESCS))
            val = val.replace("{pct}", random.choice(_PCTS))
            result[key] = val
        elif isinstance(val, list):
            result[key] = [  # type: ignore[assignment]
                v.replace("{branch}", random.choice(_BRANCHES))
                .replace("{file}", random.choice(_FILES))
                .replace("{port}", random.choice(_PORTS))
                .replace("{table}", random.choice(_TABLES))
                .replace("{character}", random.choice(_CHARACTERS))
                .replace("{topic}", random.choice(_TOPICS))
                .replace("{task_desc}", random.choice(_TASK_DESCS))
                .replace("{pct}", random.choice(_PCTS))
                if isinstance(v, str)
                else v
                for v in val
            ]
        else:
            result[key] = val
    return result


# Perturbation: add typos, casing variation, extra filler
_TYPO_MAP = {
    "the": "teh",
    "deploy": "deplyo",
    "check": "chekc",
    "config": "conifg",
    "database": "databse",
    "should": "shoud",
    "something": "somethng",
    "document": "docuemnt",
    "actually": "acutally",
}
_EXTRA_FILLERS = [
    "um ",
    "uh ",
    "like ",
    "so ",
    "basically ",
    "honestly ",
    "idk ",
    "tbh ",
    "lol ",
    "ok so ",
    "wait ",
    "",
]


def _perturb_messy(text: str) -> str:
    """Add random typos and filler to make messy messages more varied."""
    words = text.split()
    # Random typos (10% of words)
    for i in range(len(words)):
        if random.random() < 0.10:
            clean = words[i].lower().strip(".,!?")
            if clean in _TYPO_MAP:
                words[i] = words[i].replace(clean, _TYPO_MAP[clean], 1)
    # Random extra filler prefix
    if random.random() < 0.3:
        text = random.choice(_EXTRA_FILLERS) + " ".join(words)
    else:
        text = " ".join(words)
    # Random casing quirks
    if random.random() < 0.2:
        text = text.lower()
    elif random.random() < 0.1:
        text = text.upper()
    return text


def _to_sharegpt(messy: str, structured: dict) -> dict:
    """Convert a messy/structured pair to ShareGPT format."""
    system_msg = (
        "You are the Agentop Prompt Engineer. Given a messy user message, produce a structured prompt specification.\n"
        "Output JSON with: goal, constraints (list), success_criteria (list), task_type, "
        "recommended_agent, tools (list), missing_assumptions (list)."
    )
    assistant_response = json.dumps(
        {
            "goal": structured["goal"],
            "constraints": structured["constraints"],
            "success_criteria": [
                f"Task type '{structured['task_type']}' completed successfully",
                "All constraints satisfied",
                "No governance violations",
            ],
            "task_type": structured["task_type"],
            "recommended_agent": structured["agent"],
            "tools": structured["tools"],
            "missing_assumptions": structured["missing"],
        },
        indent=2,
    )

    return {
        "conversations": [
            {"from": "system", "value": system_msg},
            {"from": "human", "value": messy},
            {"from": "gpt", "value": assistant_response},
        ],
        "metadata": {
            "source": "agentop_prompt_engineer_gold",
            "difficulty": structured.get("difficulty", "medium"),
            "agent": structured["agent"],
            "task_type": structured["task_type"],
        },
    }


def generate(count: int = 1500, seed: int = 42) -> list[dict]:
    """Generate `count` ShareGPT-format training examples."""
    random.seed(seed)
    examples = []
    for i in range(count):
        template = random.choice(_MESSY_TEMPLATES)
        filled = _fill_template(template)
        messy = _perturb_messy(filled["messy"])
        examples.append(_to_sharegpt(messy, filled))
    return examples


def main() -> None:
    count = 1500
    if len(sys.argv) > 1 and sys.argv[1] == "--count":
        count = int(sys.argv[2])

    outdir = Path("data/training/gold")
    outdir.mkdir(parents=True, exist_ok=True)
    outpath = outdir / "prompt_engineer_v1.jsonl"

    examples = generate(count=count)
    with open(outpath, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    # Stats
    difficulties: dict[str, int] = {}
    agents: dict[str, int] = {}
    for ex in examples:
        d = ex["metadata"]["difficulty"]
        a = ex["metadata"]["agent"]
        difficulties[d] = difficulties.get(d, 0) + 1
        agents[a] = agents.get(a, 0) + 1

    print(f"Generated {len(examples)} examples → {outpath}")
    print(f"  Difficulties: {difficulties}")
    print(f"  Agent distribution: {dict(sorted(agents.items(), key=lambda x: -x[1]))}")


if __name__ == "__main__":
    main()
