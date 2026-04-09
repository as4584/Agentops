"""
Security Alerts API — serves pending alerts to the Discord bot poller.

The Discord bot (running in Kubernetes) polls GET /security/alerts/pending
every 30s. This endpoint returns undelivered alerts and marks them delivered.

Delivery flow:
  SecurityEventWatcher detects event → appends to security_alerts.json
  Discord bot polls /security/alerts/pending → delivers to #security channel
  Bot POSTs /security/alerts/ack → marks alerts delivered
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.auth import require_api_auth
from backend.config import PROJECT_ROOT

router = APIRouter(prefix="/security", tags=["security"], dependencies=[Depends(require_api_auth)])

_ALERTS_PATH = PROJECT_ROOT / "data" / "agents" / "security_agent" / "security_alerts.json"
_ALERTS_PATH.parent.mkdir(parents=True, exist_ok=True)


class AlertAckRequest(BaseModel):
    alert_ids: list[str]


def _read_alerts() -> list[dict]:
    if not _ALERTS_PATH.exists():
        return []
    try:
        data = json.loads(_ALERTS_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_alerts(alerts: list[dict]) -> None:
    _ALERTS_PATH.write_text(json.dumps(alerts[-500:], indent=2))


@router.get("/alerts/pending")
async def get_pending_alerts() -> dict[str, Any]:
    """
    Return all undelivered security alerts.
    Called by the Discord bot's polling loop every 30s.
    """
    alerts = _read_alerts()
    pending = [a for a in alerts if not a.get("delivered")]
    return {"alerts": pending, "count": len(pending)}


@router.post("/alerts/ack")
async def ack_alerts(req: AlertAckRequest) -> dict[str, Any]:
    """
    Mark alerts as delivered after the Discord bot sends them.
    """
    alerts = _read_alerts()
    acked = 0
    for alert in alerts:
        if alert.get("alert_id") in req.alert_ids:
            alert["delivered"] = True
            alert["delivered_at"] = datetime.now(tz=UTC).isoformat()
            acked += 1
    _write_alerts(alerts)
    return {"acked": acked}


@router.get("/alerts/all")
async def get_all_alerts(limit: int = 50) -> dict[str, Any]:
    """Return recent alerts (delivered + pending) for dashboard view."""
    alerts = _read_alerts()
    return {"alerts": alerts[-limit:], "total": len(alerts)}
