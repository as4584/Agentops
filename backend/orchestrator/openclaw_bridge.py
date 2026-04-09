#!/usr/bin/env python3
"""
backend/orchestrator/openclaw_bridge.py — Bridge OpenClaw Gateway to Agentop agents.

This module:
1. Registers Agentop agents as OpenClaw tools (so OpenClaw can call them)
2. Exposes a /openclaw/route endpoint that accepts OpenClaw-format requests
3. Maps OpenClaw channels (Discord/Telegram) → Agentop agent routing
4. Enforces red lines from agents.md before any tool execution

Architecture:
    OpenClaw Gateway (port 18789)
        → POST /openclaw/route
        → Lex router (agent selection)
        → Agentop agent (execution)
        → Response back to OpenClaw channel
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC
from enum import Enum
from typing import Any

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT

logger = logging.getLogger("agentop.openclaw")

# ---------------------------------------------------------------------------
# Risk Assessment
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# Keywords that push a request into higher risk tiers
_HIGH_RISK_KEYWORDS: list[str] = [
    "deploy",
    "push to production",
    "push to main",
    "release",
    "rollback",
    "delete",
    "drop table",
    "drop database",
    "truncate",
    "wipe",
    "reboot",
    "shutdown",
    "kill process",
    "rm -rf",
    "format",
    "production database",
    "prod db",
    "master branch",
    "override",
    "disable firewall",
    "open port",
    "expose",
]

_MEDIUM_RISK_KEYWORDS: list[str] = [
    "modify",
    "update",
    "write",
    "create file",
    "add user",
    "change config",
    "restart service",
    "migrate",
    "seed",
    "insert",
    "commit",
    "merge",
    "install package",
    "pip install",
    "npm install",
]


def assess_risk(message: str) -> RiskLevel:
    """Score the risk level of an incoming OpenClaw task."""
    lower = message.lower()
    for kw in _HIGH_RISK_KEYWORDS:
        if kw in lower:
            return RiskLevel.HIGH
    for kw in _MEDIUM_RISK_KEYWORDS:
        if kw in lower:
            return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ---------------------------------------------------------------------------
# Cloud Escalation (OpenRouter → Claude Sonnet)
# ---------------------------------------------------------------------------

_OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
_CLOUD_MODEL: str = os.getenv("OPENCLAW_CLOUD_MODEL", "anthropic/claude-sonnet-4-6")
_DPO_DIR = PROJECT_ROOT / "data" / "dpo"


async def _escalate_to_cloud(message: str, reason: str) -> str:
    """
    Escalate a task to a cloud LLM when local risk is too high or local fails.
    Returns the cloud response text.
    Logs a DPO pair if escalation succeeds.
    """
    if not _OPENROUTER_API_KEY:
        logger.warning("[OpenClaw] Escalation requested but OPENROUTER_API_KEY not set.")
        return "Escalation unavailable: OPENROUTER_API_KEY not configured."

    system = (
        "You are Agentop's cloud escalation handler. "
        "The local agent could not safely handle this task. "
        "Provide a careful, safe response. If the action is destructive, require explicit confirmation steps."
    )
    payload = {
        "model": _CLOUD_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"[ESCALATED: {reason}]\n\n{message}"},
        ],
        "max_tokens": 1024,
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {_OPENROUTER_API_KEY}",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "Agentop-OpenClaw",
                },
                json=payload,
            )
            resp.raise_for_status()
            cloud_response = resp.json()["choices"][0]["message"]["content"]
            logger.info(f"[OpenClaw] Cloud escalation succeeded via {_CLOUD_MODEL}")
            _log_escalation_dpo(message, reason, cloud_response)
            return cloud_response
    except Exception as exc:
        logger.error(f"[OpenClaw] Cloud escalation failed: {exc}")
        return f"Cloud escalation failed: {exc}. Manual review required."


def _log_escalation_dpo(message: str, reason: str, cloud_response: str) -> None:
    """Write escalation as a DPO pair — local couldn't handle it, cloud did."""
    try:
        _DPO_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime

        ts = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
        path = _DPO_DIR / f"openclaw_escalation_{ts}.jsonl"
        pair = {
            "category": "openclaw_escalation",
            "task": message[:300],
            "escalation_reason": reason,
            "cloud_model": _CLOUD_MODEL,
            "cloud_response_preview": cloud_response[:300],
            "timestamp": ts,
        }
        with path.open("w") as f:
            f.write(json.dumps(pair) + "\n")
    except Exception as exc:
        logger.warning(f"[OpenClaw] DPO logging failed: {exc}")


