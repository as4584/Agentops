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

import logging
import os
import time
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("agentop.openclaw")

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
    """Main entry point for OpenClaw → Agentop routing."""
    start = time.monotonic()

    # Firewall check
    block = firewall.check(req)
    if block:
        return OpenClawResponse(
            response=f"Request blocked: {block}",
            blocked=True,
            block_reason=block,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    # Import here to avoid circular imports
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

    # Execute via orchestrator
    try:
        app = request.app
        orchestrator = getattr(app, "_orchestrator", None)
        if orchestrator:
            result = await orchestrator.process_message(
                agent_id=agent_id,
                message=req.message,
            )
            response_text = result.get("response", str(result))
        else:
            response_text = f"[Routed to {agent_id}] Orchestrator not available — backend may be starting up."
    except Exception as e:
        logger.error("Agent execution failed: %s", e)
        response_text = f"Agent {agent_id} encountered an error: {e}"

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
