"""Tests for Feature 1 — WebSocket Control Plane.

Covers:
- Sprint 1.1: connection management, channel subscriptions, reconnect-safe IDs
- Sprint 1.2: task event emitter (TaskTracker → WS broadcast)
- Heartbeat: ping sent, stale client eviction, pong recording
"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.websockets import WebSocket as FastAPIWebSocket
from starlette.testclient import WebSocketTestSession


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fresh_manager():
    """Return a brand-new ConnectionManager (not the module singleton)."""
    from backend.websocket.hub import ConnectionManager
    return ConnectionManager()


@pytest.fixture()
def ws_app(fresh_manager):
    """Minimal FastAPI app with a /ws/test endpoint using fresh_manager."""
    from backend.websocket.hub import handle_ws_connection

    app = FastAPI()

    @app.websocket("/ws/test")
    async def _endpoint(ws: FastAPIWebSocket):
        await handle_ws_connection(ws, fresh_manager, client_id=None)

    return app, fresh_manager


# ---------------------------------------------------------------------------
# Sprint 1.1 — Connection Management
# ---------------------------------------------------------------------------

def test_ws_connection_sends_welcome(ws_app) -> None:
    app, manager = ws_app
    client = TestClient(app)
    with client.websocket_connect("/ws/test") as ws:
        welcome = ws.receive_json()
    assert welcome["type"] == "connected"
    assert "client_id" in welcome


def test_ws_subscribe_accepted_channels(ws_app) -> None:
    app, _ = ws_app
    client = TestClient(app)
    with client.websocket_connect("/ws/test") as ws:
        ws.receive_json()  # welcome
        ws.send_json({"type": "subscribe", "channels": ["tasks", "agents"]})
        resp = ws.receive_json()
    assert resp["type"] == "subscribed"
    assert set(resp["channels"]) == {"tasks", "agents"}


def test_ws_subscribe_ignores_invalid_channel(ws_app) -> None:
    app, _ = ws_app
    client = TestClient(app)
    with client.websocket_connect("/ws/test") as ws:
        ws.receive_json()  # welcome
        ws.send_json({"type": "subscribe", "channels": ["tasks", "not_a_channel"]})
        resp = ws.receive_json()
    # "not_a_channel" filtered out
    assert "not_a_channel" not in resp["channels"]
    assert "tasks" in resp["channels"]


def test_ws_unknown_message_type_returns_error(ws_app) -> None:
    app, _ = ws_app
    client = TestClient(app)
    with client.websocket_connect("/ws/test") as ws:
        ws.receive_json()  # welcome
        ws.send_json({"type": "explode"})
        resp = ws.receive_json()
    assert resp["type"] == "error"
    assert "explode" in resp["detail"]


def test_ws_reconnect_same_client_id_replaces_slot(ws_app) -> None:
    """Reconnecting with the same client_id should not duplicate the entry."""
    from backend.websocket.hub import ConnectionManager, handle_ws_connection

    app = FastAPI()
    mgr = ConnectionManager()

    @app.websocket("/ws/multi")
    async def _ep(ws: FastAPIWebSocket):
        await handle_ws_connection(ws, mgr, client_id="fixed-id")

    client = TestClient(app)
    with client.websocket_connect("/ws/multi") as ws:
        ws.receive_json()

    # After disconnect the slot is removed
    assert mgr.connection_count == 0

    # Reconnect
    with client.websocket_connect("/ws/multi") as ws:
        ws.receive_json()
        assert mgr.connection_count == 1


def test_ws_multiple_clients_independent(ws_app) -> None:
    app, manager = ws_app
    client = TestClient(app)

    # Open two simultaneous connections
    with client.websocket_connect("/ws/test") as ws1:
        w1 = ws1.receive_json()
        with client.websocket_connect("/ws/test") as ws2:
            w2 = ws2.receive_json()
            assert w1["client_id"] != w2["client_id"]


# ---------------------------------------------------------------------------
# Sprint 1.1 — get_subscriptions
# ---------------------------------------------------------------------------

def test_get_subscriptions_returns_active_channels(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED
        cid = await fresh_manager.connect(ws_mock, client_id="test-sub")
        await fresh_manager.subscribe(cid, ["tasks", "logs"])
        return fresh_manager.get_subscriptions(cid)

    subs = asyncio.run(_run())
    assert "tasks" in subs
    assert "logs" in subs


# ---------------------------------------------------------------------------
# Sprint 1.2 — Broadcast
# ---------------------------------------------------------------------------

def test_broadcast_delivers_to_subscribed_client(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        received: list[dict] = []
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED
        ws_mock.send_json = AsyncMock(side_effect=lambda x: received.append(x))
        cid = await fresh_manager.connect(ws_mock, client_id="bcast-client")
        await fresh_manager.subscribe(cid, ["tasks"])
        count = await fresh_manager.broadcast("tasks", "task_created", {"id": "t1"})
        return received, count

    received, count = asyncio.run(_run())
    events = [m for m in received if m.get("type") == "event"]
    assert count == 1
    assert len(events) == 1
    assert events[0]["channel"] == "tasks"
    assert events[0]["event"] == "task_created"
    assert events[0]["payload"]["id"] == "t1"


def test_broadcast_skips_unsubscribed_client(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        call_count = {"n": 0}
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED

        async def _track(msg):
            if msg.get("type") == "event":
                call_count["n"] += 1

        ws_mock.send_json = AsyncMock(side_effect=_track)
        cid = await fresh_manager.connect(ws_mock, client_id="nosub")
        await fresh_manager.subscribe(cid, ["logs"])  # subscribed to logs, not tasks
        count = await fresh_manager.broadcast("tasks", "task_created", {})
        return count, call_count["n"]

    count, n = asyncio.run(_run())
    assert count == 0
    assert n == 0


def test_broadcast_wildcard_subscription_receives_all_channels(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        received: list[dict] = []
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED
        ws_mock.send_json = AsyncMock(side_effect=lambda x: received.append(x))
        cid = await fresh_manager.connect(ws_mock, client_id="wild")
        await fresh_manager.subscribe(cid, ["*"])
        await fresh_manager.broadcast("agents", "agent_response", {"agent": "craig"})
        await fresh_manager.broadcast("logs", "mcp_status", {"ok": True})
        return received

    received = asyncio.run(_run())
    events = [m for m in received if m.get("type") == "event"]
    assert len(events) == 2


# ---------------------------------------------------------------------------
# Heartbeat — ping_all / record_pong / stale eviction
# ---------------------------------------------------------------------------

def test_ping_all_sends_ping_to_connected_clients(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        pings: list[dict] = []
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED
        ws_mock.send_json = AsyncMock(side_effect=lambda x: pings.append(x))
        await fresh_manager.connect(ws_mock, client_id="ping-client")
        await fresh_manager.ping_all()
        return pings

    pings = asyncio.run(_run())
    ping_msgs = [m for m in pings if m.get("type") == "ping"]
    assert len(ping_msgs) >= 1


def test_stale_client_evicted_on_ping(fresh_manager) -> None:
    from starlette.websockets import WebSocketState

    async def _run():
        ws_mock = AsyncMock()
        ws_mock.client_state = WebSocketState.CONNECTED
        cid = await fresh_manager.connect(ws_mock, client_id="stale")
        fresh_manager._clients[cid].last_pong = time.monotonic() - 100
        await fresh_manager.ping_all()
        return cid

    cid = asyncio.run(_run())
    assert cid not in fresh_manager._clients


def test_record_pong_updates_last_pong(fresh_manager) -> None:
    async def _run():
        ws_mock = AsyncMock()
        cid = await fresh_manager.connect(ws_mock, client_id="pong-client")
        old_time = fresh_manager._clients[cid].last_pong
        await asyncio.sleep(0.01)
        fresh_manager.record_pong(cid)
        return old_time, fresh_manager._clients[cid].last_pong

    old_time, new_time = asyncio.run(_run())
    assert new_time > old_time


# ---------------------------------------------------------------------------
# Sprint 1.2 — Task event emitter integration
# ---------------------------------------------------------------------------

def test_task_tracker_subscribe_unsubscribe_compiles() -> None:
    """Smoke test that the task tracker SSE API is compatible with the emitter loop."""
    from backend.tasks import task_tracker

    q = task_tracker.subscribe()
    assert q is not None
    task_tracker.unsubscribe(q)


# ---------------------------------------------------------------------------
# Server endpoint smoke test
# ---------------------------------------------------------------------------

def test_ws_control_endpoint_exists_in_app() -> None:
    """Confirm /ws/control is registered in the real server app."""
    from backend.server import app

    routes = [r.path for r in app.routes]  # type: ignore[attr-defined]
    assert "/ws/control" in routes