router = APIRouter(prefix="/openclaw", tags=["openclaw"])

# ---------------------------------------------------------------------------
# Red Lines — loaded from .openclaw/agents.md at import time
# ---------------------------------------------------------------------------

RED_LINES: list[str] = [
    "rm -rf",
    "DROP TABLE",
    "DROP DATABASE",
    "TRUNCATE",
    "format c:",
    "mkfs",
    "dd if=/dev/zero",
    "chmod 777",
    "iptables -F",
    "ufw disable",
    "git push --force main",
    "git push origin main",
]

BLOCKED_DOMAINS: set[str] = {
    "pastebin.com",
    "hastebin.com",
    "transfer.sh",
    "file.io",
    "0x0.st",
}


def _check_red_lines(message: str) -> str | None:
    """Check if a message violates any red lines. Returns violation or None."""
    lower = message.lower()
    for line in RED_LINES:
        if line.lower() in lower:
            return f"RED LINE VIOLATION: '{line}' is prohibited"
    for domain in BLOCKED_DOMAINS:
        if domain in lower:
            return f"RED LINE VIOLATION: '{domain}' is a blocked exfiltration domain"
    return None


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class OpenClawRequest(BaseModel):
    """Incoming request from OpenClaw gateway."""

    message: str
    channel: str = "discord"  # discord | telegram | slack | cli
    user_id: str = ""
    conversation_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class OpenClawResponse(BaseModel):
    """Response back to OpenClaw gateway."""

    response: str
    agent_id: str = ""
    tools_used: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    latency_ms: float = 0.0
    blocked: bool = False
    block_reason: str = ""


# ---------------------------------------------------------------------------
# Firewall middleware
# ---------------------------------------------------------------------------


class OpenClawFirewall:
    """Firewall for OpenClaw requests — rate limiting + red line enforcement."""

    def __init__(self) -> None:
        self._request_log: dict[str, list[float]] = {}
        self.max_requests_per_minute = int(os.getenv("OPENCLAW_RATE_LIMIT", "30"))
        self.blocked_users: set[str] = set()

    def check(self, req: OpenClawRequest) -> str | None:
        """Returns block reason or None if allowed."""
        # Check banned users
        if req.user_id in self.blocked_users:
            return "User is blocked"

        # Rate limiting per user
        now = time.time()
        window = self._request_log.setdefault(req.user_id, [])
        # Prune old entries
        window[:] = [t for t in window if now - t < 60]
        if len(window) >= self.max_requests_per_minute:
            return f"Rate limited: {self.max_requests_per_minute} requests/min exceeded"
        window.append(now)

        # Red line check
        violation = _check_red_lines(req.message)
        if violation:
            logger.warning("FIREWALL BLOCK: user=%s reason=%s", req.user_id, violation)
            return violation

        # Message length check
        if len(req.message) > 4000:
            return "Message too long (max 4000 chars)"

        return None

    def block_user(self, user_id: str) -> None:
        self.blocked_users.add(user_id)

    def unblock_user(self, user_id: str) -> None:
        self.blocked_users.discard(user_id)


firewall = OpenClawFirewall()


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


