"""WebSocket Connection Manager — hub for the Agentop control plane.

Responsibilities
----------------
- Accept / track WebSocket connections by client_id.
- Manage per-client channel subscriptions.
- Broadcast structured events to all subscribed clients.
- Heartbeat: server pings every 20 s; stale connections (last pong > 45 s)
  are evicted.
- Reconnect-safe: client_id from a prior session re-uses (replaces) the slot.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from backend.websocket.models import (
    VALID_CHANNELS,
    ErrorMessage,
    OutboundEvent,
    PingMessage,
    SubscribeMessage,
    WelcomeMessage,
)

PING_INTERVAL: float = 20.0  # seconds between heartbeat pings
PONG_TIMEOUT: float = 45.0  # seconds before stale connection is evicted


class _ClientState:
    __slots__ = ("ws", "channels", "last_pong", "session_id")

    def __init__(self, ws: WebSocket, session_id: str | None = None) -> None:
        self.ws = ws
        self.channels: set[str] = set()
        self.last_pong: float = time.monotonic()
        self.session_id: str | None = session_id


class ConnectionManager:
    """Thread-safe (asyncio) WebSocket hub."""

    def __init__(self) -> None:
        self._clients: dict[str, _ClientState] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self,
        ws: WebSocket,
        client_id: str | None = None,
        session_id: str | None = None,
    ) -> str:
        """Accept the WebSocket and register the client.

        Returns the resolved client_id (auto-generated if not provided).
        """
        await ws.accept()
        cid = client_id or str(uuid.uuid4())
        async with self._lock:
            # Replace stale entry for same client_id (reconnect-safe)
            self._clients[cid] = _ClientState(ws, session_id=session_id)
        await ws.send_json(WelcomeMessage(client_id=cid).model_dump())
        return cid

    async def disconnect(self, client_id: str) -> None:
        async with self._lock:
            self._clients.pop(client_id, None)

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def subscribe(self, client_id: str, channels: list[str]) -> list[str]:
        """Add channel subscriptions for a client; return accepted channels."""
        accepted: list[str] = []
        async with self._lock:
            state = self._clients.get(client_id)
            if state is None:
                return accepted
            for ch in channels:
                if ch in VALID_CHANNELS:
                    state.channels.add(ch)
                    accepted.append(ch)
        return accepted

    def get_subscriptions(self, client_id: str) -> list[str]:
        state = self._clients.get(client_id)
        return sorted(state.channels) if state else []

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(
        self,
        channel: str,
        event: str,
        payload: dict[str, Any] | None = None,
    ) -> int:
        """Broadcast an event to all clients subscribed to *channel* (or ``*``).

        Returns the number of clients reached.
        """
        msg = OutboundEvent(
            channel=channel,
            event=event,
            payload=payload or {},
        ).model_dump()

        dead: list[str] = []
        sent = 0

        async with self._lock:
            targets = dict(self._clients)

        for cid, state in targets.items():
            if channel not in state.channels and "*" not in state.channels:
                continue
            try:
                if state.ws.client_state == WebSocketState.CONNECTED:
                    await state.ws.send_json(msg)
                    sent += 1
                else:
                    dead.append(cid)
            except Exception:
                dead.append(cid)

        if dead:
            async with self._lock:
                for cid in dead:
                    self._clients.pop(cid, None)

        return sent

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    async def ping_all(self) -> None:
        """Send a ping to every connected client and evict stale ones."""
        ping_msg = PingMessage().model_dump()
        now = time.monotonic()
        dead: list[str] = []

        async with self._lock:
            targets = dict(self._clients)

        for cid, state in targets.items():
            if now - state.last_pong > PONG_TIMEOUT:
                dead.append(cid)
                continue
            try:
                if state.ws.client_state == WebSocketState.CONNECTED:
                    await state.ws.send_json(ping_msg)
                else:
                    dead.append(cid)
            except Exception:
                dead.append(cid)

        if dead:
            async with self._lock:
                for cid in dead:
                    self._clients.pop(cid, None)

    def record_pong(self, client_id: str) -> None:
        state = self._clients.get(client_id)
        if state:
            state.last_pong = time.monotonic()

    async def heartbeat_loop(self) -> None:
        """Async background task: ping all clients every PING_INTERVAL seconds."""
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await self.ping_all()

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def connection_count(self) -> int:
        return len(self._clients)

    def connected_client_ids(self) -> list[str]:
        return list(self._clients.keys())


# ---------------------------------------------------------------------------
# Handle a single WebSocket connection (used by the /ws/control endpoint)
# ---------------------------------------------------------------------------


async def handle_ws_connection(
    ws: WebSocket,
    manager: ConnectionManager,
    client_id: str | None = None,
) -> None:
    """Accept and drive a single WebSocket client until disconnect."""
    cid = await manager.connect(ws, client_id=client_id)
    try:
        while True:
            raw = await ws.receive_json()
            msg_type = str(raw.get("type", ""))

            if msg_type == "subscribe":
                msg = SubscribeMessage.model_validate(raw)
                accepted = await manager.subscribe(cid, msg.channels)
                await ws.send_json({"type": "subscribed", "channels": accepted})

            elif msg_type == "pong":
                manager.record_pong(cid)

            else:
                await ws.send_json(ErrorMessage(detail=f"Unknown message type: {msg_type!r}").model_dump())

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(cid)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

ws_hub = ConnectionManager()
