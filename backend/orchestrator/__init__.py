"""
LangGraph Orchestrator — Stateful multi-agent orchestration.
============================================================
This module implements the LangGraph-based state machine that:
1. Routes messages to the correct agent
2. Manages conversation state
3. Enforces agent isolation (INV-2: no direct inter-agent calls)
4. Tracks drift status across operations
5. Appends shared events (INV-9: append-only via orchestrator)

Architecture Notes:
- Agents communicate ONLY through this orchestrator
- The orchestrator mediates all agent interactions
- State is maintained per-conversation
- Drift checks happen at each state transition
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypedDict

from langgraph.graph import StateGraph, END

from backend.knowledge import KnowledgeVectorStore
from backend.llm import OllamaClient
from backend.memory import memory_store
from backend.middleware import drift_guard
from backend.models import (
    AgentDefinition,
    AgentState,
    AgentStatus,
    ChangeImpactLevel,
    DriftReport,
    DriftStatus,
)
from backend.agents import create_agent, ALL_AGENT_DEFINITIONS, SoulAgent
from backend.agents.gatekeeper_agent import GatekeeperAgent, GatekeeperResult
from backend.tasks import task_tracker, TaskStatus
from backend.utils import logger
from backend.utils.tool_ids import ToolIdRegistry


# ---------------------------------------------------------------------------
# Orchestrator State Schema
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict):
    """
    State schema for the LangGraph state machine.

    This is the single source of truth for a conversation's state.
    All fields are immutable within a single node execution.
    """
    # Routing
    target_agent: str               # Which agent should handle this
    message: str                    # Current message to process
    context: dict[str, Any]         # Additional context

    # Response
    response: str                   # The agent's response
    tool_calls: list[dict[str, Any]]  # Tool calls made during processing

    # Tool ID normalisation — per-conversation ToolIdRegistry instance.
    # Stored as Any to keep TypedDict JSON-annotation compatible; actual
    # value is always a ToolIdRegistry or None (created at conversation start).
    tool_id_registry: Any

    # Governance
    drift_status: str               # Current drift status (GREEN/YELLOW/RED)
    governance_notes: list[str]     # Governance observations

    # Metadata
    timestamp: str                  # Processing timestamp
    error: str | None               # Error message if any


INTAKE_QUESTIONS: list[tuple[str, str]] = [
    ("business_name", "What is your business name and primary offer?"),
    ("industry", "What industry and niche are you in?"),
    ("target_audience", "Who is your ideal customer? Include demographics and interests."),
    ("brand_voice", "What brand voice should we use (e.g., bold, friendly, luxury, playful)?"),
    ("goals", "What are your top marketing goals over the next 90 days?"),
    ("platforms", "Which platforms matter most (Instagram, TikTok, YouTube Shorts, X, LinkedIn)?"),
    ("offers", "Which products/services should be promoted first?"),
    ("cta", "What call-to-actions should content push (book call, buy now, DM, email signup)?"),
]


# ---------------------------------------------------------------------------
# Orchestrator Class
# ---------------------------------------------------------------------------

class AgentOrchestrator:
    """
    LangGraph-based multi-agent orchestrator.

    Responsibilities:
    - Route messages to correct agents
    - Maintain state machine for conversations
    - Enforce governance at routing boundaries
    - Provide system status for dashboard

    Non-responsibilities:
    - Does NOT execute tools directly (agents do)
    - Does NOT maintain conversation history (agents do)
    - Does NOT interact with LLM directly (agents do)
    """

    def __init__(self, llm_client: OllamaClient) -> None:
        self.llm_client = llm_client
        self._agents: dict[str, Any] = {}
        self._gatekeeper = GatekeeperAgent()
        self._knowledge_store = KnowledgeVectorStore(llm_client)
        self._knowledge_agent_id = "knowledge_agent"
        self._intake_namespace = "social_intake"
        # Build the knowledge-agent definition separately (uses vector store internally)
        self._agent_definition = AgentDefinition(
            agent_id=self._knowledge_agent_id,
            role="Knowledge assistant with semantic retrieval over local project/docs vector DB.",
            system_prompt=(
                "You are the Agentop Knowledge Agent. Use retrieved context as source-of-truth, "
                "answer precisely, and cite file paths in your answer when relevant. "
                "If context is insufficient, state uncertainty and ask for clarifying input."
            ),
            tool_permissions=["file_reader"],
            memory_namespace=self._knowledge_agent_id,
            allowed_actions=[
                "Retrieve semantic context from local vector DB",
                "Answer user questions grounded in indexed knowledge",
                "Store query/response summaries in namespaced memory",
            ],
            change_impact_level=ChangeImpactLevel.MEDIUM,
        )
        self._agent_state = AgentState(agent_id=self._knowledge_agent_id)
        self._graph = self._build_graph()
        self._compiled_graph = self._graph.compile()
        self._initialize_agents()
        logger.info("AgentOrchestrator initialized with full agent cluster")

    def gatekeeper_review(self, payload: dict[str, Any]) -> GatekeeperResult:
        """Run mutation payload through the Gatekeeper review layer."""
        return self._gatekeeper.review_mutation(payload)

    def _initialize_agents(self) -> None:
        """Instantiate all registered agents from ALL_AGENT_DEFINITIONS."""
        for agent_id in ALL_AGENT_DEFINITIONS:
            try:
                self._agents[agent_id] = create_agent(agent_id, self.llm_client)
                logger.info(f"Agent instantiated: {agent_id}")
            except Exception as exc:
                logger.error(f"Failed to instantiate agent '{agent_id}': {exc}")

    async def boot_soul(self) -> dict[str, Any]:
        """Run the Soul Agent boot sequence. Call this once after orchestrator init."""
        soul = self._agents.get("soul_core")
        if isinstance(soul, SoulAgent):
            result = await soul.boot()
            logger.info(f"Soul boot complete: {result}")
            return result
        return {"error": "soul_core agent not found"}

    async def soul_reflect(self, trigger: str = "manual") -> str:
        """Trigger a soul self-reflection and return the reflection text."""
        soul = self._agents.get("soul_core")
        if isinstance(soul, SoulAgent):
            return await soul.reflect(trigger=trigger)
        return "Soul Core agent not available."

    def soul_set_goal(self, title: str, description: str, priority: str = "MEDIUM") -> dict[str, Any]:
        """Add a goal to the Soul Agent."""
        soul = self._agents.get("soul_core")
        if isinstance(soul, SoulAgent):
            return soul.set_goal(title, description, priority)
        return {"error": "Soul Core agent not available."}

    def soul_get_goals(self) -> list[dict[str, Any]]:
        """Return the soul's active goals."""
        soul = self._agents.get("soul_core")
        if isinstance(soul, SoulAgent):
            return soul._active_goals
        return []

    # Complete registry of available agent IDs (knowledge + all BaseAgents)
    @property
    def _all_agent_ids(self) -> set[str]:
        return {self._knowledge_agent_id, "direct_llm"} | set(self._agents.keys())

    # -----------------------------------------------------------------
    # LangGraph State Machine Construction
    # -----------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph state machine.

        Graph structure:
            router → direct_llm_executor → governance_check → END

        The router validates state before direct LLM execution.
        The governance_check verifies drift status after execution.
        """
        graph = StateGraph(OrchestratorState)

        # Add nodes
        graph.add_node("router", self._router_node)
        graph.add_node("direct_llm_executor", self._agent_executor_node)
        graph.add_node("governance_check", self._governance_check_node)

        # Define edges
        graph.set_entry_point("router")
        graph.add_edge("router", "direct_llm_executor")
        graph.add_edge("direct_llm_executor", "governance_check")
        graph.add_edge("governance_check", END)

        return graph

    # -----------------------------------------------------------------
    # Graph Nodes
    # -----------------------------------------------------------------

    async def _router_node(self, state: OrchestratorState) -> dict[str, Any]:
        """
        Router node — validates system state and routes to knowledge agent mode.

        Validates:
        - System is not halted
        """
        target = state.get("target_agent", self._knowledge_agent_id)
        governance_notes: list[str] = list(state.get("governance_notes", []))

        if drift_guard.is_halted:
            return {
                "error": "SYSTEM HALTED: Critical drift event. Resolve before proceeding.",
                "drift_status": DriftStatus.RED.value,
                "governance_notes": governance_notes + [
                    "ROUTING BLOCKED: System halted due to drift violation"
                ],
            }

        if target not in self._all_agent_ids:
            available = sorted(self._all_agent_ids - {"direct_llm"})
            return {
                "error": (
                    f"Agent '{target}' not found. "
                    f"Available: {available}"
                ),
                "governance_notes": governance_notes + [f"Unknown agent requested: {target}"],
            }

        resolved_target = target if target in self._agents else self._knowledge_agent_id
        governance_notes.append(f"Routed to agent: {resolved_target}")
        return {
            "target_agent": resolved_target,
            "governance_notes": governance_notes,
            "timestamp": datetime.utcnow().isoformat(),
        }

    async def _agent_executor_node(self, state: OrchestratorState) -> dict[str, Any]:
        """
        Dispatch to the correct agent executor:
        - knowledge_agent → vector-store RAG path (existing behaviour)
        - all other agents → BaseAgent.process_message delegation
        """
        message = state.get("message", "")
        context = state.get("context", {})
        error = state.get("error")
        target = state.get("target_agent", self._knowledge_agent_id)

        if error:
            return {"response": f"Error: {error}"}

        # ── Non-knowledge agents: delegate to BaseAgent ──────────────────
        if target != self._knowledge_agent_id and target in self._agents:
            from backend.agents import BaseAgent as _BA
            agent = self._agents[target]
            if isinstance(agent, _BA):
                try:
                    response = await agent.process_message(message, context)
                    memory_store.append_shared_event({
                        "type": "AGENT_RESPONSE",
                        "agent_id": target,
                        "message_preview": message[:100],
                        "response_preview": response[:100],
                    })
                    return {"response": response, "error": None}
                except Exception as exc:
                    error_msg = f"{target} execution error: {exc}"
                    logger.error(error_msg)
                    return {"response": f"Error: {error_msg}", "error": error_msg}

        # ── Knowledge agent: vector-store RAG path ───────────────────────

        self._agent_state.status = AgentStatus.ACTIVE
        self._agent_state.last_active = datetime.utcnow()

        _tid = task_tracker.create_task(
            agent_id=self._knowledge_agent_id,
            action="knowledge_search",
            detail=message[:120],
            status=TaskStatus.RUNNING,
        )

        try:
            business_id = str(context.get("business_id", "")).strip()
            retrieved = await self._knowledge_store.search(message, top_k=4)
            profile_hits: list[dict[str, Any]] = []
            if business_id:
                profile_hits = await self._knowledge_store.search_business_profiles(
                    query=message,
                    business_id=business_id,
                    top_k=4,
                )

            context_blocks = []
            for i, item in enumerate(profile_hits, start=1):
                context_blocks.append(
                    f"[Business Context {i}] {item['business_id']}::{item['field']} (score={item['score']:.3f})\n{item['text']}"
                )

            for i, item in enumerate(retrieved, start=1):
                context_blocks.append(
                    f"[Source {i}] {item['path']} (score={item['score']:.3f})\n{item['text']}"
                )

            system_prompt = (
                "You are a local knowledge agent. Use the provided sources to answer. "
                "If the answer is not in sources, say so clearly. "
                "Include a brief 'Sources:' section listing relevant file paths."
            )
            prompt = (
                "Context:\n"
                + ("\n\n".join(context_blocks) if context_blocks else "No indexed context retrieved.")
                + "\n\nUser question:\n"
                + message
            )
            response = await self.llm_client.generate(prompt=prompt, system=system_prompt)

            memory_store.write(
                self._knowledge_agent_id,
                f"query_{self._agent_state.total_actions}",
                {
                    "question": message,
                    "response_preview": response[:400],
                    "sources": [item["path"] for item in retrieved],
                    "business_id": business_id or None,
                    "timestamp": datetime.utcnow().isoformat(),
                },
            )
            self._agent_state.total_actions += 1
            self._agent_state.memory_size_bytes = memory_store.get_namespace_size(self._knowledge_agent_id)
            self._agent_state.status = AgentStatus.IDLE

            task_tracker.complete_task(_tid, detail=f"OK — {len(retrieved)} chunks")

            # Record shared event (INV-9: append-only via orchestrator)
            memory_store.append_shared_event({
                "type": "LLM_RESPONSE",
                "agent_id": self._knowledge_agent_id,
                "message_preview": message[:100],
                "response_preview": response[:100],
                "retrieved_chunks": len(retrieved),
                "retrieved_business_chunks": len(profile_hits),
            })

            return {
                "response": response,
                "error": None,
            }

        except Exception as e:
            error_msg = f"Direct LLM execution error: {e}"
            logger.error(error_msg)
            task_tracker.fail_task(_tid, error=str(e))
            self._agent_state.status = AgentStatus.ERROR
            self._agent_state.error_count += 1
            return {
                "response": f"Error: {error_msg}",
                "error": error_msg,
            }

    async def _governance_check_node(self, state: OrchestratorState) -> dict[str, Any]:
        """
        Governance check node — verifies drift status after execution.

        Runs after every agent execution to detect:
        - Pending documentation updates (YELLOW)
        - Invariant violations (RED)
        """
        drift_report = drift_guard.check_invariants()
        governance_notes = list(state.get("governance_notes", []))

        governance_notes.append(f"Drift status: {drift_report.status.value}")

        if drift_report.pending_updates:
            governance_notes.append(
                f"Pending docs: {', '.join(drift_report.pending_updates)}"
            )

        if drift_report.violations:
            for v in drift_report.violations:
                governance_notes.append(
                    f"VIOLATION: {v.invariant_id} — {v.description}"
                )

        return {
            "drift_status": drift_report.status.value,
            "governance_notes": governance_notes,
        }

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    async def process_message(
        self,
        agent_id: str,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Process a message through the orchestrator's state machine.

        This is the main entry point for all agent interactions.
        Messages flow through: router → agent_executor → governance_check

        Args:
            agent_id: Target agent ID.
            message: The message to process.
            context: Optional additional context.

        Returns:
            Dict with response, drift_status, governance_notes.
        """
        initial_state: OrchestratorState = {
            "target_agent": agent_id,
            "message": message,
            "context": context or {},
            "response": "",
            "tool_calls": [],
            "tool_id_registry": ToolIdRegistry(),
            "drift_status": DriftStatus.GREEN.value,
            "governance_notes": [],
            "timestamp": datetime.utcnow().isoformat(),
            "error": None,
        }

        try:
            # Run the state machine
            final_state = await self._compiled_graph.ainvoke(initial_state)

            return {
                "agent_id": agent_id,
                "response": final_state.get("response", ""),
                "drift_status": final_state.get("drift_status", DriftStatus.GREEN.value),
                "governance_notes": final_state.get("governance_notes", []),
                "timestamp": final_state.get("timestamp", datetime.utcnow().isoformat()),
                "error": final_state.get("error"),
            }

        except Exception as e:
            logger.error(f"Orchestrator error: {e}")
            return {
                "agent_id": agent_id,
                "response": f"System error: {e}",
                "drift_status": drift_guard.drift_status.value,
                "governance_notes": [f"ORCHESTRATOR ERROR: {e}"],
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }

    def get_agent_states(self) -> list[AgentState]:
        """Return current state of all agents for dashboard (knowledge + all BaseAgents)."""
        # knowledge agent state
        self._agent_state.memory_size_bytes = memory_store.get_namespace_size(self._knowledge_agent_id)
        states = [self._agent_state]
        # all BaseAgent states
        for agent in self._agents.values():
            if hasattr(agent, "get_state"):
                states.append(agent.get_state())
        return states

    def get_drift_report(self) -> DriftReport:
        """Return current drift report."""
        return drift_guard.check_invariants()

    def get_available_agents(self) -> list[str]:
        """Return list of all available agent IDs."""
        return [self._knowledge_agent_id] + list(self._agents.keys())

    def get_agent_definition(self) -> AgentDefinition:
        """Return the knowledge agent definition (legacy compatibility)."""
        return self._agent_definition

    def get_all_agent_definitions(self) -> list[AgentDefinition]:
        """Return all agent definitions (knowledge + registered agents)."""
        defs = [self._agent_definition]
        for agent in self._agents.values():
            if hasattr(agent, "definition"):
                defs.append(agent.definition)
        return defs

    async def reindex_knowledge(self) -> dict[str, Any]:
        """Force rebuild the local vector DB and return index stats."""
        stats = await self._knowledge_store.rebuild_index()
        return {
            "agent_id": self._knowledge_agent_id,
            "chunks": stats["chunks"],
            "index_size_bytes": stats["file_size_bytes"],
            "index_size_mb": round(stats["file_size_bytes"] / (1024 * 1024), 4),
            "business_profile_vectors": stats["business_profile_vectors"],
            "business_profiles_size_bytes": stats["business_profiles_size_bytes"],
            "business_profiles_size_mb": round(stats["business_profiles_size_bytes"] / (1024 * 1024), 4),
        }

    def get_agent_memory_usage(self) -> list[dict[str, Any]]:
        """Return per-agent memory usage in bytes and megabytes for all agents."""
        results = []
        # knowledge agent
        size_bytes = memory_store.get_namespace_size(self._knowledge_agent_id)
        results.append({
            "agent_id": self._knowledge_agent_id,
            "namespace": self._knowledge_agent_id,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 4),
        })
        # all other agents
        for agent in self._agents.values():
            if hasattr(agent, "definition"):
                ns = agent.definition.memory_namespace
                ns_bytes = memory_store.get_namespace_size(ns)
                results.append({
                    "agent_id": agent.definition.agent_id,
                    "namespace": ns,
                    "size_bytes": ns_bytes,
                    "size_mb": round(ns_bytes / (1024 * 1024), 4),
                })
        return results

    def _get_intake_state(self, business_id: str) -> dict[str, Any]:
        """Read or initialize intake state for a business."""
        existing = memory_store.read(self._intake_namespace, business_id, None)
        if isinstance(existing, dict):
            return existing
        return {
            "business_id": business_id,
            "current_question_index": 0,
            "answers": {},
            "completed": False,
            "updated_at": datetime.utcnow().isoformat(),
        }

    async def start_intake(self, business_id: str) -> dict[str, Any]:
        """Start or resume intake for a business profile."""
        state = self._get_intake_state(business_id)
        memory_store.write(self._intake_namespace, business_id, state)

        idx = int(state.get("current_question_index", 0))
        completed = bool(state.get("completed", False))

        if completed or idx >= len(INTAKE_QUESTIONS):
            return {
                "business_id": business_id,
                "current_question_index": len(INTAKE_QUESTIONS),
                "total_questions": len(INTAKE_QUESTIONS),
                "question_key": "",
                "question": "Intake complete.",
                "completed": True,
            }

        question_key, question = INTAKE_QUESTIONS[idx]
        return {
            "business_id": business_id,
            "current_question_index": idx,
            "total_questions": len(INTAKE_QUESTIONS),
            "question_key": question_key,
            "question": question,
            "completed": False,
        }

    async def submit_intake_answer(self, business_id: str, answer: str) -> dict[str, Any]:
        """Persist answer, index it in vector DB, and return next question state."""
        state = self._get_intake_state(business_id)
        idx = int(state.get("current_question_index", 0))

        if idx >= len(INTAKE_QUESTIONS):
            state["completed"] = True
            memory_store.write(self._intake_namespace, business_id, state)
            return self.get_intake_status(business_id)

        question_key, _ = INTAKE_QUESTIONS[idx]
        clean_answer = answer.strip()
        state_answers = dict(state.get("answers", {}))
        state_answers[question_key] = clean_answer
        state["answers"] = state_answers
        await self._knowledge_store.upsert_business_answer(
            business_id=business_id,
            field=question_key,
            answer=clean_answer,
        )

        next_idx = idx + 1
        state["current_question_index"] = next_idx
        state["completed"] = next_idx >= len(INTAKE_QUESTIONS)
        state["updated_at"] = datetime.utcnow().isoformat()
        memory_store.write(self._intake_namespace, business_id, state)

        return self.get_intake_status(business_id)

    def get_intake_status(self, business_id: str) -> dict[str, Any]:
        """Return current intake progress for a business."""
        state = self._get_intake_state(business_id)
        idx = int(state.get("current_question_index", 0))
        completed = bool(state.get("completed", False))

        next_question_key: str | None = None
        next_question: str | None = None
        if not completed and idx < len(INTAKE_QUESTIONS):
            next_question_key, next_question = INTAKE_QUESTIONS[idx]

        return {
            "business_id": business_id,
            "current_question_index": idx,
            "total_questions": len(INTAKE_QUESTIONS),
            "completed": completed,
            "next_question_key": next_question_key,
            "next_question": next_question,
            "answers": dict(state.get("answers", {})),
        }

    async def generate_campaign(
        self,
        business_id: str,
        platform: str,
        objective: str,
        format_type: str = "reel",
        duration_seconds: int = 30,
    ) -> dict[str, Any]:
        """Generate a campaign package using completed intake + vector profile context."""
        intake_status = self.get_intake_status(business_id)
        if not intake_status.get("completed", False):
            raise ValueError(
                "Intake must be completed before campaign generation. "
                "Finish all intake questions first."
            )

        answers = dict(intake_status.get("answers", {}))
        semantic_query = (
            f"Generate a {format_type} campaign for {platform} with objective: {objective}. "
            f"Business profile context: {json.dumps(answers, ensure_ascii=False)}"
        )

        profile_hits = await self._knowledge_store.search_business_profiles(
            query=semantic_query,
            business_id=business_id,
            top_k=6,
        )

        answer_lines: list[str] = [f"- {k}: {v}" for k, v in answers.items()]
        profile_lines: list[str] = []
        for idx, hit in enumerate(profile_hits, start=1):
            profile_lines.append(
                f"[Profile Hit {idx}] field={hit.get('field')} score={hit.get('score', 0):.3f}\n"
                f"{hit.get('text', '')}"
            )

        system_prompt = (
            "You are a senior social media strategist. Return ONLY valid JSON with keys: "
            "script, caption, hashtags, image_prompts, shot_list, cta. "
            "hashtags/image_prompts/shot_list must be arrays of strings."
        )
        prompt = (
            f"Business ID: {business_id}\n"
            f"Platform: {platform}\n"
            f"Objective: {objective}\n"
            f"Format Type: {format_type}\n"
            f"Duration Seconds: {duration_seconds}\n\n"
            "Intake Answers:\n"
            + ("\n".join(answer_lines) if answer_lines else "- none")
            + "\n\nSemantic Profile Hits:\n"
            + ("\n\n".join(profile_lines) if profile_lines else "No semantic hits found.")
            + "\n\nGenerate the campaign JSON now."
        )

        raw = await self.llm_client.generate(
            prompt=prompt,
            system=system_prompt,
            temperature=0.4,
            max_tokens=1400,
        )

        def _to_list(value: Any) -> list[str]:
            if isinstance(value, list):
                return [str(v).strip() for v in value if str(v).strip()]
            if isinstance(value, str) and value.strip():
                return [value.strip()]
            return []

        def _extract_json(text: str) -> dict[str, Any]:
            candidate = text.strip()
            if candidate.startswith("```"):
                lines = candidate.splitlines()
                if len(lines) >= 3:
                    candidate = "\n".join(lines[1:-1]).strip()

            try:
                parsed = json.loads(candidate)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                pass

            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(candidate[start : end + 1])
                    return parsed if isinstance(parsed, dict) else {}
                except Exception:
                    return {}
            return {}

        parsed = _extract_json(raw)
        defaults = {
            "script": "Hook: Big promise. Body: quick proof + offer. CTA: take action now.",
            "caption": f"{objective} campaign for {platform} with clear value and CTA.",
            "hashtags": [f"#{platform.lower().replace(' ', '')}", "#marketing", "#growth"],
            "image_prompts": ["High-quality branded scene matching the campaign message."],
            "shot_list": ["Hook shot", "Value shot", "Offer shot", "CTA shot"],
            "cta": answers.get("cta", "DM us to get started today."),
        }

        campaign = {
            "script": str(parsed.get("script") or defaults["script"]),
            "caption": str(parsed.get("caption") or defaults["caption"]),
            "hashtags": _to_list(parsed.get("hashtags")) or defaults["hashtags"],
            "image_prompts": _to_list(parsed.get("image_prompts")) or defaults["image_prompts"],
            "shot_list": _to_list(parsed.get("shot_list")) or defaults["shot_list"],
            "cta": str(parsed.get("cta") or defaults["cta"]),
        }

        generated_at = datetime.utcnow().isoformat()
        memory_key = f"campaign_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        memory_store.write(
            self._knowledge_agent_id,
            memory_key,
            {
                "business_id": business_id,
                "platform": platform,
                "objective": objective,
                "format_type": format_type,
                "duration_seconds": duration_seconds,
                "generated_at": generated_at,
                "campaign": campaign,
                "profile_hits_count": len(profile_hits),
            },
        )

        return {
            "business_id": business_id,
            "platform": platform,
            "objective": objective,
            "format_type": format_type,
            "duration_seconds": duration_seconds,
            "generated_at": generated_at,
            "campaign": campaign,
        }
