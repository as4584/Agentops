"""
Security Event Watcher — monitors shared events for security alerts and
forwards them to a dedicated security_alerts.json file.

This is the push path for the security agent:
  cron → security_agent scans → alert_dispatch writes to shared_events
      → EventWatcher detects new security events
      → Writes to data/agents/security_agent/security_alerts.json
      → OpenClaw Discord bot polls this file and posts to #security channel

When the Discord bot is fully wired, replace _write_alert_file with
a direct Discord channel send via the bot's send_message() method.

Usage (server.py lifespan):
    from backend.security.event_watcher import SecurityEventWatcher
    watcher = SecurityEventWatcher(memory_store)
    asyncio.ensure_future(watcher.run())
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import PROJECT_ROOT

logger = logging.getLogger("agentop.security.watcher")

_ALERTS_PATH = PROJECT_ROOT / "data" / "agents" / "security_agent" / "security_alerts.json"
_POLL_INTERVAL_SECONDS = 30
_SECURITY_EVENT_TYPES = {
    "SECURITY_ALERT",
    "SECRET_DETECTED",
    "VULNERABILITY_FOUND",
    "SCAN_FINDING",
    "RED_LINE_VIOLATION",
    "INTRUSION_ATTEMPT",
    "NEWS_INTEL_DIGEST",  # high-relevance news items from NewsIntelWatcher
}

# Event types that produce security-keyword-rich content as normal output
# (e.g. an agent response that echoes scan results). These should only be
# forwarded as alerts if they carry an explicit security event type — the
# keyword fallback would produce false-positive noise for these types.
_KEYWORD_FALLBACK_EXCLUDED_TYPES = {
    "AGENT_RESPONSE",
    "TOOL_RESULT",
    "TASK_LOG",
}


class SecurityEventWatcher:
    """
    Background coroutine that watches the shared events bus for security events
    and routes them to the security alerts file (and eventually Discord).
    """

    def __init__(self, memory_store: Any) -> None:
        self._store = memory_store
        self._seen_event_ids: set[str] = set()
        self._alerts_path = _ALERTS_PATH
        self._alerts_path.parent.mkdir(parents=True, exist_ok=True)

    async def run(self) -> None:
        """Long-running poll loop. Run as a background asyncio task."""
        logger.info("[SecurityWatcher] Started — polling every %ds", _POLL_INTERVAL_SECONDS)
        while True:
            try:
                await self._check_events()
            except Exception as exc:
                logger.warning("[SecurityWatcher] Poll error (non-fatal): %s", exc)
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _check_events(self) -> None:
        """Read shared events, filter for security events, forward new ones."""
        try:
            events: list[dict] = self._store.get_shared_events(limit=200)
        except Exception:
            return

        for event in events:
            event_id = _event_id(event)
            if event_id in self._seen_event_ids:
                continue
            self._seen_event_ids.add(event_id)

            event_type = event.get("type", "")
            if event_type not in _SECURITY_EVENT_TYPES:
                # AGENT_RESPONSE and similar types naturally contain security
                # keywords in their content (e.g. scan result echoes). Skip the
                # keyword fallback for these — only explicit security event types
                # should trigger alerts from them.
                if event_type in _KEYWORD_FALLBACK_EXCLUDED_TYPES:
                    continue
                # For all other unknown types, catch events with security keywords
                content = json.dumps(event).lower()
                if not any(
                    kw in content for kw in ["secret", "vulnerability", "cve", "leak", "intrusion", "scan_finding"]
                ):
                    continue

            await self._forward_alert(event)

    async def _forward_alert(self, event: dict) -> None:
        """Write alert to file and log. Replace with Discord send when bot is ready."""
        alert = {
            "alert_id": str(uuid.uuid4())[:12],
            "received_at": datetime.now(tz=UTC).isoformat(),
            "type": event.get("type", "UNKNOWN"),
            "agent_id": event.get("agent_id", "unknown"),
            "severity": _infer_severity(event),
            "summary": _summarize_event(event),
            "delivered": False,
            "raw": event,
        }

        # Append to alerts file
        _append_alert(self._alerts_path, alert)

        severity = alert["severity"]
        logger.warning(
            "[SecurityWatcher] %s alert forwarded: %s",
            severity,
            alert["summary"][:120],
        )

        # TODO: when Discord bot is wired, replace with:
        # await discord_bot.send_to_channel("#security", format_alert(alert))


def _event_id(event: dict) -> str:
    """Stable ID for deduplication — hash of type + timestamp + agent."""
    return f"{event.get('type', '')}:{event.get('timestamp', '')}:{event.get('agent_id', '')}"


def _infer_severity(event: dict) -> str:
    content = json.dumps(event).lower()
    if any(kw in content for kw in ["critical", "intrusion", "red_line", "production"]):
        return "CRITICAL"
    if any(kw in content for kw in ["secret", "api_key", "token", "password", "vulnerability", "cve"]):
        return "HIGH"
    return "MEDIUM"


def _summarize_event(event: dict) -> str:
    parts = []
    if event.get("agent_id"):
        parts.append(f"agent={event['agent_id']}")
    if event.get("type"):
        parts.append(f"type={event['type']}")
    for key in ("message_preview", "detail", "description", "finding"):
        if event.get(key):
            parts.append(str(event[key])[:100])
            break
    return " | ".join(parts) if parts else json.dumps(event)[:150]


def _append_alert(path: Path, alert: dict) -> None:
    """Append alert to the JSON array in the alerts file."""
    existing: list[dict] = []
    if path.exists():
        try:
            existing = json.loads(path.read_text())
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
    existing.append(alert)
    # Keep last 500 alerts
    path.write_text(json.dumps(existing[-500:], indent=2))
