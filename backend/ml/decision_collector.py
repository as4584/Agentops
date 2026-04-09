"""
Decision Collector — Captures routing decisions and preference pairs for DPO.
=============================================================================
Hooks into the orchestrator routing pipeline to log:

1. **Routing Decisions** — every resolve_agent() call with full context
2. **Preference Pairs** — good vs bad choices for DPO fine-tuning
3. **Trajectories** — multi-step agent execution traces

Data is written to ``data/training/`` and ``data/dpo/`` as JSONL.
The orchestrator calls ``record_routing_decision()`` after every route,
and ``record_trajectory()`` after every completed task chain.

Target: Opus-level routing quality via DPO on the lex-v2 3B router.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT
from backend.utils import logger

TRAINING_DIR = PROJECT_ROOT / "data" / "training"
DPO_DIR = PROJECT_ROOT / "data" / "dpo"
TRAINING_DIR.mkdir(parents=True, exist_ok=True)
DPO_DIR.mkdir(parents=True, exist_ok=True)

# Valid agent IDs for validation
VALID_AGENTS: frozenset[str] = frozenset(
    {
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
        "ocr_agent",
        "prompt_engineer",
        "token_optimizer",
        "career_intel",
        "higgsfield_agent",
        "BLOCKED",
    }
)

VALID_TOOLS: frozenset[str] = frozenset(
    {
        "safe_shell",
        "file_reader",
        "document_ocr",
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
    }
)

# Known weak boundaries — routing decisions at these boundaries get
# higher weight during training and are more likely to generate pairs
WEAK_BOUNDARIES: list[tuple[str, str]] = [
    ("knowledge_agent", "soul_core"),
    ("monitor_agent", "it_agent"),
    ("code_review_agent", "security_agent"),
    ("devops_agent", "self_healer_agent"),
    ("cs_agent", "knowledge_agent"),
    ("it_agent", "self_healer_agent"),
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class RoutingDecision(BaseModel):
    """A single routing decision captured from the orchestrator."""

    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    user_message: str
    chosen_agent: str
    method: str  # c_fast, lex, keyword, lex_fallback
    confidence: float
    latency_ms: float
    rejected_agents: list[str] = Field(default_factory=list)
    reasoning: str = ""
    tools_likely: list[str] = Field(default_factory=list)
    was_correct: bool | None = None  # Set by feedback loop
    correction: str | None = None  # If was_correct=False, what should it have been
    difficulty: str = "medium"  # easy, medium, hard, red_line
    is_boundary: bool = False  # True if at a known weak boundary
    boundary_agents: list[str] = Field(default_factory=list)


class PreferencePair(BaseModel):
    """Good vs bad routing decision for DPO training."""

    task: str
    user_message: str
    chosen_agent: str
    good_response: str
    bad_response: str
    good_plan: list[str] = Field(default_factory=list)
    bad_plan: list[str] = Field(default_factory=list)
    why_good_is_better: list[str] = Field(default_factory=list)
    good_tools: list[str] = Field(default_factory=list)
    bad_tools: list[str] = Field(default_factory=list)
    category: str = ""
    confidence_delta: float = 0.0  # How much more confident the good choice was


class Trajectory(BaseModel):
    """A complete multi-step task execution trace."""

    task: str
    task_type: str
    goal: str
    constraints: list[str] = Field(default_factory=list)
    chosen_agent: str
    rejected_agents: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
    validations: list[str] = Field(default_factory=list)
    result: str = ""
    why_this_route_was_correct: str = ""
    tools_used: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    success: bool = True


class RoutingConversation(BaseModel):
    """Training example in the Lex conversation format."""

    conversations: list[dict[str, str]]


# ---------------------------------------------------------------------------
# Decision Collector
# ---------------------------------------------------------------------------


class DecisionCollector:
    """
    Collects and persists routing decisions, preference pairs, and trajectories.

    Called by the orchestrator at routing time. Data lands in JSONL files
    grouped by date for incremental training runs.
    """

    def __init__(self) -> None:
        self._pending_decisions: list[RoutingDecision] = []
        self._session_start = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    def _routing_path(self) -> Path:
        return TRAINING_DIR / f"live_routing_{self._session_start}.jsonl"

    def _dpo_path(self) -> Path:
        return DPO_DIR / f"live_dpo_{self._session_start}.jsonl"

    def _trajectory_path(self) -> Path:
        return TRAINING_DIR / f"live_trajectory_{self._session_start}.jsonl"

    def _lex_training_path(self) -> Path:
        return TRAINING_DIR / f"live_lex_pairs_{self._session_start}.jsonl"

    # -----------------------------------------------------------------
    # Record routing decisions (called by orchestrator on every route)
    # -----------------------------------------------------------------

    def record_routing_decision(
        self,
        user_message: str,
        chosen_agent: str,
        method: str,
        confidence: float,
        latency_ms: float,
        reasoning: str = "",
        tools_likely: list[str] | None = None,
        rejected_agents: list[str] | None = None,
    ) -> RoutingDecision:
        """
        Record a routing decision from the orchestrator pipeline.

        Automatically detects:
        - Boundary decisions (known weak boundaries)
        - Difficulty level based on confidence
        - Generates a Lex training pair for the decision
        """
        # Validate agent ID before recording
        if chosen_agent not in VALID_AGENTS:
            logger.warning(
                f"[DecisionCollector] Skipping invalid agent_id={chosen_agent!r} — "
                f"not in VALID_AGENTS. Add it to decision_collector.VALID_AGENTS if real."
            )
            return RoutingDecision(
                user_message=user_message,
                chosen_agent=chosen_agent,
                method=method,
                confidence=confidence,
                latency_ms=latency_ms,
                reasoning=reasoning,
                tools_likely=tools_likely or [],
                rejected_agents=rejected_agents or [],
                difficulty="invalid",
            )

        # Detect boundary
        is_boundary = False
        boundary_agents: list[str] = []
        for a, b in WEAK_BOUNDARIES:
            if chosen_agent in (a, b):
                other = b if chosen_agent == a else a
                is_boundary = True
                boundary_agents.append(other)

        # Assess difficulty
        if method == "c_red_line":
            difficulty = "red_line"
        elif confidence >= 0.9:
            difficulty = "easy"
        elif confidence >= 0.7:
            difficulty = "medium"
        else:
            difficulty = "hard"

        decision = RoutingDecision(
            user_message=user_message,
            chosen_agent=chosen_agent,
            method=method,
            confidence=confidence,
            latency_ms=latency_ms,
            reasoning=reasoning,
            tools_likely=tools_likely or [],
            rejected_agents=rejected_agents or [],
            difficulty=difficulty,
            is_boundary=is_boundary,
            boundary_agents=boundary_agents,
        )

        # Persist to JSONL
        self._append_jsonl(self._routing_path(), decision.model_dump())

        # Generate a lex training pair from this live decision
        self._generate_lex_pair(decision)

        # If it's a boundary decision, generate a preference pair
        if is_boundary and confidence < 0.85:
            self._generate_boundary_pair(decision)

        self._pending_decisions.append(decision)
        logger.info(
            f"[DecisionCollector] Recorded: {chosen_agent} "
            f"(method={method}, conf={confidence:.2f}, boundary={is_boundary})"
        )
        return decision

    # -----------------------------------------------------------------
    # Record feedback (human correction of a routing decision)
    # -----------------------------------------------------------------

    def record_feedback(
        self,
        user_message: str,
        original_agent: str,
        correct_agent: str,
        reasoning: str = "",
    ) -> PreferencePair:
        """
        Record human feedback that a routing decision was wrong.
        Generates a preference pair for DPO training.
        """
        if correct_agent not in VALID_AGENTS:
            raise ValueError(f"Invalid agent: {correct_agent}")

        pair = PreferencePair(
            task=user_message,
            user_message=user_message,
            chosen_agent=correct_agent,
            good_response=f"Route to {correct_agent}. {reasoning}",
            bad_response=f"Route to {original_agent}.",
            why_good_is_better=[
                reasoning or f"{correct_agent} is the correct handler",
                f"{original_agent} was the wrong choice",
            ],
            category=f"correction_{original_agent}_to_{correct_agent}",
        )

        self._append_jsonl(self._dpo_path(), pair.model_dump())
        logger.info(f"[DecisionCollector] Feedback recorded: {original_agent} → {correct_agent}")
        return pair

    # -----------------------------------------------------------------
    # Record trajectories (called after a complete task execution)
    # -----------------------------------------------------------------

    def record_trajectory(
        self,
        task: str,
        task_type: str,
        goal: str,
        chosen_agent: str,
        actions: list[str],
        result: str,
        success: bool,
        rejected_agents: list[str] | None = None,
        constraints: list[str] | None = None,
        plan: list[str] | None = None,
        validations: list[str] | None = None,
        tools_used: list[str] | None = None,
        duration_ms: float = 0.0,
        why_correct: str = "",
    ) -> Trajectory:
        """Record a complete task execution trajectory."""
        traj = Trajectory(
            task=task,
            task_type=task_type,
            goal=goal,
            chosen_agent=chosen_agent,
            rejected_agents=rejected_agents or [],
            plan=plan or [],
            actions=actions,
            validations=validations or [],
            result=result,
            why_this_route_was_correct=why_correct,
            tools_used=tools_used or [],
            duration_ms=duration_ms,
            success=success,
            constraints=constraints or [],
        )

        self._append_jsonl(self._trajectory_path(), traj.model_dump())
        logger.info(f"[DecisionCollector] Trajectory recorded: {task[:60]}")
        return traj

    # -----------------------------------------------------------------
    # Bulk export for training
    # -----------------------------------------------------------------

    def export_lex_training_data(self) -> dict[str, Any]:
        """
        Compile all routing decisions into Lex conversation format JSONL.

        Returns stats about the exported data.
        """
        routing_files = sorted(TRAINING_DIR.glob("live_routing_*.jsonl"))
        out_path = TRAINING_DIR / f"lex_compiled_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.jsonl"

        total = 0
        hard_count = 0
        boundary_count = 0

        with out_path.open("w", encoding="utf-8") as out:
            for fpath in routing_files:
                for line in fpath.open(encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        decision = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    conv = self._decision_to_lex_conversation(decision)
                    if conv:
                        out.write(json.dumps(conv, ensure_ascii=False) + "\n")
                        total += 1
                        if decision.get("difficulty") in ("hard", "red_line"):
                            hard_count += 1
                        if decision.get("is_boundary"):
                            boundary_count += 1

        return {
            "output_file": str(out_path),
            "total_examples": total,
            "hard_examples": hard_count,
            "boundary_examples": boundary_count,
            "easy_examples": total - hard_count - boundary_count,
        }

    def export_dpo_pairs(self) -> dict[str, Any]:
        """Compile all DPO preference pairs into a single file."""
        dpo_files = sorted(DPO_DIR.glob("live_dpo_*.jsonl"))
        out_path = DPO_DIR / f"compiled_dpo_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.jsonl"

        total = 0
        categories: dict[str, int] = {}

        with out_path.open("w", encoding="utf-8") as out:
            for fpath in dpo_files:
                for line in fpath.open(encoding="utf-8"):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        pair = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    out.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    total += 1
                    cat = pair.get("category", "unknown")
                    categories[cat] = categories.get(cat, 0) + 1

        return {
            "output_file": str(out_path),
            "total_pairs": total,
            "categories": categories,
        }

    def get_stats(self) -> dict[str, Any]:
        """Return statistics about collected data."""
        routing_count = 0
        dpo_count = 0
        trajectory_count = 0

        for fpath in TRAINING_DIR.glob("live_routing_*.jsonl"):
            routing_count += sum(1 for _ in fpath.open(encoding="utf-8") if _.strip())

        for fpath in DPO_DIR.glob("live_dpo_*.jsonl"):
            dpo_count += sum(1 for _ in fpath.open(encoding="utf-8") if _.strip())

        for fpath in TRAINING_DIR.glob("live_trajectory_*.jsonl"):
            trajectory_count += sum(1 for _ in fpath.open(encoding="utf-8") if _.strip())

        return {
            "routing_decisions": routing_count,
            "dpo_pairs": dpo_count,
            "trajectories": trajectory_count,
            "session_start": self._session_start,
            "pending_in_memory": len(self._pending_decisions),
        }

    # -----------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------

    def _generate_lex_pair(self, decision: RoutingDecision) -> None:
        """Generate a Lex-format training conversation from a routing decision."""
        conv = self._decision_to_lex_conversation(decision.model_dump())
        if conv:
            self._append_jsonl(self._lex_training_path(), conv)

    def _decision_to_lex_conversation(self, decision: dict[str, Any]) -> dict[str, Any] | None:
        """Convert a routing decision dict to Lex conversation format."""
        agent = decision.get("chosen_agent", "")
        if agent not in VALID_AGENTS or agent == "BLOCKED":
            return None

        response_obj = {
            "agent_id": agent,
            "confidence": decision.get("confidence", 0.5),
            "reasoning": decision.get("reasoning", ""),
            "tools_likely": decision.get("tools_likely", []),
        }

        return {
            "conversations": [
                {
                    "from": "system",
                    "value": (
                        "You are Lex, the OpenClaw Router for Agentop. "
                        "Classify the user message to the correct agent. "
                        "Respond with ONLY a JSON object: "
                        '{"agent_id": "<agent>", "confidence": <0-1>, '
                        '"reasoning": "<brief>", "tools_likely": [...]}'
                    ),
                },
                {"from": "human", "value": decision.get("user_message", "")},
                {"from": "gpt", "value": json.dumps(response_obj)},
            ]
        }

    def _generate_boundary_pair(self, decision: RoutingDecision) -> None:
        """
        Generate a DPO preference pair for a boundary decision.

        For weak-boundary routing with low confidence, the chosen agent is
        treated as 'good' and the boundary competitor is treated as 'bad'.
        This teaches the model to distinguish between similar agents.
        """
        if not decision.boundary_agents:
            return

        bad_agent = decision.boundary_agents[0]
        category = f"boundary_{'_'.join(sorted([decision.chosen_agent, bad_agent]))}"

        pair = PreferencePair(
            task=decision.user_message,
            user_message=decision.user_message,
            chosen_agent=decision.chosen_agent,
            good_response=(f"Route to {decision.chosen_agent}. {decision.reasoning}"),
            bad_response=f"Route to {bad_agent}.",
            why_good_is_better=[
                decision.reasoning or f"{decision.chosen_agent} is the correct handler",
                f"{bad_agent} is a common misroute for this type of message",
            ],
            good_tools=decision.tools_likely,
            bad_tools=[],
            category=category,
            confidence_delta=decision.confidence,
        )

        self._append_jsonl(self._dpo_path(), pair.model_dump())

    @staticmethod
    def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
        """Append a single JSON object as a line to a JSONL file."""
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, default=str) + "\n")


# Module-level singleton
decision_collector = DecisionCollector()
