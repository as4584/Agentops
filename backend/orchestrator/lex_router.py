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

# ── C-accelerated pre-filter (optional, degrades to Python keywords) ─────
try:
    from backend.orchestrator.fast_route_binding import FastRouter

    _fast_router = FastRouter()
except Exception:
    _fast_router = None  # type: ignore[assignment]

# ── Valid agent IDs ──────────────────────────────────────────────────────
VALID_AGENTS: set[str] = {
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
}

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
    (
        ["ocr", "pdf", "scan", "extract text", "document extract", "image to text", "read pdf", "parse document"],
        "ocr_agent",
    ),
    (["reflect", "goal", "trust", "purpose", "mission", "remember", "soul"], "soul_core"),
]


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

_ROUTER_SYSTEM_PROMPT = (
    "You are Lex, the OpenClaw router for Agentop. "
    "Given a user message, respond with ONLY a JSON object:\n"
    '{"agent_id": "<agent>", "confidence": <0.0-1.0>, "reasoning": "<brief>"}\n\n'
    "Available agents: " + ", ".join(sorted(VALID_AGENTS)) + "\n"
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


async def _lex_route(message: str) -> tuple[str, float]:
    """Query the lex model for routing. Returns (agent_id, confidence)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": LEX_ROUTER_MODEL,
                    "system": _ROUTER_SYSTEM_PROMPT,
                    "prompt": message,
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 256},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            response_text = data.get("response", "")

        decision = _parse_lex_response(response_text)
        if decision and decision.get("agent_id") in VALID_AGENTS:
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
            }
            _record_decision(message, result, _t0)
            return result

    # ── Stage 1: C keyword pre-filter (~0.01ms) ─────────────────────
    if _fast_router and _fast_router.available and mode != "keyword":
        c_result = _fast_router.route(message)
        if c_result["matched"] and c_result["confidence"] >= 0.85:
            agent_id = c_result["agent_id"]
            if agent_id in VALID_AGENTS:
                logger.info(f"[LexRouter] C fast-routed to {agent_id} (confidence={c_result['confidence']:.2f})")
                result = {"agent_id": agent_id, "method": "c_fast", "confidence": c_result["confidence"]}
                _record_decision(message, result, _t0)
                return result

    # ── Stage 2: LLM routing via Ollama (~800ms) ────────────────────
    if mode == "lex" or mode == "hybrid":
        agent_id, confidence = await _lex_route(message)
        if agent_id:
            logger.info(f"[LexRouter] Routed to {agent_id} (confidence={confidence:.2f})")
            result = {"agent_id": agent_id, "method": "lex", "confidence": confidence}
            _record_decision(message, result, _t0)
            return result
        if mode == "lex":
            # Strict mode: fall back to soul rather than keyword
            result = {"agent_id": "soul_core", "method": "lex_fallback", "confidence": 0.0}
            _record_decision(message, result, _t0)
            return result

    # ── Stage 3: Python keyword fallback ─────────────────────────────
    agent_id = _keyword_route(message)
    logger.info(f"[LexRouter] Keyword routed to {agent_id}")
    result = {"agent_id": agent_id, "method": "keyword", "confidence": 0.8}
    _record_decision(message, result, _t0)
    return result


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