@router.post("/route", response_model=OpenClawResponse)
async def openclaw_route(req: OpenClawRequest, request: Request) -> OpenClawResponse:
    """
    Main entry point for OpenClaw → Agentop routing.

    Risk pipeline:
      LOW  → local agent via orchestrator
      MEDIUM → local agent + log for review
      HIGH → escalate to cloud LLM (OpenRouter/Claude)
      FAIL → escalate to cloud as fallback + log DPO pair
    """
    start = time.monotonic()

    # ── Firewall check ───────────────────────────────────────────────────
    block = firewall.check(req)
    if block:
        return OpenClawResponse(
            response=f"Request blocked: {block}",
            blocked=True,
            block_reason=block,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ── Risk assessment ──────────────────────────────────────────────────
    risk = assess_risk(req.message)
    logger.info("[OpenClaw] Risk assessment: %s for user=%s", risk.value, req.user_id)

    if risk == RiskLevel.HIGH:
        logger.warning("[OpenClaw] HIGH risk task — escalating to cloud. user=%s", req.user_id)
        response_text = await _escalate_to_cloud(
            message=req.message,
            reason=f"HIGH risk task from channel={req.channel} user={req.user_id}",
        )
        return OpenClawResponse(
            response=f"[CLOUD ESCALATION — HIGH RISK]\n{response_text}",
            agent_id="cloud_escalation",
            confidence=1.0,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # ── Route to local agent ─────────────────────────────────────────────
    from backend.orchestrator.lex_router import resolve_agent

    try:
        routing: dict[str, Any] = await resolve_agent(req.message)
        agent_id = str(routing.get("agent_id", "soul_core"))
        confidence = float(routing.get("confidence", 0.0))
        tools: list[str] = list(routing.get("tools_needed", []))
    except Exception as e:
        logger.error("Routing failed: %s", e)
        agent_id = "soul_core"
        confidence = 0.0
        tools = []

    # ── Execute via orchestrator ─────────────────────────────────────────
    response_text = ""
    local_failed = False
    try:
        app = request.app
        orchestrator = getattr(app, "_orchestrator", None)
        if orchestrator:
            result = await orchestrator.process_message(
                agent_id=agent_id,
                message=req.message,
            )
            local_error = result.get("error")
            response_text = result.get("response", str(result))
            if local_error:
                local_failed = True
        else:
            response_text = f"[Routed to {agent_id}] Orchestrator not available — backend may be starting up."
    except Exception as e:
        logger.error("Agent execution failed: %s", e)
        response_text = str(e)
        local_failed = True

    # ── Fallback escalation on local failure ─────────────────────────────
    if local_failed:
        logger.warning("[OpenClaw] Local agent failed — escalating to cloud. agent=%s", agent_id)
        response_text = await _escalate_to_cloud(
            message=req.message,
            reason=f"Local agent '{agent_id}' failed: {response_text[:200]}",
        )
        response_text = f"[CLOUD FALLBACK]\n{response_text}"
        agent_id = "cloud_fallback"

    # ── MEDIUM risk: tag response for review ─────────────────────────────
    if risk == RiskLevel.MEDIUM:
        response_text = f"[MEDIUM RISK — flagged for review]\n{response_text}"

    latency = (time.monotonic() - start) * 1000
    return OpenClawResponse(
        response=response_text,
        agent_id=agent_id,
        tools_used=tools,
        confidence=confidence,
        latency_ms=latency,
    )


@router.get("/health")
async def openclaw_health() -> dict[str, Any]:
    """Health check for OpenClaw integration."""
    return {
        "status": "ok",
        "firewall": "active",
        "rate_limit": firewall.max_requests_per_minute,
        "blocked_users": len(firewall.blocked_users),
        "red_lines": len(RED_LINES),
    }


@router.get("/agents")
async def openclaw_agents() -> dict[str, Any]:
    """List available agents for OpenClaw routing."""
    from backend.agents import ALL_AGENT_DEFINITIONS

    return {
        "agents": [
            {
                "id": defn.agent_id,
                "name": defn.role,
                "description": defn.role,
            }
            for defn in ALL_AGENT_DEFINITIONS.values()
        ]
    }
