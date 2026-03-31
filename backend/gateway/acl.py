"""
Model Access Control — Per-key model whitelist with wildcard support.
====================================================================
Design:
- Default DENY: a new key has no model access until explicitly granted.
- Whitelist entries support exact match or wildcard patterns.
  e.g. "ollama/*", "openrouter/kimi-*"
- Cost tiers: budget, standard, premium — can be mapped to key classes.
- ACL records are stored in the same SQLite DB as API keys.
"""

from __future__ import annotations

import fnmatch
import sqlite3
from pathlib import Path

from backend.gateway.auth import DB_PATH, _create_schema, _get_conn

# ---------------------------------------------------------------------------
# Model tier definitions
# ---------------------------------------------------------------------------


class ModelTier:
    BUDGET = "budget"
    STANDARD = "standard"
    PREMIUM = "premium"


TIER_MODELS: dict[str, list[str]] = {
    ModelTier.BUDGET: [
        "ollama/*",
        "llama3.2:1b",
        "llama3.2",
        "mistral:7b",
        "qwen2.5",
    ],
    ModelTier.STANDARD: [
        "openrouter/kimi-k2",
        "openrouter/claude-haiku-*",
        "openrouter/deepseek-*",
        "gpt-4o-mini",
    ],
    ModelTier.PREMIUM: [
        "openrouter/*",
        "gpt-4o",
        "gpt-4o-mini",
        "o1-preview",
        "claude-sonnet",
        "claude-opus",
        "anthropic/*",
    ],
}

# Convenience: all models allowed
WILDCARD_ALL = "*"


# ---------------------------------------------------------------------------
# Database schema for ACLs
# ---------------------------------------------------------------------------

_ACL_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_key_acl (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    pattern     TEXT NOT NULL,
    UNIQUE(key_id, pattern)
);
CREATE INDEX IF NOT EXISTS idx_acl_key_id ON gateway_key_acl(key_id);
"""


def _ensure_acl_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_ACL_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# ModelACL
# ---------------------------------------------------------------------------


class ModelACL:
    """Manage per-key model access control lists."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._conn = _get_conn(db_path)
        _create_schema(self._conn)
        _ensure_acl_schema(self._conn)

    # ---------------------------------------------------------------- Grant / Revoke

    def grant(self, key_id: str, patterns: list[str]) -> None:
        """Grant access to models matching *patterns* for *key_id*."""
        self._conn.executemany(
            "INSERT OR IGNORE INTO gateway_key_acl (key_id, pattern) VALUES (?, ?)",
            [(key_id, p) for p in patterns],
        )
        self._conn.commit()

    def grant_tier(self, key_id: str, tier: str) -> None:
        """Grant all patterns in a cost tier."""
        patterns = TIER_MODELS.get(tier, [])
        self.grant(key_id, patterns)

    def revoke(self, key_id: str, patterns: list[str]) -> None:
        """Revoke specific patterns."""
        self._conn.executemany(
            "DELETE FROM gateway_key_acl WHERE key_id = ? AND pattern = ?",
            [(key_id, p) for p in patterns],
        )
        self._conn.commit()

    def revoke_all(self, key_id: str) -> None:
        """Remove all ACL entries for a key."""
        self._conn.execute("DELETE FROM gateway_key_acl WHERE key_id = ?", (key_id,))
        self._conn.commit()

    # ---------------------------------------------------------------- Check

    def is_allowed(self, key_id: str, model_id: str) -> bool:
        """Return True if *key_id* is allowed to access *model_id*."""
        rows = self._conn.execute("SELECT pattern FROM gateway_key_acl WHERE key_id = ?", (key_id,)).fetchall()
        patterns = [r[0] for r in rows]
        return _matches_any(model_id, patterns)

    def get_allowed_patterns(self, key_id: str) -> list[str]:
        """Return all patterns granted to *key_id*."""
        rows = self._conn.execute(
            "SELECT pattern FROM gateway_key_acl WHERE key_id = ? ORDER BY pattern",
            (key_id,),
        ).fetchall()
        return [r[0] for r in rows]

    def filter_allowed_models(self, key_id: str, all_models: list[str]) -> list[str]:
        """Return the subset of *all_models* that *key_id* is allowed to use."""
        patterns = self.get_allowed_patterns(key_id)
        if not patterns:
            return []
        return [m for m in all_models if _matches_any(m, patterns)]


# ---------------------------------------------------------------------------
# Pattern matching helpers
# ---------------------------------------------------------------------------


def _matches_any(model_id: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern == WILDCARD_ALL:
            return True
        # Normalise: "ollama/llama3.2" or "llama3.2" both match entries
        if fnmatch.fnmatchcase(model_id, pattern):
            return True
        # Also try matching without provider prefix
        short = model_id.split("/", 1)[-1]
        if fnmatch.fnmatchcase(short, pattern):
            return True
    return False


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_acl: ModelACL | None = None


def get_acl() -> ModelACL:
    global _acl
    if _acl is None:
        _acl = ModelACL()
    return _acl
