"""
API Key Management — HMAC-SHA256 gateway key generation and validation.
=======================================================================
Key format:  agp_{prefix}_{random_hex}
             e.g. agp_sk_a1b2c3d4_e5f6a7b8c9d0e1f2

Design decisions:
- Keys are hashed (SHA-256) before storage — raw key is never persisted.
- Timing-safe comparison via hmac.compare_digest().
- SQLite backend (no extra infra).
- Support for primary + secondary keys per client (rotation).
- RBAC via a permissions set per key.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.config import BACKEND_DIR

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PATH: Path = Path(BACKEND_DIR) / "memory" / "gateway_keys.db"
KEY_PREFIX = "agp"

# Available permission scopes
SCOPE_CHAT = "chat"
SCOPE_MODELS = "models"
SCOPE_ADMIN = "admin"
ALL_SCOPES = {SCOPE_CHAT, SCOPE_MODELS, SCOPE_ADMIN}
DEFAULT_SCOPES = {SCOPE_CHAT, SCOPE_MODELS}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class APIKey:
    key_id: str  # opaque stable ID (uuid-ish hex)
    name: str  # human label
    owner: str  # owner identifier (user / service)
    key_hash: str  # SHA-256(raw_key) — never the raw key
    key_prefix: str  # first 8 chars of raw key (for display / logs)
    created_at: float  # Unix timestamp
    expires_at: float  # Unix timestamp, 0 = no expiry
    disabled: bool
    scopes: set[str]  # permission scopes
    quota_rpm: int
    quota_tpm: int
    quota_tpd: int
    quota_daily_usd: float
    quota_monthly_usd: float
    # Secondary key hash for zero-downtime rotation (may be None)
    secondary_hash: str | None = None
    secondary_prefix: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _get_conn(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS gateway_keys (
            key_id           TEXT PRIMARY KEY,
            name             TEXT NOT NULL,
            owner            TEXT NOT NULL DEFAULT '',
            key_hash         TEXT NOT NULL UNIQUE,
            key_prefix       TEXT NOT NULL,
            secondary_hash   TEXT,
            secondary_prefix TEXT,
            created_at       REAL NOT NULL,
            expires_at       REAL NOT NULL DEFAULT 0,
            disabled         INTEGER NOT NULL DEFAULT 0,
            scopes           TEXT NOT NULL DEFAULT 'chat,models',
            quota_rpm        INTEGER NOT NULL DEFAULT 60,
            quota_tpm        INTEGER NOT NULL DEFAULT 100000,
            quota_tpd        INTEGER NOT NULL DEFAULT 1000000,
            quota_daily_usd  REAL NOT NULL DEFAULT 5.0,
            quota_monthly_usd REAL NOT NULL DEFAULT 50.0,
            metadata         TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_gateway_keys_hash
            ON gateway_keys(key_hash);
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def _hash_key(raw_key: str) -> str:
    """Return SHA-256 hex digest of raw_key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key(variant: str = "sk") -> tuple[str, str]:
    """Generate a new gateway API key.

    Returns (raw_key, key_prefix).
    raw_key format: agp_{variant}_{8hex}_{24hex}
    """
    part1 = secrets.token_hex(4)  # 8 hex chars
    part2 = secrets.token_hex(12)  # 24 hex chars
    raw_key = f"{KEY_PREFIX}_{variant}_{part1}_{part2}"
    prefix = f"{KEY_PREFIX}_{variant}_{part1}"  # first visible portion
    return raw_key, prefix


# ---------------------------------------------------------------------------
# APIKeyManager
# ---------------------------------------------------------------------------


