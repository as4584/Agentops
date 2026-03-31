from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.agents import ALL_AGENT_DEFINITIONS
from backend.config import AGENTOP_WEBHOOK_SECRET, API_SECRET, WEBHOOK_RATE_LIMIT_RPM, WEBHOOKS_DB_PATH
from backend.utils import logger

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

DispatchCallable = Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any] | Any]]

_webhook_secret = AGENTOP_WEBHOOK_SECRET or API_SECRET


class WebhookRegisterRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    message_template: str = Field(..., min_length=1)
    webhook_id: str | None = Field(default=None, min_length=1)


class WebhookRecord(BaseModel):
    webhook_id: str
    agent_id: str
    message_template: str
    created_at: str


class _WebhookRegistry:
    def __init__(self, storage_path: Path) -> None:
        self.storage_path = storage_path
        self._lock = Lock()

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.storage_path.exists():
            return {"webhooks": []}
        try:
            raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return {"webhooks": []}
        if not isinstance(raw, dict):
            return {"webhooks": []}
        raw_dict = cast(dict[str, Any], raw)
        webhooks = raw_dict.get("webhooks")
        if not isinstance(webhooks, list):
            return {"webhooks": []}

        normalized: list[dict[str, Any]] = []
        for item in cast(list[Any], webhooks):
            if isinstance(item, dict):
                normalized.append(cast(dict[str, Any], item))
        return {"webhooks": normalized}

    def _write(self, payload: dict[str, list[dict[str, Any]]]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list(self) -> list[WebhookRecord]:
        with self._lock:
            payload = self._read()
            rows = payload.get("webhooks", [])
            records: list[WebhookRecord] = []
            for row in rows:
                try:
                    records.append(WebhookRecord.model_validate(row))
                except Exception:
                    continue
            return records

    def get(self, webhook_id: str) -> WebhookRecord | None:
        for record in self.list():
            if record.webhook_id == webhook_id:
                return record
        return None

    def save(self, record: WebhookRecord) -> None:
        with self._lock:
            payload = self._read()
            rows = payload.get("webhooks", [])
            rows = [row for row in rows if row.get("webhook_id") != record.webhook_id]
            rows.append(record.model_dump())
            payload["webhooks"] = rows
            self._write(payload)

    def delete(self, webhook_id: str) -> bool:
        with self._lock:
            payload = self._read()
            rows = payload.get("webhooks", [])
            kept = [row for row in rows if row.get("webhook_id") != webhook_id]
            deleted = len(kept) != len(rows)
            payload["webhooks"] = kept
            self._write(payload)
            return deleted


_registry = _WebhookRegistry(WEBHOOKS_DB_PATH)
_dispatcher: DispatchCallable | None = None
_webhook_rate_limit_rpm = WEBHOOK_RATE_LIMIT_RPM
_rate_limit_lock = Lock()
_rate_buckets: dict[str, list[float]] = {}


def set_dispatcher(dispatcher: DispatchCallable | None) -> None:
    global _dispatcher
    _dispatcher = dispatcher


def configure_webhooks(storage_path: Path | None = None, secret: str | None = None) -> None:
    global _registry, _webhook_secret
    if storage_path is not None:
        _registry = _WebhookRegistry(storage_path)
    if secret is not None:
        _webhook_secret = secret


def configure_webhook_limits(rate_limit_rpm: int | None = None) -> None:
    global _webhook_rate_limit_rpm
    if rate_limit_rpm is not None:
        _webhook_rate_limit_rpm = rate_limit_rpm
    with _rate_limit_lock:
        _rate_buckets.clear()


def _valid_agent_ids() -> set[str]:
    ids = set(ALL_AGENT_DEFINITIONS.keys())
    ids.add("knowledge_agent")
    return ids


def _signature_ok(raw_body: bytes, signature_header: str, secret: str) -> bool:
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.strip()
    if provided.startswith("sha256="):
        provided = provided[len("sha256=") :]
    return hmac.compare_digest(provided, expected)


def _render_message(template: str, payload: dict[str, Any]) -> str:
    try:
        rendered = template.format(**payload)
        if rendered.strip():
            return rendered
    except Exception:
        pass
    return f"{template}\n\nPayload: {json.dumps(payload, ensure_ascii=False)}"


def _enforce_rate_limit(webhook_id: str) -> None:
    if _webhook_rate_limit_rpm <= 0:
        return

    now = time.time()
    with _rate_limit_lock:
        bucket = _rate_buckets.get(webhook_id, [])
        bucket = [entry for entry in bucket if now - entry < 60]
        if len(bucket) >= _webhook_rate_limit_rpm:
            raise HTTPException(status_code=429, detail="Webhook rate limit exceeded")
        bucket.append(now)
        _rate_buckets[webhook_id] = bucket


@router.post("/register")
async def register_webhook(body: WebhookRegisterRequest) -> WebhookRecord:
    if body.agent_id not in _valid_agent_ids():
        raise HTTPException(status_code=404, detail="Unknown agent_id")

    webhook_id = body.webhook_id or f"wh_{uuid.uuid4().hex[:12]}"
    if _registry.get(webhook_id):
        raise HTTPException(status_code=409, detail="webhook_id already exists")

    record = WebhookRecord(
        webhook_id=webhook_id,
        agent_id=body.agent_id,
        message_template=body.message_template,
        created_at=datetime.now(UTC).isoformat(),
    )
    _registry.save(record)
    logger.info(
        "Webhook registered",
        event_type="webhook_registered",
        webhook_id=record.webhook_id,
        agent_id=record.agent_id,
    )
    return record


@router.get("")
async def list_webhooks() -> list[WebhookRecord]:
    return _registry.list()


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str) -> dict[str, str]:
    deleted = _registry.delete(webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
    logger.info(
        "Webhook deleted",
        event_type="webhook_deleted",
        webhook_id=webhook_id,
    )
    return {"webhook_id": webhook_id, "status": "deleted"}


@router.post("/{webhook_id}")
async def receive_webhook(webhook_id: str, request: Request, dry_run: bool = False) -> dict[str, Any]:
    record = _registry.get(webhook_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Webhook not found")

    _enforce_rate_limit(webhook_id)

    if not _webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook secret is not configured")

    signature = request.headers.get("X-Agentop-Signature", "")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing X-Agentop-Signature")

    raw_body = await request.body()
    if not _signature_ok(raw_body=raw_body, signature_header=signature, secret=_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload: dict[str, Any] | Any = json.loads(raw_body.decode("utf-8")) if raw_body else {}
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook payload must be a JSON object")
    payload_obj = cast(dict[str, Any], payload)

    message = _render_message(record.message_template, payload_obj)
    context: dict[str, Any] = {
        "source": "webhook",
        "webhook_id": record.webhook_id,
        "payload": payload_obj,
    }

    logger.info(
        "Webhook payload accepted",
        event_type="webhook_received",
        webhook_id=record.webhook_id,
        agent_id=record.agent_id,
        dry_run=dry_run,
    )

    if dry_run:
        logger.info(
            "Webhook dry-run completed",
            event_type="webhook_dry_run",
            webhook_id=record.webhook_id,
            agent_id=record.agent_id,
        )
        return {
            "webhook_id": record.webhook_id,
            "agent_id": record.agent_id,
            "accepted": True,
            "dry_run": True,
            "rendered_message": message,
            "dispatch_result": None,
        }

    if _dispatcher is None:
        raise HTTPException(status_code=503, detail="Webhook dispatcher is not configured")

    result = await _dispatcher(record.agent_id, message, context)

    logger.info(
        "Webhook dispatched to orchestrator",
        event_type="webhook_dispatched",
        webhook_id=record.webhook_id,
        agent_id=record.agent_id,
    )

    return {
        "webhook_id": record.webhook_id,
        "agent_id": record.agent_id,
        "accepted": True,
        "dry_run": False,
        "dispatch_result": result,
    }
