"""
End-to-end coverage for the proposed-action approval loop.

Week 2 sprint A2 + A3. Verifies:
  - POST /actions/proposed → action persisted, audit row written
  - GET  /actions/pending → returns it
  - POST /actions/{id}/approve → executor runs, status=EXECUTED, audit rows linked
  - POST /actions/{id}/reject → status=REJECTED, no executor
  - Idempotent re-approval / re-rejection of a terminal action
  - source=discord attribution survives the round-trip into the audit log
  - GET /audit returns the full timeline for a single action

The executor is mocked at module level so no real ``pkill`` is invoked.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.database import actions_store as actions_store_module
from backend.database import audit_store as audit_store_module
from backend.routes import actions as actions_route


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Isolated app with temp SQLite + mocked process_restart executor."""
    # Swap the module-level singletons to per-test databases.
    actions_store_module.reset_default_store(tmp_path / "actions.db")
    audit_store_module.reset_default_store(tmp_path / "audit.db")

    captured: dict[str, Any] = {}

    async def _fake_restart(action, params):  # type: ignore[no-untyped-def]
        captured["called"] = True
        captured["process_name"] = params.get("process_name")
        captured["operator"] = action.operator
        return {"success": True, "process": params.get("process_name"), "return_code": 0}

    monkeypatch.setitem(actions_route.ACTION_DISPATCH, "process_restart", _fake_restart)
    monkeypatch.setattr(actions_route, "_captured", captured, raising=False)

    fastapi_app = FastAPI()
    fastapi_app.include_router(actions_route.router)
    fastapi_app.include_router(actions_route.audit_router)
    return fastapi_app


@pytest.fixture()
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _propose(client: TestClient, source: str = "web", agent_id: str = "knowledge_agent") -> dict[str, Any]:
    resp = client.post(
        "/actions/proposed",
        json={
            "agent_id": agent_id,
            "action_type": "process_restart",
            "parameters": {"process_name": "nginx"},
            "summary": "nginx is returning 502",
            "source": source,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_full_approval_loop_writes_audit_timeline(client: TestClient) -> None:
    action = _propose(client)
    assert action["status"] == "pending"
    assert action["source"] == "web"

    pending = client.get("/actions/pending").json()
    assert any(a["id"] == action["id"] for a in pending)

    approved = client.post(f"/actions/{action['id']}/approve", json={"operator": "lex"}).json()
    assert approved["status"] == "executed"
    assert approved["operator"] == "lex"
    assert approved["result"]["success"] is True
    assert approved["executed_at"] is not None

    # No longer pending.
    pending_after = client.get("/actions/pending").json()
    assert not any(a["id"] == action["id"] for a in pending_after)

    # Audit log holds: proposed, approved, executed — three rows, all linked.
    rows = client.get("/audit", params={"limit": 100}).json()
    events_for_action = [r for r in rows if r["payload_json"].get("action_id") == action["id"]]
    event_names = sorted(r["payload_json"]["event"] for r in events_for_action)
    assert event_names == ["approved", "executed", "proposed"]
    executed_row = next(r for r in events_for_action if r["payload_json"]["event"] == "executed")
    assert executed_row["result_json"]["success"] is True
    assert executed_row["operator"] == "lex"


def test_rejection_sets_status_and_audits_reason(client: TestClient) -> None:
    action = _propose(client)
    rejected = client.post(
        f"/actions/{action['id']}/reject",
        json={"operator": "lex", "reason": "wrong process"},
    ).json()
    assert rejected["status"] == "rejected"
    assert rejected["reason"] == "wrong process"

    rows = client.get("/audit").json()
    reject_row = next(
        r
        for r in rows
        if r["payload_json"].get("event") == "rejected" and r["payload_json"].get("action_id") == action["id"]
    )
    assert reject_row["payload_json"]["reason"] == "wrong process"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_approve_is_idempotent_for_terminal_actions(client: TestClient) -> None:
    action = _propose(client)
    first = client.post(f"/actions/{action['id']}/approve", json={"operator": "lex"}).json()
    second = client.post(f"/actions/{action['id']}/approve", json={"operator": "lex"}).json()
    assert first["status"] == "executed"
    assert second["status"] == "executed"
    assert first["executed_at"] == second["executed_at"]  # not re-executed


def test_reject_after_approve_is_no_op(client: TestClient) -> None:
    action = _propose(client)
    client.post(f"/actions/{action['id']}/approve", json={"operator": "lex"})
    resp = client.post(
        f"/actions/{action['id']}/reject",
        json={"operator": "lex", "reason": "changed my mind"},
    ).json()
    assert resp["status"] == "executed"  # unchanged


# ---------------------------------------------------------------------------
# Source attribution (A3 acceptance criterion)
# ---------------------------------------------------------------------------


def test_discord_source_attribution_survives_to_audit_log(client: TestClient) -> None:
    action = _propose(client, source="discord")
    client.post(f"/actions/{action['id']}/approve", json={"operator": "discord:lex#1234"})

    rows = client.get("/audit", params={"limit": 100}).json()
    discord_rows = [r for r in rows if r["source"] == "discord"]
    assert len(discord_rows) >= 3  # proposed + approved + executed
    assert all(r["payload_json"].get("action_id") == action["id"] for r in discord_rows)
    operator_set = {r["operator"] for r in discord_rows if r["operator"]}
    assert "discord:lex#1234" in operator_set


def test_audit_filters_by_operator(client: TestClient) -> None:
    a1 = _propose(client)
    a2 = _propose(client)
    client.post(f"/actions/{a1['id']}/approve", json={"operator": "alice"})
    client.post(f"/actions/{a2['id']}/approve", json={"operator": "bob"})

    alice_rows = client.get("/audit", params={"operator": "alice"}).json()
    assert alice_rows  # at least one
    assert all(r["operator"] == "alice" for r in alice_rows)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_unknown_action_returns_404(client: TestClient) -> None:
    resp = client.post("/actions/act_does_not_exist/approve", json={"operator": "lex"})
    assert resp.status_code == 404


def test_unmapped_action_type_records_failed_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        actions_route.ACTION_DISPATCH, "process_restart", actions_route.ACTION_DISPATCH["process_restart"]
    )
    # Propose an action whose type is not in the dispatch table.
    resp = client.post(
        "/actions/proposed",
        json={
            "agent_id": "knowledge_agent",
            "action_type": "no_such_tool",
            "parameters": {},
            "source": "web",
        },
    )
    action = resp.json()
    approved = client.post(f"/actions/{action['id']}/approve", json={"operator": "lex"}).json()
    assert approved["status"] == "failed"
    assert "no_such_tool" in approved["result"]["error"]
