from __future__ import annotations

import hashlib
import hmac
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def _signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _client_with_webhooks(tmp_path: Path) -> tuple[TestClient, dict[str, Any]]:
    from backend.routes import webhooks as webhooks_routes

    webhooks_routes.configure_webhooks(
        storage_path=tmp_path / "webhooks.json",
        secret="unit-test-secret",
    )
    webhooks_routes.configure_webhook_limits(rate_limit_rpm=60)

    captured: dict[str, Any] = {}

    async def fake_dispatch(agent_id: str, message: str, context: dict[str, Any]) -> dict[str, Any]:
        captured["agent_id"] = agent_id
        captured["message"] = message
        captured["context"] = context
        return {"ok": True}

    webhooks_routes.set_dispatcher(fake_dispatch)

    app = FastAPI()
    app.include_router(webhooks_routes.router)
    return TestClient(app), captured


def test_register_list_delete_webhook(tmp_path: Path):
    client, _ = _client_with_webhooks(tmp_path)

    created = client.post(
        "/webhooks/register",
        json={
            "agent_id": "knowledge_agent",
            "message_template": "new event {event_type}",
            "webhook_id": "wh_test",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["webhook_id"] == "wh_test"
    assert body["agent_id"] == "knowledge_agent"

    listed = client.get("/webhooks")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["webhook_id"] == "wh_test"

    deleted = client.delete("/webhooks/wh_test")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"

    listed_after = client.get("/webhooks")
    assert listed_after.status_code == 200
    assert listed_after.json() == []


def test_signed_webhook_dispatches_to_agent(tmp_path: Path):
    client, captured = _client_with_webhooks(tmp_path)

    create = client.post(
        "/webhooks/register",
        json={
            "agent_id": "knowledge_agent",
            "message_template": "source={source} event={event_type}",
            "webhook_id": "wh_dispatch",
        },
    )
    assert create.status_code == 200

    payload_obj = {"source": "github", "event_type": "push", "ref": "refs/heads/main"}
    payload = json.dumps(payload_obj).encode("utf-8")
    signed = _signature("unit-test-secret", payload)

    resp = client.post(
        "/webhooks/wh_dispatch",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Agentop-Signature": signed,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["agent_id"] == "knowledge_agent"

    assert captured["agent_id"] == "knowledge_agent"
    assert captured["message"] == "source=github event=push"
    assert captured["context"]["source"] == "webhook"
    assert captured["context"]["webhook_id"] == "wh_dispatch"
    assert captured["context"]["payload"] == payload_obj


def test_invalid_signature_rejected(tmp_path: Path):
    client, _ = _client_with_webhooks(tmp_path)

    create = client.post(
        "/webhooks/register",
        json={
            "agent_id": "knowledge_agent",
            "message_template": "event {event_type}",
            "webhook_id": "wh_sig",
        },
    )
    assert create.status_code == 200

    payload = json.dumps({"event_type": "deploy"}).encode("utf-8")
    resp = client.post(
        "/webhooks/wh_sig",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Agentop-Signature": "sha256=notavalidsignature",
        },
    )
    assert resp.status_code == 401
    assert "Invalid signature" in resp.text


def test_webhook_dry_run_skips_dispatch(tmp_path: Path):
    client, captured = _client_with_webhooks(tmp_path)

    create = client.post(
        "/webhooks/register",
        json={
            "agent_id": "knowledge_agent",
            "message_template": "event {event_type}",
            "webhook_id": "wh_dryrun",
        },
    )
    assert create.status_code == 200

    payload_obj = {"event_type": "build"}
    payload = json.dumps(payload_obj).encode("utf-8")
    signed = _signature("unit-test-secret", payload)

    resp = client.post(
        "/webhooks/wh_dryrun?dry_run=true",
        content=payload,
        headers={
            "Content-Type": "application/json",
            "X-Agentop-Signature": signed,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["dry_run"] is True
    assert body["dispatch_result"] is None
    assert "event build" in body["rendered_message"]
    assert captured == {}


def test_webhook_rate_limit_enforced(tmp_path: Path):
    from backend.routes import webhooks as webhooks_routes

    client, _ = _client_with_webhooks(tmp_path)
    webhooks_routes.configure_webhook_limits(rate_limit_rpm=1)

    create = client.post(
        "/webhooks/register",
        json={
            "agent_id": "knowledge_agent",
            "message_template": "event {event_type}",
            "webhook_id": "wh_rl",
        },
    )
    assert create.status_code == 200

    payload = json.dumps({"event_type": "deploy"}).encode("utf-8")
    signed = _signature("unit-test-secret", payload)
    headers = {
        "Content-Type": "application/json",
        "X-Agentop-Signature": signed,
    }

    first = client.post("/webhooks/wh_rl", content=payload, headers=headers)
    assert first.status_code == 200

    second = client.post("/webhooks/wh_rl", content=payload, headers=headers)
    assert second.status_code == 429
    assert "rate limit" in second.text.lower()
