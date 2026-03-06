"""
Audit Logger — Structured JSON audit trail for gateway requests.
================================================================
Logs per-request metadata WITHOUT capturing prompt/completion content.

Log fields:
  ts         ISO-8601 timestamp
  key_id     SHA-256 of key_id (not raw key) for correlation
  model      model identifier
  provider   provider name
  tokens_in  prompt tokens (count only)
  tokens_out completion tokens (count only)
  cost_usd   estimated cost
  latency_ms wall-clock latency in ms
  status     HTTP status code
  stream     true/false
  error      error type if any

Debug stream (GATEWAY_DEBUG_LOG_CONTENT=1) also logs raw content.
Never enable in production.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.config_gateway import (
    GATEWAY_AUDIT_LOG_PATH,
    GATEWAY_DEBUG_LOG_CONTENT,
)


# ---------------------------------------------------------------------------
# AuditEntry
# ---------------------------------------------------------------------------

@dataclass
class AuditEntry:
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    key_id_hash: str = ""   # SHA-256 of key_id — never raw key
    model: str = ""
    provider: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    status: int = 200
    stream: bool = False
    error: str = ""
    # Debug-only fields — empty unless GATEWAY_DEBUG_LOG_CONTENT=1
    _prompt_hash: str = ""   # SHA-256 of first user message (PII-safe ref)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop private debug fields in non-debug mode
        if not GATEWAY_DEBUG_LOG_CONTENT:
            d.pop("_prompt_hash", None)
        return {k: v for k, v in d.items() if not k.startswith("_") or GATEWAY_DEBUG_LOG_CONTENT}


# ---------------------------------------------------------------------------
# AuditLogger
# ---------------------------------------------------------------------------

class AuditLogger:
    """Append-only JSONL audit log for gateway requests."""

    def __init__(self, path: Path = GATEWAY_AUDIT_LOG_PATH) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry) -> None:
        """Append *entry* to the JSONL audit log."""
        line = json.dumps(entry.to_dict(), separators=(",", ":"))
        with open(self._path, "a") as f:
            f.write(line + "\n")

    def log_request(
        self,
        *,
        key_id: str,
        model: str,
        provider: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        status: int = 200,
        stream: bool = False,
        error: str = "",
        first_user_message: str = "",  # only hashed if debug mode
    ) -> None:
        entry = AuditEntry(
            key_id_hash=_hash_id(key_id),
            model=model,
            provider=provider,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            status=status,
            stream=stream,
            error=error,
        )
        if GATEWAY_DEBUG_LOG_CONTENT and first_user_message:
            entry._prompt_hash = hashlib.sha256(
                first_user_message.encode()
            ).hexdigest()[:16]
        self.log(entry)

    def tail(self, n: int = 100) -> list[dict[str, Any]]:
        """Return up to *n* most recent log entries."""
        if not self._path.exists():
            return []
        lines = self._path.read_text().splitlines()
        recent = lines[-n:]
        result = []
        for line in recent:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_id(key_id: str) -> str:
    """Stable anonymised key for correlation in logs."""
    return hashlib.sha256(key_id.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Timer context manager for latency measurement
# ---------------------------------------------------------------------------

class RequestTimer:
    """Context manager that records wall-clock latency in ms."""

    def __init__(self) -> None:
        self._start = 0.0
        self.elapsed_ms = 0

    def __enter__(self) -> "RequestTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.elapsed_ms = int((time.perf_counter() - self._start) * 1000)


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _logger
    if _logger is None:
        _logger = AuditLogger()
    return _logger
