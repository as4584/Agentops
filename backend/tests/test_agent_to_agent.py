from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from backend.orchestrator import AgentOrchestrator

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _orchestrator_stub() -> AgentOrchestrator:
    from backend.orchestrator import AgentOrchestrator

    orchestrator: AgentOrchestrator = object.__new__(AgentOrchestrator)
    orchestrator._knowledge_agent_id = "knowledge_agent"
    orchestrator._agents = {
        "agent_a": object(),
        "agent_b": object(),
    }
    return orchestrator


def test_send_list_history_and_dedupe(monkeypatch):
    import backend.orchestrator as orchestrator_module
    from backend.orchestrator import AgentOrchestrator

    orchestrator = _orchestrator_stub()

    shared_events: list[dict] = []

    def fake_append(event: dict) -> None:
        stamped = dict(event)
        stamped.setdefault("timestamp", "2026-03-06T00:00:00+00:00")
        shared_events.append(stamped)

    def fake_get(limit: int = 50):
        return shared_events[-limit:]

    monkeypatch.setattr(orchestrator_module.memory_store, "append_shared_event", fake_append)
    monkeypatch.setattr(orchestrator_module.memory_store, "get_shared_events", fake_get)

    first = AgentOrchestrator.send_agent_message(
        orchestrator,
        from_agent="agent_a",
        to_agent="agent_b",
        purpose="delegate research",
        payload={"topic": "pricing"},
        message_id="msg_1",
    )

    assert first["message_id"] == "msg_1"
    assert first["thread_id"] == "msg_1"

    second = AgentOrchestrator.send_agent_message(
        orchestrator,
        from_agent="agent_b",
        to_agent="agent_a",
        purpose="response",
        payload={"summary": "done"},
        parent_message_id="msg_1",
        thread_id="msg_1",
        message_id="msg_2",
        depth=1,
    )
    assert second["thread_id"] == "msg_1"

    listed = AgentOrchestrator.list_agent_messages(orchestrator, agent_id="agent_a", limit=50)
    assert len(listed) == 2

    thread = AgentOrchestrator.get_message_history(orchestrator, thread_id="msg_1")
    assert [item["message_id"] for item in thread] == ["msg_1", "msg_2"]

    try:
        AgentOrchestrator.send_agent_message(
            orchestrator,
            from_agent="agent_a",
            to_agent="agent_b",
            purpose="duplicate",
            payload={},
            message_id="msg_1",
        )
        assert False, "expected duplicate message_id error"
    except ValueError as exc:
        assert "Duplicate message_id" in str(exc)


def test_depth_and_self_send_policy(monkeypatch):
    import backend.orchestrator as orchestrator_module
    from backend.config import A2A_MAX_DEPTH
    from backend.orchestrator import AgentOrchestrator

    orchestrator = _orchestrator_stub()

    events: list[dict] = []
    monkeypatch.setattr(orchestrator_module.memory_store, "append_shared_event", lambda event: events.append(event))
    monkeypatch.setattr(orchestrator_module.memory_store, "get_shared_events", lambda limit=50: events[-limit:])

    try:
        AgentOrchestrator.send_agent_message(
            orchestrator,
            from_agent="agent_a",
            to_agent="agent_a",
            purpose="self",
            payload={},
        )
        assert False, "expected self-send policy error"
    except ValueError as exc:
        assert "Self-send" in str(exc)

    try:
        AgentOrchestrator.send_agent_message(
            orchestrator,
            from_agent="agent_a",
            to_agent="agent_b",
            purpose="too deep",
            payload={},
            depth=A2A_MAX_DEPTH + 1,
        )
        assert False, "expected depth guard error"
    except ValueError as exc:
        assert "depth exceeded" in str(exc)


def test_agent_message_routes_with_injected_orchestrator():
    from backend.routes import agent_control

    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def list_agent_messages(self, agent_id: str, limit: int = 50):
            return [{"message_id": "m1", "from_agent": agent_id, "to_agent": "agent_b", "thread_id": "m1"}]

        def send_agent_message(self, **kwargs):
            captured.update(kwargs)
            return {"message_id": "m2", "thread_id": kwargs.get("thread_id") or "m2", **kwargs}

        def get_message_history(self, thread_id: str):
            return [{"message_id": "m2", "thread_id": thread_id}]

    agent_control.set_orchestrator(FakeOrchestrator())  # type: ignore[arg-type]

    app = FastAPI()
    app.include_router(agent_control.router)
    app.include_router(agent_control.a2a_router)
    client = TestClient(app)

    listed = client.get("/agents/messages", params={"agent_id": "agent_a", "limit": 10})
    assert listed.status_code == 200
    assert listed.json()[0]["message_id"] == "m1"

    sent = client.post(
        "/agents/messages/send",
        json={
            "from_agent": "agent_a",
            "to_agent": "agent_b",
            "purpose": "test",
            "payload": {"k": "v"},
            "depth": 0,
        },
    )
    assert sent.status_code == 200
    assert captured["from_agent"] == "agent_a"

    thread = client.get("/agents/messages/thread/m2")
    assert thread.status_code == 200
    assert thread.json()[0]["thread_id"] == "m2"
