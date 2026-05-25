"""
Lex Router — LLM-based intent classification for automatic agent routing.
=========================================================================
When agent_id is ``"auto"`` the orchestrator delegates to this module,
which uses the locally fine-tuned *lex* model (via Ollama) to classify
the user message and select the best agent.

Falls back to keyword-based heuristics when:
  - Ollama is unreachable
  - The lex model is not pulled
  - LLM_ROUTER_MODE is set to "keyword"

Environment:
  LLM_ROUTER_MODE  — "lex" | "keyword" | "hybrid" (default: "hybrid")
    lex     → always use the LLM router
    keyword → always use the keyword fallback
    hybrid  → try LLM first, fall back to keyword on failure
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from backend.config import OLLAMA_BASE_URL
from backend.utils import logger

LLM_ROUTER_MODE: str = os.getenv("LLM_ROUTER_MODE", "hybrid")

# ── Decision collector (lazy import to avoid circular deps) ──────────
_decision_collector = None


def _get_collector():  # noqa: ANN202
    global _decision_collector
    if _decision_collector is None:
        from backend.ml.decision_collector import decision_collector

        _decision_collector = decision_collector
    return _decision_collector


LEX_ROUTER_MODEL: str = os.getenv("LEX_ROUTER_MODEL", "lex")


# Sprint 3: prefer the role-based router model from the registry when set.
# Falls back to LEX_ROUTER_MODEL (the fine-tuned lex model) if the env is unset.
def _effective_router_model() -> str:
    """Return the active router model, preferring DEFAULT_TASK_MODELS['router'] when available."""
    try:
        from backend.llm.unified_registry import DEFAULT_TASK_MODELS

        return DEFAULT_TASK_MODELS.get("router", LEX_ROUTER_MODEL)
    except Exception:
        return LEX_ROUTER_MODEL


# ── C-accelerated pre-filter (optional, degrades to Python keywords) ─────
try:
    from backend.orchestrator.fast_route_binding import FastRouter

    _fast_router = FastRouter()
except Exception:
    _fast_router = None  # type: ignore[assignment]

# ── Valid agent IDs ──────────────────────────────────────────────────────
# Canonical 11 — hardcoded here to decouple routing from agent module loading.
# Any change to this set requires a matching change in ALL_AGENT_DEFINITIONS.
VALID_AGENTS: set[str] = {
    "soul_core",
    "it_agent",
    "cs_agent",
    "devops_agent",
    "monitor_agent",
    "self_healer_agent",
    "code_review_agent",
    "security_agent",
    "data_agent",
    "comms_agent",
    "knowledge_agent",
}

# soul_core only receives escalations — never a direct LLM routing target
GENERAL_AUTO_ROUTE_AGENTS: set[str] = VALID_AGENTS - {"soul_core"}

# Retired agents — used in migration assertions and roster enforcement tests
RETIRED_AGENTS: set[str] = {
    "token_optimizer",
    "vocabulary_coach",
    "career_intel",
    "accreditation_advisor",
    "pedagogy_agent",
    "higgsfield_agent",
    "higgsfield_research_agent",
    "ocr_agent",
    "prompt_engineer",
    "curriculum_advisor",
}

# Defensive import-time guard
_retired_overlap = VALID_AGENTS & RETIRED_AGENTS
if _retired_overlap:
    raise RuntimeError(f"FATAL: Retired agent IDs in VALID_AGENTS: {_retired_overlap}")

# ── High-risk agents requiring >= 0.8 LLM confidence ────────────────────────
_HIGH_RISK_AGENTS: frozenset[str] = frozenset(
    {
        "security_agent",
        "self_healer_agent",
        "code_review_agent",
    }
)

_SPECIALIST_EXPLICIT_MAP: list[tuple[list[str], str]] = [
    (
        [
            "prompt engineer",
            "rewrite this prompt",
            "optimize this prompt",
            "optimise this prompt",
            "fix this prompt",
            # Natural-language phrases a user would say without knowing the agent name
            "make this prompt better",
            "improve my prompt",
            "help me write a prompt",
            "write a better prompt",
            "craft a prompt",
            "better prompt for",
            "prompt for llm",
            "prompt for ai",
        ],
        "prompt_engineer",
    ),
    (
        [
            "token optimizer",
            "token optimiser",
            "compress this prompt",
            "reduce token count",
            "context window budget",
            # Natural-language phrases
            "too many tokens",
            "reduce tokens",
            "shorten the prompt",
            "compress context",
            "trim my prompt",
            "prompt too long",
            "running out of context",
            "context limit",
        ],
        "token_optimizer",
    ),
    (
        ["curriculum advisor", "course sequence", "studio 1", "studio 2", "prerequisite", "bseai curriculum"],
        "curriculum_advisor",
    ),
    (
        ["vocabulary coach", "spell book", "define this term", "terminology precision", "precise vocabulary"],
        "vocabulary_coach",
    ),
    (
        ["career intel", "job description analysis", "skills gap", "resume positioning", "interview positioning"],
        "career_intel",
    ),
    (["accreditation advisor", "abet", "msche", "accreditation matrix", "student outcomes"], "accreditation_advisor"),
    (
        ["pedagogy agent", "learning objectives", "bloom's taxonomy", "lesson plan", "assessment design"],
        "pedagogy_agent",
    ),
    (
        [
            "higgsfield research",
            "video failure pattern",
            "prompt recommendation for higgsfield",
            "research higgsfield failures",
        ],
        "higgsfield_research_agent",
    ),
    (["higgsfield", "soul id", "video generation", "character lock"], "higgsfield_agent"),
]

# ── Keyword Fallback ─────────────────────────────────────────────────────
_KEYWORD_MAP: list[tuple[list[str], str]] = [
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

# ── Specialist keyword map (precision overrides) ─────────────────────────────
# Multi-word phrases precise enough to override C-router single-keyword matches.
# Priority order: first match in SPECIALIST_PRIORITY_ORDER wins.
SPECIALIST_KEYWORD_MAP: dict[str, list[str]] = {
    "knowledge_agent": [
        "source of truth",
        "source_of_truth",
        "what does the corpus",
        "corpus say",
        "docs say",
        "documentation say",
        "knowledge base",
        "search the docs",
    ],
    "cs_agent": [
        "i need help with",
        "help with my account",
        "billing issue",
        "my account",
        "account problem",
        "subscription",
        "invoice",
        "refund",
        "customer support",
        "user account",
        "access issue",
        "login problem",
        "password reset",
    ],
    "comms_agent": [
        "notification",
        "incident notification",
        "send notification",
        "incident alert",
        "notify the team",
        "send an incident",
        "alert the team",
        "stakeholder",
        "send to slack",
        "post to slack",
        "incident report",
    ],
    "code_review_agent": [
        "review the diff",
        "review this diff",
        "review the code",
        "code review",
        "review before merge",
        "review the pr",
        "check the diff",
        "review these changes",
        "review this pr",
    ],
    "self_healer_agent": [
        "lint errors",
        "ruff lint",
        "fix lint errors",
        "fix the lint",
        "ruff fix",
        "ruff check",
        "ruff format",
        "fix type errors",
        "mypy errors",
        "fix imports",
        "fix the imports",
        "clean pycache",
        "clear pycache",
        "pod crashlooping",
        "pod crash",
        "rollout restart",
        "auto-remediate",
        "auto remediate",
        "self heal",
        "restart and fix",
        "fix and restart",
    ],
    "it_agent": [
        "kubernetes",
        "kubectl",
        "k8s",
        "pod running",
        "pod status",
        "port 11434",
        "port 8000",
        "port 3007",
        "vlan",
        "dns lookup",
        "nameserver",
        "traceroute",
        "vm",
        "hypervisor",
    ],
    "security_agent": [
        "scan for secrets",
        "scan for credentials",
        "hardcoded credentials",
        "secret scan",
        "cve",
        "vulnerability scan",
        "audit security",
        "security audit",
        "owasp",
    ],
    "data_agent": [
        "database schema",
        "schema drift",
        "check schema",
        "migrate the database",
        "sqlite query",
        "data validation",
        "table structure",
    ],
    "monitor_agent": [
        "tail logs",
        "tail the logs",
        "watch logs",
        "set up alerting",
        "alert me if",
        "alert when",
        "grafana",
        "prometheus",
        "latency spike",
        "response time",
        "error rate",
    ],
    "devops_agent": [
        "deploy to",
        "deploy the",
        "run the pipeline",
        "ci pipeline",
        "cd pipeline",
        "build and deploy",
        "pipeline failed",
        "pipeline passing",
        "helm chart",
        "docker build",
        "docker push",
        "staging deploy",
        "production deploy",
        "rollback",
        "blue green",
    ],
    "soul_core": [
        "reflect on",
        "our mission",
        "our purpose",
        "trust score",
        "goal arbitration",
        "goal tracking",
    ],
}

# Order matters: first match wins.
SPECIALIST_PRIORITY_ORDER: list[str] = [
    "knowledge_agent",  # corpus queries — distinctive phrases
    "cs_agent",  # account + billing — distinctive
    "comms_agent",  # outbound send intent — must beat devops 'incident'
    "code_review_agent",  # review intent — must beat devops 'merge'
    "self_healer_agent",  # fix + remediate — must beat code_review 'lint'
    "it_agent",  # infra + port — must beat self_healer 'restart'
    "security_agent",  # scan + CVE — distinctive
    "data_agent",  # schema + database — distinctive
    "monitor_agent",  # observe + alert setup
    "devops_agent",  # deploy + pipeline — broad, placed last
    "soul_core",  # fallback only
]


def _specialist_keyword_route(message: str) -> tuple[str, float] | None:
    """Priority-ordered keyword match against SPECIALIST_KEYWORD_MAP.

    Returns (agent_id, confidence) or None if no match.
    First match in SPECIALIST_PRIORITY_ORDER wins, giving precise
    multi-word phrases priority over C-router single-keyword matches.
    """
    msg_lower = message.lower()
    for agent_id in SPECIALIST_PRIORITY_ORDER:
        for kw in SPECIALIST_KEYWORD_MAP.get(agent_id, []):
            if kw in msg_lower:
                logger.info(f"[LexRouter] specialist_keyword: '{kw}' -> {agent_id}")
                return agent_id, 0.88
    return None


def _specialist_route(message: str) -> str:
    """Route explicit specialist requests without perturbing the 12-agent baseline."""
    msg_lower = message.lower()
    for keywords, agent_id in _SPECIALIST_EXPLICIT_MAP:
        if any(keyword in msg_lower for keyword in keywords):
            return agent_id
    return ""


def _keyword_route(message: str) -> str:
    """Keyword-based routing fallback. Returns agent_id."""
    msg_lower = message.lower()
    scores: dict[str, int] = {}
    for keywords, agent_id in _KEYWORD_MAP:
        score = sum(1 for kw in keywords if kw in msg_lower)
        if score > 0:
            scores[agent_id] = scores.get(agent_id, 0) + score

    if scores:
        return max(scores, key=scores.get)  # type: ignore[arg-type]
    return "soul_core"  # Default: soul handles everything else


# ── Lex LLM Router ──────────────────────────────────────────────────────


def _router_system_prompt(allowed_agents: set[str]) -> str:
    return (
        "You are Lex, the OpenClaw router for Agentop. "
        "Given a user message, respond with ONLY a JSON object:\n"
        '{"agent_id": "<agent>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}\n\n'
        "Available agents: " + ", ".join(sorted(allowed_agents)) + "\n"
        "Choose the single best agent. Respond with valid JSON only."
    )


def _parse_lex_response(text: str) -> dict[str, Any] | None:
    """Extract JSON routing decision from Lex's response."""
    text = text.strip()
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Find JSON in text
    match = re.search(r"\{[^}]+\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


async def _lex_route(
    message: str,
    *,
    model: str | None = None,
    temperature: float | None = None,
    allowed_agents: set[str] | None = None,
) -> tuple[str, float]:
    """Query the lex model for routing. Returns (agent_id, confidence)."""
    _model = model or _effective_router_model()
    _temp = temperature if temperature is not None else 0.1
    _allowed = allowed_agents or VALID_AGENTS
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": _model,
                    "system": _router_system_prompt(_allowed),
                    "prompt": message,
                    "stream": False,
                    "options": {"temperature": _temp, "num_predict": 256},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get("response", "")

        decision = _parse_lex_response(response_text)
        if decision and decision.get("agent_id") in _allowed:
            confidence = float(decision.get("confidence", 0.5))
            return decision["agent_id"], confidence

        logger.warning(f"[LexRouter] Invalid response: {response_text[:200]}")
        return "", 0.0

    except Exception as exc:
        logger.warning(f"[LexRouter] Ollama call failed: {exc}")
        return "", 0.0


# ── Public API ───────────────────────────────────────────────────────────


async def resolve_agent(message: str) -> dict[str, Any]:
    """
    Resolve the best agent_id for a given message.

    Pipeline: C pre-filter → LLM (Ollama) → Python keyword fallback
    The C layer handles unambiguous keywords in ~0.01ms, skipping the
    800ms LLM call entirely for clear-cut requests.

    Every routing decision is recorded by the DecisionCollector for
    training data generation (routing pairs + DPO preference pairs).

    Returns:
        {"agent_id": str, "method": "c_fast"|"lex"|"keyword", "confidence": float}
    """
    import time as _time

    mode = LLM_ROUTER_MODE.lower()
    _t0 = _time.monotonic()

    # ── Stage 0: C red-line check (blocks dangerous requests) ────────
    if _fast_router and _fast_router.available:
        if _fast_router.check_red_line(message):
            logger.warning(f"[LexRouter] Red line blocked: {message[:80]}")
            result = {
                "agent_id": "soul_core",
                "method": "c_red_line",
                "confidence": 1.0,
                "blocked": True,
                "reason": "Red line violation",
                "reasoning": "Red line violation detected by C fast router",
            }
            _record_decision(message, result, _t0)
            return result

    # ── Stage 1: C keyword pre-filter (~0.01ms) ─────────────────────
    if _fast_router and _fast_router.available and mode != "keyword":
        c_result = _fast_router.route(message)
        if c_result["matched"] and c_result["confidence"] >= 0.85:
            agent_id = c_result["agent_id"]
            if agent_id in GENERAL_AUTO_ROUTE_AGENTS:
                # Allow precise specialist keywords to override C router
                sk = _specialist_keyword_route(message)
                if sk and sk[0] != agent_id:
                    sk_agent, sk_conf = sk
                    logger.info(
                        f"[LexRouter] Specialist override: C→{agent_id} overridden by specialist keyword → {sk_agent}"
                    )
                    result = {
                        "agent_id": sk_agent,
                        "method": "keyword",
                        "confidence": sk_conf,
                        "reasoning": (f"Specialist keyword overrode C router ({agent_id} → {sk_agent})"),
                    }
                    _record_decision(message, result, _t0)
                    return result
                logger.info(f"[LexRouter] C fast-routed to {agent_id} (confidence={c_result['confidence']:.2f})")
                result = {
                    "agent_id": agent_id,
                    "method": "c_fast",
                    "confidence": c_result["confidence"],
                    "reasoning": f"C fast router matched keyword for {agent_id}",
                }
                _record_decision(message, result, _t0)
                return result

    # ── Stage 1.5: explicit specialist routing ───────────────────────
    specialist_agent = _specialist_route(message)
    if specialist_agent:
        logger.info(f"[LexRouter] Specialist-routed to {specialist_agent}")
        result = {
            "agent_id": specialist_agent,
            "method": "specialist_keyword",
            "confidence": 0.9,
            "reasoning": f"Specialist keyword match for {specialist_agent}",
        }
        _record_decision(message, result, _t0)
        return result

    # ── Stage 2: LLM routing via Ollama (~800ms) ────────────────────
    if mode == "lex" or mode == "hybrid":
        import asyncio as _asyncio

        try:
            agent_id, confidence = await _asyncio.wait_for(
                _lex_route(message, allowed_agents=GENERAL_AUTO_ROUTE_AGENTS),
                timeout=1.2,
            )
        except (TimeoutError, Exception) as _exc:
            logger.warning(f"[LexRouter] _lex_route failed: {_exc} — falling back to soul_core")
            result = {
                "agent_id": "soul_core",
                "method": "fallback_soul_core",
                "confidence": 0.0,
                "reasoning": f"LLM router exception: {type(_exc).__name__}",
            }
            _record_decision(message, result, _t0)
            return result
        if agent_id:
            # ── Confidence threshold guards ──────────────────────────
            if confidence < 0.5:
                logger.info(f"[LexRouter] Confidence {confidence:.2f} < 0.5 — escalating to soul_core")
                result = {
                    "agent_id": "soul_core",
                    "method": "low_confidence_escalation",
                    "confidence": confidence,
                    "reasoning": (f"Confidence {confidence:.2f} below threshold 0.5 for {agent_id} — escalating"),
                }
                _record_decision(message, result, _t0)
                return result
            if agent_id in _HIGH_RISK_AGENTS and confidence < 0.8:
                logger.info(f"[LexRouter] High-risk agent {agent_id} at confidence {confidence:.2f} < 0.8 — escalating")
                result = {
                    "agent_id": "soul_core",
                    "method": "high_risk_escalation",
                    "confidence": confidence,
                    "reasoning": (f"High-risk agent {agent_id} requires >= 0.8 confidence, got {confidence:.2f}"),
                }
                _record_decision(message, result, _t0)
                return result
            logger.info(f"[LexRouter] Routed to {agent_id} (confidence={confidence:.2f})")
            result = {
                "agent_id": agent_id,
                "method": "lex",
                "confidence": confidence,
                "reasoning": f"LLM router selected {agent_id}",
            }
            _record_decision(message, result, _t0)
            return result
        if mode == "lex":
            # Strict mode: fall back to soul rather than keyword
            result = {
                "agent_id": "soul_core",
                "method": "lex_fallback",
                "confidence": 0.0,
                "reasoning": "LLM router failed in strict mode — escalating",
            }
            _record_decision(message, result, _t0)
            return result

    # ── Stage 3: Python keyword fallback ─────────────────────────────
    sk = _specialist_keyword_route(message)
    if sk:
        agent_id, confidence = sk
        reasoning = f"Specialist keyword matched {agent_id}"
    else:
        agent_id = _keyword_route(message)
        confidence = 0.8
        reasoning = f"Python keyword fallback matched {agent_id}"
    logger.info(f"[LexRouter] Keyword routed to {agent_id} (confidence={confidence:.2f})")
    result = {
        "agent_id": agent_id,
        "method": "keyword",
        "confidence": confidence,
        "reasoning": reasoning,
    }
    _record_decision(message, result, _t0)
    return result


async def lex_route_with_override(
    message: str,
    model: str | None = None,
    temperature: float | None = None,
) -> tuple[str, float]:
    """Public: route via LLM with optional model/temperature override."""
    return await _lex_route(message, model=model, temperature=temperature, allowed_agents=GENERAL_AUTO_ROUTE_AGENTS)


def keyword_route(message: str) -> str:
    """Public: route via keyword heuristics (instant, no LLM)."""
    return _keyword_route(message)


def _record_decision(message: str, result: dict[str, Any], start_time: float) -> None:
    """Record a routing decision to the decision collector (best-effort)."""
    import time as _time

    try:
        collector = _get_collector()
        collector.record_routing_decision(
            user_message=message,
            chosen_agent=result.get("agent_id", "unknown"),
            method=result.get("method", "unknown"),
            confidence=result.get("confidence", 0.0),
            latency_ms=(_time.monotonic() - start_time) * 1000,
            reasoning=result.get("reason", ""),
        )
    except Exception as exc:
        logger.info(f"[LexRouter] Decision recording failed (non-fatal): {exc}")
