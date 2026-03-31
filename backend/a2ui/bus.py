"""A2UI event bus — delivers canvas events over the WebSocket control plane.

Responsibilities
----------------
- Assign monotone sequence numbers per session.
- Enforce per-session quota (max events, Sprint 5.5).
- Enforce per-target widget count (Sprint 5.5).
- Track current canvas state per session / target / widget_id.
- Deliver events to WS ``canvas`` channel via ``ws_hub``.
- Provide clear / state query helpers.
- Support per-agent component allowlists (Sprint 5.5).
"""

from __future__ import annotations

from typing import Any

from backend.a2ui.schema import A2UIMessage
from backend.config import (
    A2UI_ALLOWED_AGENTS,
    A2UI_MAX_EVENTS_PER_SESSION,
    A2UI_MAX_WIDGETS_PER_TARGET,
)
from backend.utils import logger
from backend.websocket.hub import ws_hub  # noqa: E402 — placed after logger to respect init order

# ---------------------------------------------------------------------------
# Quota / permissioning errors
# ---------------------------------------------------------------------------


class A2UIQuotaError(Exception):
    """Raised when a session or target exceeds its quota."""


class A2UIPermissionError(Exception):
    """Raised when an agent is not allowed to use A2UI."""


# ---------------------------------------------------------------------------
# A2UIBus
# ---------------------------------------------------------------------------


class A2UIBus:
    """Singleton bus for delivering A2UI events to the WebSocket hub."""

    def __init__(self) -> None:
        # seq counters per session_id
        self._seq: dict[str, int] = {}
        # event counts per session_id (for quota)
        self._event_counts: dict[str, int] = {}
        # canvas state: session_id -> target -> widget_id -> message dict
        self._canvas: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}

    # ------------------------------------------------------------------
    # Emit
    # ------------------------------------------------------------------

    async def emit(self, msg: A2UIMessage) -> dict[str, Any]:
        """Validate, sequence, persist, and broadcast an A2UI message.

        Raises:
            A2UIPermissionError: if the agent is not allowed.
            A2UIQuotaError: if a quota is exceeded.
        """
        # Permission check (Sprint 5.5)
        self._check_permission(msg.agent_id)

        # Quota check
        count = self._event_counts.get(msg.session_id, 0)
        if count >= A2UI_MAX_EVENTS_PER_SESSION:
            raise A2UIQuotaError(
                f"Session '{msg.session_id}' has reached the A2UI event quota ({A2UI_MAX_EVENTS_PER_SESSION} events)."
            )

        # Widget count check for render ops
        if msg.op == "render" and msg.widget_id:
            target_widgets = self._canvas.get(msg.session_id, {}).get(msg.target, {})
            if len(target_widgets) >= A2UI_MAX_WIDGETS_PER_TARGET:
                raise A2UIQuotaError(
                    f"Target '{msg.target}' has reached the widget limit ({A2UI_MAX_WIDGETS_PER_TARGET} widgets)."
                )

        # Assign sequence number
        seq = self._seq.get(msg.session_id, 0)
        msg.seq = seq
        self._seq[msg.session_id] = seq + 1

        # Persist canvas state
        self._apply_canvas_update(msg)

        # Increment event count
        self._event_counts[msg.session_id] = count + 1

        # Broadcast over WS hub
        sent = await ws_hub.broadcast(
            channel="canvas",
            event=f"canvas_{msg.op}",
            payload=msg.model_dump(),
        )

        logger.info(
            "a2ui_event_emitted",
            extra={
                "event_type": "a2ui_event_emitted",
                "session_id": msg.session_id,
                "agent_id": msg.agent_id,
                "op": msg.op,
                "target": msg.target,
                "widget_id": msg.widget_id,
                "seq": msg.seq,
                "ws_clients_reached": sent,
            },
        )

        return {"ok": True, "seq": msg.seq, "ws_clients_reached": sent}

    # ------------------------------------------------------------------
    # Canvas state helpers
    # ------------------------------------------------------------------

    def get_canvas_state(self, session_id: str) -> dict[str, Any]:
        """Return the full canvas state for *session_id*."""
        return dict(self._canvas.get(session_id, {}))

    async def clear_canvas(self, session_id: str) -> dict[str, Any]:
        """Remove all widget state for *session_id* and broadcast a clear event."""
        old_count = sum(len(widgets) for widgets in self._canvas.get(session_id, {}).values())
        self._canvas.pop(session_id, None)

        await ws_hub.broadcast(
            channel="canvas",
            event="canvas_cleared",
            payload={"session_id": session_id},
        )
        logger.info(
            "a2ui_canvas_cleared",
            extra={
                "event_type": "a2ui_canvas_cleared",
                "session_id": session_id,
                "widgets_removed": old_count,
            },
        )
        return {"ok": True, "session_id": session_id, "widgets_removed": old_count}

    def get_event_count(self, session_id: str) -> int:
        return self._event_counts.get(session_id, 0)

    def get_widget_count(self, session_id: str, target: str) -> int:
        return len(self._canvas.get(session_id, {}).get(target, {}))

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _apply_canvas_update(self, msg: A2UIMessage) -> None:
        session_state = self._canvas.setdefault(msg.session_id, {})

        if msg.op == "clear":
            if msg.target:
                session_state.pop(msg.target, None)
            else:
                self._canvas.pop(msg.session_id, None)
            return

        target_state = session_state.setdefault(msg.target, {})

        if msg.op in ("render", "replace", "append") and msg.widget_id:
            target_state[msg.widget_id] = msg.model_dump()

    def _check_permission(self, agent_id: str) -> None:
        if A2UI_ALLOWED_AGENTS and agent_id not in A2UI_ALLOWED_AGENTS:
            raise A2UIPermissionError(f"Agent '{agent_id}' is not in A2UI_ALLOWED_AGENTS.")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_bus: A2UIBus | None = None


def get_a2ui_bus() -> A2UIBus:
    """Return the module-level singleton A2UIBus (lazy init)."""
    global _bus
    if _bus is None:
        _bus = A2UIBus()
    return _bus
