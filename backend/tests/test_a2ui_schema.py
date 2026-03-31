"""Tests for Feature 5 — Canvas + A2UI.

Covers:
- Sprint 5.1: strict schema validation (all ops, unknown components, bad props)
- Sprint 5.2: sequence numbers, WS broadcast
- Sprint 5.3: v1 component prop schemas
- Sprint 5.4: action dispatch route
- Sprint 5.5: quota, permission, clear
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_msg(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "session_id": "sess-1",
        "agent_id": "agent-a",
        "op": "render",
        "target": "canvas/main",
        "widget_id": "w-001",
        "component": "status_card",
        "props": {"title": "Deploy", "state": "running"},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Sprint 5.1 — Schema validation
# ---------------------------------------------------------------------------


def test_a2ui_message_valid_render() -> None:
    from backend.a2ui.schema import A2UIMessage

    msg = A2UIMessage(**_base_msg())
    assert msg.op == "render"
    assert msg.component == "status_card"
    assert msg.props is not None
    assert msg.props["title"] == "Deploy"


def test_a2ui_message_assign_uuid_and_timestamp() -> None:
    from backend.a2ui.schema import A2UIMessage

    msg = A2UIMessage(**_base_msg())
    assert len(msg.ui_event_id) == 36
    assert "T" in msg.timestamp  # ISO datetime


def test_a2ui_message_render_requires_component() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception, match="component"):
        A2UIMessage(**_base_msg(component=None))


def test_a2ui_message_render_requires_widget_id() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception, match="widget_id"):
        A2UIMessage(**_base_msg(widget_id=None))


def test_a2ui_message_clear_does_not_require_component() -> None:
    from backend.a2ui.schema import A2UIMessage

    msg = A2UIMessage(
        session_id="s1",
        agent_id="a1",
        op="clear",
        target="canvas/main",
    )
    assert msg.op == "clear"


def test_a2ui_message_rejects_unknown_component() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception):
        A2UIMessage(**_base_msg(component="chat_bubble"))  # not in v1


def test_a2ui_message_rejects_bad_target_format() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception, match="target"):
        A2UIMessage(**_base_msg(target="badtarget"))


def test_a2ui_message_rejects_target_with_spaces() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception):
        A2UIMessage(**_base_msg(target="canvas/has space"))


def test_a2ui_message_extra_fields_forbidden() -> None:
    from backend.a2ui.schema import A2UIMessage

    with pytest.raises(Exception):
        A2UIMessage(**_base_msg(), unknown_field="boom")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Sprint 5.3 — Per-component prop validation
# ---------------------------------------------------------------------------


def test_status_card_valid_props() -> None:
    from backend.a2ui.schema import StatusCardProps

    props = StatusCardProps(title="Deploy", state="running")
    assert props.state == "running"


def test_status_card_invalid_state() -> None:
    from backend.a2ui.schema import StatusCardProps

    with pytest.raises(Exception):
        StatusCardProps(title="Deploy", state="flying")  # type: ignore[arg-type]


def test_status_card_extra_fields_forbidden() -> None:
    from backend.a2ui.schema import StatusCardProps

    with pytest.raises(Exception):
        StatusCardProps(title="T", state="idle", extra_prop="no")  # type: ignore[call-arg]


def test_task_list_valid() -> None:
    from backend.a2ui.schema import TaskListProps

    props = TaskListProps(title="Tasks", tasks=[{"id": "1", "label": "A"}])
    assert len(props.tasks) == 1


def test_kv_table_valid() -> None:
    from backend.a2ui.schema import KVTableProps

    props = KVTableProps(title="Config", rows=[{"key": "port", "value": "8080"}])
    assert props.striped is True


def test_validate_component_props_unknown_component() -> None:
    from backend.a2ui.schema import validate_component_props

    with pytest.raises(ValueError, match="Unknown A2UI component"):
        validate_component_props("chart_widget", {})


# ---------------------------------------------------------------------------
# Sprint 5.2 — Sequence numbers + bus emit
# ---------------------------------------------------------------------------


def test_bus_assigns_sequence_numbers() -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with patch("backend.a2ui.bus.ws_hub") as mock_hub:
            mock_hub.broadcast = AsyncMock(return_value=0)
            m1 = A2UIMessage(**_base_msg())
            m2 = A2UIMessage(**_base_msg(widget_id="w-002"))
            await bus.emit(m1)
            await bus.emit(m2)
        return m1.seq, m2.seq

    s1, s2 = asyncio.run(_run())
    assert s1 == 0
    assert s2 == 1


def test_bus_broadcasts_to_canvas_channel() -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()
    calls: list[dict] = []

    async def _fake_broadcast(channel, event, payload):
        calls.append({"channel": channel, "event": event})
        return 1

    async def _run():
        with patch("backend.a2ui.bus.ws_hub") as mock_hub:
            mock_hub.broadcast = _fake_broadcast
            m = A2UIMessage(**_base_msg())
            await bus.emit(m)

    asyncio.run(_run())
    assert calls[0]["channel"] == "canvas"
    assert calls[0]["event"] == "canvas_render"


def test_bus_tracks_canvas_state_after_render() -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with patch("backend.a2ui.bus.ws_hub") as mock_hub:
            mock_hub.broadcast = AsyncMock(return_value=0)
            m = A2UIMessage(**_base_msg())
            await bus.emit(m)

    asyncio.run(_run())
    state = bus.get_canvas_state("sess-1")
    assert "canvas/main" in state
    assert "w-001" in state["canvas/main"]


def test_bus_clear_removes_all_widgets() -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with patch("backend.a2ui.bus.ws_hub") as mock_hub:
            mock_hub.broadcast = AsyncMock(return_value=0)
            m = A2UIMessage(**_base_msg())
            await bus.emit(m)
            result = await bus.clear_canvas("sess-1")
        return result

    result = asyncio.run(_run())
    assert result["ok"] is True
    assert result["widgets_removed"] == 1
    assert "canvas/main" not in bus.get_canvas_state("sess-1")


# ---------------------------------------------------------------------------
# Sprint 5.5 — Quota enforcement
# ---------------------------------------------------------------------------


def test_bus_raises_quota_exceeded() -> None:
    from backend.a2ui.bus import A2UIBus, A2UIQuotaError
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with (
            patch("backend.a2ui.bus.ws_hub") as mock_hub,
            patch("backend.a2ui.bus.A2UI_MAX_EVENTS_PER_SESSION", 2),
        ):
            mock_hub.broadcast = AsyncMock(return_value=0)
            for i in range(2):
                await bus.emit(A2UIMessage(**_base_msg(widget_id=f"w-{i}")))
            # 3rd emit should fail
            with pytest.raises(A2UIQuotaError):
                await bus.emit(A2UIMessage(**_base_msg(widget_id="w-99")))

    asyncio.run(_run())


def test_bus_raises_widget_count_exceeded() -> None:
    from backend.a2ui.bus import A2UIBus, A2UIQuotaError
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with (
            patch("backend.a2ui.bus.ws_hub") as mock_hub,
            patch("backend.a2ui.bus.A2UI_MAX_WIDGETS_PER_TARGET", 2),
        ):
            mock_hub.broadcast = AsyncMock(return_value=0)
            for i in range(2):
                await bus.emit(A2UIMessage(**_base_msg(widget_id=f"w-{i}")))
            with pytest.raises(A2UIQuotaError, match="widget limit"):
                await bus.emit(A2UIMessage(**_base_msg(widget_id="w-new")))

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Sprint 5.5 — Permission check
# ---------------------------------------------------------------------------


def test_bus_raises_permission_error_for_disallowed_agent() -> None:
    from backend.a2ui.bus import A2UIBus, A2UIPermissionError
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with (
            patch("backend.a2ui.bus.A2UI_ALLOWED_AGENTS", ["allowed-only"]),
        ):
            with pytest.raises(A2UIPermissionError):
                await bus.emit(A2UIMessage(**_base_msg(agent_id="rogue-agent")))

    asyncio.run(_run())


def test_bus_allows_agent_when_list_empty() -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.a2ui.schema import A2UIMessage

    bus = A2UIBus()

    async def _run():
        with (
            patch("backend.a2ui.bus.A2UI_ALLOWED_AGENTS", []),
            patch("backend.a2ui.bus.ws_hub") as mock_hub,
        ):
            mock_hub.broadcast = AsyncMock(return_value=0)
            await bus.emit(A2UIMessage(**_base_msg(agent_id="any-agent")))

    asyncio.run(_run())  # should not raise


# ---------------------------------------------------------------------------
# REST route integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def a2ui_client() -> TestClient:
    from backend.routes.a2ui import router as a2ui_router

    app = FastAPI()
    app.include_router(a2ui_router)
    return TestClient(app, raise_server_exceptions=True)


def test_canvas_emit_route_returns_seq(a2ui_client: TestClient) -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.routes import a2ui as a2ui_route_module

    fresh_bus = A2UIBus()

    async def _fake_emit(msg):
        msg.seq = 0
        return {"ok": True, "seq": 0, "ws_clients_reached": 0}

    fresh_bus.emit = _fake_emit  # type: ignore[method-assign]
    a2ui_route_module._get_bus = lambda: fresh_bus

    resp = a2ui_client.post(
        "/canvas/sess-42/event",
        json=_base_msg(session_id="sess-42"),
    )
    assert resp.status_code == 200
    assert "seq" in resp.json()


def test_canvas_state_route(a2ui_client: TestClient) -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.routes import a2ui as a2ui_route_module

    fresh_bus = A2UIBus()
    a2ui_route_module._get_bus = lambda: fresh_bus

    resp = a2ui_client.get("/canvas/sess-x/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "targets" in data


def test_canvas_clear_route(a2ui_client: TestClient) -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.routes import a2ui as a2ui_route_module

    fresh_bus = A2UIBus()
    a2ui_route_module._get_bus = lambda: fresh_bus

    resp = a2ui_client.delete("/canvas/sess-z")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_canvas_emit_422_on_session_id_mismatch(a2ui_client: TestClient) -> None:
    from backend.a2ui.bus import A2UIBus
    from backend.routes import a2ui as a2ui_route_module

    a2ui_route_module._get_bus = A2UIBus
    resp = a2ui_client.post(
        "/canvas/sess-AAA/event",
        json=_base_msg(session_id="sess-BBB"),
    )
    assert resp.status_code == 422
