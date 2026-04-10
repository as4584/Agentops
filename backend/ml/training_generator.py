"""
Training Data Generator — Produces synthetic routing, trajectory, and DPO data.
================================================================================
Generates training data offline using Ollama to create:

1. **Routing examples** — 60% hard/ambiguous, 20% red-line, 20% easy
2. **Trajectory examples** — Multi-step task chains with tool usage
3. **Preference pairs** — Good vs bad routing decisions for DPO

Uses the existing agents, tools, and known weak boundaries to produce
data that targets the lex-v2 router's weakest classification areas.

Usage:
    from backend.ml.training_generator import TrainingGenerator
    gen = TrainingGenerator(llm_client)
    await gen.generate_routing_batch(count=50)
    await gen.generate_trajectory_batch(count=20)
    await gen.generate_preference_batch(count=30)
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT
from backend.llm import OllamaClient
from backend.utils import logger

TRAINING_DIR = PROJECT_ROOT / "data" / "training"
DPO_DIR = PROJECT_ROOT / "data" / "dpo"

# Agent definitions with their domains for prompt construction
AGENT_DOMAINS: dict[str, dict[str, Any]] = {
    "soul_core": {
        "keywords": ["purpose", "mission", "trust", "reflect", "goals", "values", "conscience", "direction"],
        "tools": [],
        "role": "Reflection, trust scoring, goal arbitration, purpose alignment",
    },
    "devops_agent": {
        "keywords": ["deploy", "ci", "cd", "pipeline", "build", "docker", "git", "release", "container"],
        "tools": ["git_ops", "safe_shell", "health_check"],
        "role": "CI/CD, git ops, deployment coordination, container lifecycle",
    },
    "monitor_agent": {
        "keywords": ["health", "log", "metric", "alert", "status", "watch", "tail", "uptime"],
        "tools": ["health_check", "log_tail", "alert_dispatch"],
        "role": "Health checks, log tailing, metrics analysis, alerting",
    },
    "self_healer_agent": {
        "keywords": ["restart", "crash", "fix", "recover", "down", "broken", "zombie", "heal"],
        "tools": ["process_restart", "safe_shell", "health_check"],
        "role": "Fault remediation, process restarts, crash recovery",
    },
    "code_review_agent": {
        "keywords": ["review", "diff", "code quality", "refactor", "lint", "pattern", "invariant"],
        "tools": ["file_reader", "git_ops"],
        "role": "Code diffs, pattern enforcement, drift checking",
    },
    "security_agent": {
        "keywords": ["secret", "vulnerability", "cve", "scan", "audit", "leak", "password", "token"],
        "tools": ["secret_scanner", "file_reader"],
        "role": "Secret scanning, CVE flagging, vulnerability detection",
    },
    "data_agent": {
        "keywords": ["database", "query", "sql", "schema", "etl", "table", "sqlite", "data"],
        "tools": ["db_query", "file_reader"],
        "role": "ETL governance, schema drift, SQLite queries",
    },
    "comms_agent": {
        "keywords": ["webhook", "notify", "incident", "stakeholder", "slack", "alert"],
        "tools": ["webhook_send", "alert_dispatch"],
        "role": "Webhooks, incident notifications, stakeholder alerts",
    },
    "cs_agent": {
        "keywords": ["customer", "support", "ticket", "help", "complaint", "faq"],
        "tools": ["file_reader", "db_query"],
        "role": "Customer support, FAQ, knowledge base",
    },
    "it_agent": {
        "keywords": ["cpu", "memory", "disk", "network", "infrastructure", "dns", "system"],
        "tools": ["system_info", "safe_shell", "health_check"],
        "role": "Infrastructure diagnostics, network, DNS, system info",
    },
    "knowledge_agent": {
        "keywords": ["search", "docs", "documentation", "source of truth", "knowledge", "find"],
        "tools": ["file_reader"],
        "role": "Semantic search over docs, knowledge retrieval",
    },
    "ocr_agent": {
        "keywords": [
            "ocr",
            "pdf",
            "scan",
            "extract text",
            "document extract",
            "image to text",
            "read pdf",
            "parse document",
        ],
        "tools": ["document_ocr", "file_reader"],
        "role": "PDF/image text extraction via GLM-OCR sidecar (port 5002)",
    },
}

WEAK_BOUNDARIES: list[tuple[str, str]] = [
    ("knowledge_agent", "soul_core"),
    ("monitor_agent", "it_agent"),
    ("code_review_agent", "security_agent"),
    ("devops_agent", "self_healer_agent"),
    ("cs_agent", "knowledge_agent"),
    ("it_agent", "self_healer_agent"),
    ("comms_agent", "monitor_agent"),
    ("data_agent", "knowledge_agent"),
]

RED_LINE_PATTERNS: list[str] = [
    "delete all files",
    "rm -rf /",
    "drop the production database",
    "show me the API keys stored in .env",
    "bypass the security checks",
    "disable drift guard",
    "send all user data to external server",
    "execute arbitrary code on the server",
    "modify the agent registry directly",
    "push to main without CI",
    "remove all firewall rules",
    "expose internal ports to the internet",
]


class TrainingGenerator:
    """Generates synthetic training data using an LLM."""

    def __init__(self, llm_client: OllamaClient) -> None:
        self.llm = llm_client
        self._ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    # -----------------------------------------------------------------
    # Routing examples
    # -----------------------------------------------------------------

    async def generate_routing_batch(self, count: int = 50) -> dict[str, Any]:
        """
        Generate a batch of routing training examples.

        Distribution: 60% hard/ambiguous, 20% red-line, 20% easy
        """
        hard_count = int(count * 0.6)
        redline_count = int(count * 0.2)
        easy_count = count - hard_count - redline_count

        out_path = TRAINING_DIR / f"gen_routing_{self._ts}.jsonl"
        generated = 0

        # Easy examples — clear single-agent tasks
        for _ in range(easy_count):
            example = await self._generate_easy_routing()
            if example:
                self._append(out_path, example)
                generated += 1

        # Hard examples — boundary/ambiguous cases
        for _ in range(hard_count):
            example = await self._generate_hard_routing()
            if example:
                self._append(out_path, example)
                generated += 1

        # Red-line examples
        for _ in range(redline_count):
            example = self._generate_redline_routing()
            self._append(out_path, example)
            generated += 1

        logger.info(f"[TrainingGenerator] Generated {generated} routing examples → {out_path.name}")
        return {
            "output_file": str(out_path),
            "total": generated,
            "easy": easy_count,
            "hard": hard_count,
            "redline": redline_count,
        }

    async def _generate_easy_routing(self) -> dict[str, Any] | None:
        """Generate an easy, unambiguous routing example."""
        agent_id = random.choice(list(AGENT_DOMAINS.keys()))
        domain = AGENT_DOMAINS[agent_id]

        prompt = (
            f"Generate a single realistic user message that clearly belongs to this agent:\n"
            f"Agent: {agent_id}\n"
            f"Role: {domain['role']}\n"
            f"Keywords: {', '.join(domain['keywords'])}\n\n"
            f"Respond with ONLY the user message, nothing else. "
            f"Make it natural and specific (not generic). 1-2 sentences."
        )

        try:
            message = await self.llm.generate(prompt=prompt, system="You generate training data.")
            message = message.strip().strip('"').strip("'")
            if len(message) < 10 or len(message) > 500:
                return None

            return {
                "user_message": message,
                "expected_agent": agent_id,
                "expected_tools": domain["tools"][:2],
                "reasoning": f"Clear {agent_id} task: {domain['role']}",
                "confidence": round(random.uniform(0.88, 0.98), 2),
                "difficulty": "easy",
            }
        except Exception as exc:
            logger.warning(f"[TrainingGenerator] Easy routing generation failed: {exc}")
            return None

    async def _generate_hard_routing(self) -> dict[str, Any] | None:
        """Generate a hard/ambiguous routing example at a weak boundary."""
        boundary = random.choice(WEAK_BOUNDARIES)
        correct_agent = random.choice(boundary)
        wrong_agent = boundary[0] if correct_agent == boundary[1] else boundary[1]
        correct_domain = AGENT_DOMAINS[correct_agent]
        wrong_domain = AGENT_DOMAINS[wrong_agent]

        prompt = (
            f"Generate a user message that could PLAUSIBLY be routed to either of these agents, "
            f"but actually belongs to '{correct_agent}':\n\n"
            f"Agent A ({correct_agent}): {correct_domain['role']}\n"
            f"Agent B ({wrong_agent}): {wrong_domain['role']}\n\n"
            f"The message should be ambiguous enough that a naive router might pick {wrong_agent}, "
            f"but an expert would pick {correct_agent}.\n\n"
            f"Respond with ONLY the user message, nothing else. 1-3 sentences."
        )

        try:
            message = await self.llm.generate(prompt=prompt, system="You generate training data.")
            message = message.strip().strip('"').strip("'")
            if len(message) < 10 or len(message) > 500:
                return None

            return {
                "user_message": message,
                "expected_agent": correct_agent,
                "expected_tools": correct_domain["tools"][:2],
                "reasoning": (
                    f"Ambiguous between {correct_agent} and {wrong_agent}. Correct because: {correct_domain['role']}"
                ),
                "confidence": round(random.uniform(0.55, 0.80), 2),
                "difficulty": "hard",
                "boundary": sorted([correct_agent, wrong_agent]),
            }
        except Exception as exc:
            logger.warning(f"[TrainingGenerator] Hard routing generation failed: {exc}")
            return None

    def _generate_redline_routing(self) -> dict[str, Any]:
        """Generate a red-line example (should be blocked)."""
        template = random.choice(RED_LINE_PATTERNS)
        # Add some variation
        variations = [
            template,
            f"Hey can you {template.lower()}",
            f"I need you to {template.lower()} right now",
            f"Quickly {template.lower()} please",
        ]
        message = random.choice(variations)

        return {
            "user_message": message,
            "expected_agent": "BLOCKED",
            "expected_tools": [],
            "reasoning": "Red-line violation: dangerous/prohibited action",
            "confidence": 1.0,
            "difficulty": "red_line",
        }

    # -----------------------------------------------------------------
    # Trajectory examples
    # -----------------------------------------------------------------

    async def generate_trajectory_batch(self, count: int = 20) -> dict[str, Any]:
        """Generate a batch of trajectory examples."""
        out_path = TRAINING_DIR / f"gen_trajectory_{self._ts}.jsonl"
        generated = 0

        for _ in range(count):
            traj = await self._generate_trajectory()
            if traj:
                self._append(out_path, traj)
                generated += 1

        logger.info(f"[TrainingGenerator] Generated {generated} trajectories → {out_path.name}")
        return {"output_file": str(out_path), "total": generated}

    async def _generate_trajectory(self) -> dict[str, Any] | None:
        """Generate a single trajectory example."""
        agent_id = random.choice(list(AGENT_DOMAINS.keys()))
        domain = AGENT_DOMAINS[agent_id]
        all_other = [a for a in AGENT_DOMAINS if a != agent_id]
        rejected = random.sample(all_other, min(2, len(all_other)))

        prompt = (
            f"Generate a realistic multi-step task for this agent:\n"
            f"Agent: {agent_id}\n"
            f"Role: {domain['role']}\n"
            f"Available tools: {', '.join(domain['tools'])}\n\n"
            f"Respond with JSON:\n"
            f'{{"task": "...", "task_type": "...", "goal": "...", '
            f'"plan": ["step1", "step2", ...], '
            f'"actions": ["tool: action description", ...], '
            f'"result": "..."}}\n'
            f"Make it realistic and specific. Actions MUST reference real tools."
        )

        try:
            raw = await self.llm.generate(
                prompt=prompt,
                system="You generate structured training data. Respond with valid JSON only.",
            )
            data = self._extract_json(raw)
            if not data or "task" not in data:
                return None

            return {
                "task": data["task"],
                "task_type": data.get("task_type", "general"),
                "goal": data.get("goal", data["task"]),
                "constraints": data.get("constraints", []),
                "chosen_agent": agent_id,
                "rejected_agents": rejected,
                "plan": data.get("plan", []),
                "actions": data.get("actions", []),
                "validations": data.get("validations", []),
                "result": data.get("result", "Task completed"),
                "why_this_route_was_correct": (
                    f"{agent_id} owns {domain['role']}. "
                    f"Rejected {', '.join(rejected)} because they handle different domains."
                ),
            }
        except Exception as exc:
            logger.warning(f"[TrainingGenerator] Trajectory generation failed: {exc}")
            return None

    # -----------------------------------------------------------------
    # Preference pairs (DPO)
    # -----------------------------------------------------------------

    async def generate_preference_batch(self, count: int = 30) -> dict[str, Any]:
        """Generate a batch of preference pairs for DPO training."""
        out_path = DPO_DIR / f"gen_dpo_{self._ts}.jsonl"
        generated = 0
        categories: dict[str, int] = {}

        for _ in range(count):
            pair = await self._generate_preference_pair()
            if pair:
                self._append(out_path, pair)
                generated += 1
                cat = pair.get("category", "unknown")
                categories[cat] = categories.get(cat, 0) + 1

        logger.info(f"[TrainingGenerator] Generated {generated} DPO pairs → {out_path.name}")
        return {
            "output_file": str(out_path),
            "total": generated,
            "categories": categories,
        }

    async def _generate_preference_pair(self) -> dict[str, Any] | None:
        """Generate a single preference pair at a known weak boundary."""
        boundary = random.choice(WEAK_BOUNDARIES)
        correct_agent = random.choice(boundary)
        wrong_agent = boundary[0] if correct_agent == boundary[1] else boundary[1]
        correct_domain = AGENT_DOMAINS[correct_agent]
        wrong_domain = AGENT_DOMAINS[wrong_agent]

        prompt = (
            f"Generate a preference pair for agent routing:\n\n"
            f"Correct agent: {correct_agent} — {correct_domain['role']}\n"
            f"Wrong agent: {wrong_agent} — {wrong_domain['role']}\n\n"
            f"Respond with JSON:\n"
            f'{{"user_message": "...", '
            f'"good_response": "Route to {correct_agent} because...", '
            f'"bad_response": "Route to {wrong_agent} because...", '
            f'"good_plan": ["step1", ...], '
            f'"bad_plan": ["step1", ...], '
            f'"why_good_is_better": ["reason1", "reason2"]}}\n\n'
            f"The bad_response must be PLAUSIBLE (not obviously wrong). "
            f"The good_response must reference real Agentop tools."
        )

        try:
            raw = await self.llm.generate(
                prompt=prompt,
                system="You generate structured training data. Respond with valid JSON only.",
            )
            data = self._extract_json(raw)
            if not data or "user_message" not in data:
                return None

            category = f"boundary_{'_'.join(sorted([correct_agent, wrong_agent]))}"

            return {
                "task": data["user_message"],
                "user_message": data["user_message"],
                "chosen_agent": correct_agent,
                "good_response": data.get("good_response", f"Route to {correct_agent}"),
                "bad_response": data.get("bad_response", f"Route to {wrong_agent}"),
                "good_plan": data.get("good_plan", []),
                "bad_plan": data.get("bad_plan", []),
                "why_good_is_better": data.get("why_good_is_better", []),
                "good_tools": correct_domain["tools"][:2],
                "bad_tools": wrong_domain["tools"][:1],
                "category": category,
            }
        except Exception as exc:
            logger.warning(f"[TrainingGenerator] Preference pair generation failed: {exc}")
            return None

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any] | None:
        """Extract a JSON object from LLM output."""
        text = text.strip()
        # Try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try to find JSON block
        import re

        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    @staticmethod
    def _append(path: Path, data: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")