class APIKeyManager:
    """Create, validate, and manage gateway API keys."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._conn = _get_conn(db_path)
        _create_schema(self._conn)

    # ---------------------------------------------------------------- CRUD

    def create_key(
        self,
        name: str,
        owner: str = "",
        scopes: set[str] | None = None,
        expires_in_days: int | None = None,
        quota_rpm: int = 60,
        quota_tpm: int = 100_000,
        quota_tpd: int = 1_000_000,
        quota_daily_usd: float = 5.0,
        quota_monthly_usd: float = 50.0,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, APIKey]:
        """Create a new API key.

        Returns (raw_key, APIKey).  Caller must deliver raw_key to the
        client once — it is *not* stored.
        """
        raw_key, prefix = generate_api_key()
        key_id = secrets.token_hex(16)
        key_hash = _hash_key(raw_key)
        now = time.time()
        expires_at = 0.0
        if expires_in_days:
            expires_at = now + expires_in_days * 86400

        active_scopes = scopes or DEFAULT_SCOPES
        api_key = APIKey(
            key_id=key_id,
            name=name,
            owner=owner,
            key_hash=key_hash,
            key_prefix=prefix,
            created_at=now,
            expires_at=expires_at,
            disabled=False,
            scopes=active_scopes,
            quota_rpm=quota_rpm,
            quota_tpm=quota_tpm,
            quota_tpd=quota_tpd,
            quota_daily_usd=quota_daily_usd,
            quota_monthly_usd=quota_monthly_usd,
            metadata=metadata or {},
        )
        self._insert(api_key)
        return raw_key, api_key

    def validate_key(self, raw_key: str) -> APIKey | None:
        """Validate *raw_key* and return its APIKey record, or None.

        Uses timing-safe comparison.  Does NOT raise on failure.
        """
        if not raw_key or not raw_key.startswith(KEY_PREFIX + "_"):
            return None
        candidate_hash = _hash_key(raw_key)
        row = self._conn.execute(
            "SELECT * FROM gateway_keys WHERE key_hash = ? OR secondary_hash = ?",
            (candidate_hash, candidate_hash),
        ).fetchone()
        if row is None:
            return None

        api_key = self._row_to_key(row)

        # Timing-safe compare (prevent oracle attacks)
        primary_ok = hmac.compare_digest(candidate_hash.encode(), api_key.key_hash.encode())
        secondary_ok = False
        if api_key.secondary_hash:
            secondary_ok = hmac.compare_digest(candidate_hash.encode(), api_key.secondary_hash.encode())
        if not (primary_ok or secondary_ok):
            return None

        if api_key.disabled:
            return None
        if api_key.expires_at and time.time() > api_key.expires_at:
            return None

        return api_key

    def get_by_id(self, key_id: str) -> APIKey | None:
        row = self._conn.execute("SELECT * FROM gateway_keys WHERE key_id = ?", (key_id,)).fetchone()
        return self._row_to_key(row) if row else None

    def list_keys(self) -> list[APIKey]:
        rows = self._conn.execute("SELECT * FROM gateway_keys ORDER BY created_at DESC").fetchall()
        return [self._row_to_key(r) for r in rows]

    def update_key(self, key_id: str, **kwargs: Any) -> bool:
        """Update mutable fields: name, owner, scopes, quotas, disabled, expires_at."""
        allowed = {
            "name",
            "owner",
            "scopes",
            "quota_rpm",
            "quota_tpm",
            "quota_tpd",
            "quota_daily_usd",
            "quota_monthly_usd",
            "disabled",
            "expires_at",
            "metadata",
        }
        updates: dict[str, Any] = {}
        for k, v in kwargs.items():
            if k not in allowed:
                continue
            if k == "scopes" and isinstance(v, (set, list)):
                updates[k] = ",".join(sorted(v))
            elif k == "metadata" and isinstance(v, dict):
                import json

                updates[k] = json.dumps(v)
            elif k == "disabled":
                updates[k] = int(bool(v))
            else:
                updates[k] = v

        if not updates:
            return False
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [key_id]
        self._conn.execute(f"UPDATE gateway_keys SET {cols} WHERE key_id = ?", vals)
        self._conn.commit()
        return True

    def revoke_key(self, key_id: str) -> bool:
        """Disable a key (soft delete)."""
        return self.update_key(key_id, disabled=True)

    def delete_key(self, key_id: str) -> bool:
        """Hard delete a key."""
        cur = self._conn.execute("DELETE FROM gateway_keys WHERE key_id = ?", (key_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def rotate_key(self, key_id: str) -> tuple[str, str] | None:
        """Generate a secondary key for zero-downtime rotation.

        Returns (new_raw_key, new_prefix) or None if key not found.
        Call promote_rotation() once the new key is deployed.
        """
        api_key = self.get_by_id(key_id)
        if not api_key:
            return None
        new_raw, new_prefix = generate_api_key()
        new_hash = _hash_key(new_raw)
        self._conn.execute(
            "UPDATE gateway_keys SET secondary_hash = ?, secondary_prefix = ? WHERE key_id = ?",
            (new_hash, new_prefix, key_id),
        )
        self._conn.commit()
        return new_raw, new_prefix

    def promote_rotation(self, key_id: str) -> bool:
        """Promote secondary key to primary, invalidating the old primary."""
        row = self._conn.execute("SELECT * FROM gateway_keys WHERE key_id = ?", (key_id,)).fetchone()
        if not row or not row["secondary_hash"]:
            return False
        self._conn.execute(
            """UPDATE gateway_keys
               SET key_hash = secondary_hash, key_prefix = secondary_prefix,
                   secondary_hash = NULL, secondary_prefix = NULL
               WHERE key_id = ?""",
            (key_id,),
        )
        self._conn.commit()
        return True

    # ---------------------------------------------------------------- Internal

    def _insert(self, key: APIKey) -> None:
        import json

        self._conn.execute(
            """INSERT INTO gateway_keys
               (key_id, name, owner, key_hash, key_prefix, secondary_hash, secondary_prefix,
                created_at, expires_at, disabled, scopes,
                quota_rpm, quota_tpm, quota_tpd, quota_daily_usd, quota_monthly_usd, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                key.key_id,
                key.name,
                key.owner,
                key.key_hash,
                key.key_prefix,
                key.secondary_hash,
                key.secondary_prefix,
                key.created_at,
                key.expires_at,
                int(key.disabled),
                ",".join(sorted(key.scopes)),
                key.quota_rpm,
                key.quota_tpm,
                key.quota_tpd,
                key.quota_daily_usd,
                key.quota_monthly_usd,
                json.dumps(key.metadata),
            ),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_key(row: sqlite3.Row) -> APIKey:
        import json

        return APIKey(
            key_id=row["key_id"],
            name=row["name"],
            owner=row["owner"],
            key_hash=row["key_hash"],
            key_prefix=row["key_prefix"],
            secondary_hash=row["secondary_hash"],
            secondary_prefix=row["secondary_prefix"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            disabled=bool(row["disabled"]),
            scopes=set(row["scopes"].split(",")) if row["scopes"] else set(),
            quota_rpm=row["quota_rpm"],
            quota_tpm=row["quota_tpm"],
            quota_tpd=row["quota_tpd"],
            quota_daily_usd=row["quota_daily_usd"],
            quota_monthly_usd=row["quota_monthly_usd"],
            metadata=json.loads(row["metadata"] or "{}"),
        )


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_manager: APIKeyManager | None = None


def get_key_manager() -> APIKeyManager:
    """Return module-level APIKeyManager singleton."""
    global _manager
    if _manager is None:
        _manager = APIKeyManager()
    return _manager
