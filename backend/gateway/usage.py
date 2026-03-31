"""
Usage Analytics — Per-key token and cost tracking in SQLite.
============================================================
Tables:
  gateway_usage_hourly   — rolled up per (key_id, model, hour)
  gateway_usage_daily    — rolled up per (key_id, model, day)

Alert thresholds:
  80% of daily/monthly quota → warning logged
  100% → request blocked by caller
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.gateway.auth import DB_PATH, _get_conn

_SCHEMA = """
CREATE TABLE IF NOT EXISTS gateway_usage_hourly (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    model       TEXT NOT NULL,
    provider    TEXT NOT NULL,
    hour_ts     TEXT NOT NULL,           -- ISO hour: 2026-03-04T14
    requests    INTEGER NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL    NOT NULL DEFAULT 0.0,
    errors      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(key_id, model, hour_ts)
);

CREATE TABLE IF NOT EXISTS gateway_usage_daily (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id      TEXT NOT NULL,
    model       TEXT NOT NULL,
    provider    TEXT NOT NULL,
    day_ts      TEXT NOT NULL,           -- ISO date: 2026-03-04
    requests    INTEGER NOT NULL DEFAULT 0,
    tokens_in   INTEGER NOT NULL DEFAULT 0,
    tokens_out  INTEGER NOT NULL DEFAULT 0,
    cost_usd    REAL    NOT NULL DEFAULT 0.0,
    errors      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(key_id, model, day_ts)
);

CREATE INDEX IF NOT EXISTS idx_usage_hourly_key ON gateway_usage_hourly(key_id, hour_ts);
CREATE INDEX IF NOT EXISTS idx_usage_daily_key  ON gateway_usage_daily(key_id, day_ts);
"""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class UsageSummary:
    key_id: str
    model: str
    provider: str
    period: str  # hour or day ISO string
    requests: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    errors: int


# ---------------------------------------------------------------------------
# UsageTracker
# ---------------------------------------------------------------------------


class UsageTracker:
    """Record and query per-key usage metrics."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self._conn = _get_conn(db_path)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # ---------------------------------------------------------------- Record

    def record(
        self,
        key_id: str,
        model: str,
        provider: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        error: bool = False,
    ) -> None:
        """Upsert usage into hourly and daily rollup tables."""
        now = datetime.now(UTC)
        hour_ts = now.strftime("%Y-%m-%dT%H")
        day_ts = now.strftime("%Y-%m-%d")
        err_count = 1 if error else 0

        for table, ts_col, ts_val in (
            ("gateway_usage_hourly", "hour_ts", hour_ts),
            ("gateway_usage_daily", "day_ts", day_ts),
        ):
            self._conn.execute(
                f"""INSERT INTO {table}
                    (key_id, model, provider, {ts_col}, requests, tokens_in, tokens_out, cost_usd, errors)
                    VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?)
                    ON CONFLICT(key_id, model, {ts_col}) DO UPDATE SET
                        requests  = requests  + 1,
                        tokens_in = tokens_in + excluded.tokens_in,
                        tokens_out= tokens_out+ excluded.tokens_out,
                        cost_usd  = cost_usd  + excluded.cost_usd,
                        errors    = errors    + excluded.errors""",
                (key_id, model, provider, ts_val, tokens_in, tokens_out, cost_usd, err_count),
            )
        self._conn.commit()

    # ---------------------------------------------------------------- Query

    def get_daily_usage(self, key_id: str, days: int = 30) -> list[UsageSummary]:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            """SELECT key_id, model, provider, day_ts, requests,
                      tokens_in, tokens_out, cost_usd, errors
               FROM gateway_usage_daily
               WHERE key_id = ? AND day_ts >= ?
               ORDER BY day_ts DESC""",
            (key_id, cutoff),
        ).fetchall()
        return [UsageSummary(*r) for r in rows]

    def get_today_cost(self, key_id: str) -> float:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM gateway_usage_daily WHERE key_id = ? AND day_ts = ?",
            (key_id, today),
        ).fetchone()
        return row[0] if row else 0.0

    def get_monthly_cost(self, key_id: str) -> float:
        month = datetime.now(UTC).strftime("%Y-%m")
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM gateway_usage_daily WHERE key_id = ? AND day_ts LIKE ?",
            (key_id, f"{month}-%"),
        ).fetchone()
        return row[0] if row else 0.0

    def get_today_tokens(self, key_id: str) -> tuple[int, int]:
        """Returns (tokens_in, tokens_out) for today."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        row = self._conn.execute(
            """SELECT COALESCE(SUM(tokens_in), 0), COALESCE(SUM(tokens_out), 0)
               FROM gateway_usage_daily WHERE key_id = ? AND day_ts = ?""",
            (key_id, today),
        ).fetchone()
        return (row[0], row[1]) if row else (0, 0)

    def check_quota(
        self,
        key_id: str,
        daily_usd_limit: float,
        monthly_usd_limit: float,
    ) -> tuple[bool, str]:
        """Returns (within_quota, reason). Emits warning at 80% threshold."""
        import logging

        logger = logging.getLogger("gateway.usage")

        daily_cost = self.get_today_cost(key_id)
        monthly_cost = self.get_monthly_cost(key_id)

        if monthly_usd_limit > 0:
            pct = monthly_cost / monthly_usd_limit
            if pct >= 1.0:
                return False, f"Monthly quota exceeded (${monthly_cost:.4f} / ${monthly_usd_limit:.2f})"
            if pct >= 0.8:
                logger.warning("Key %s at %.0f%% of monthly quota", key_id[:8], pct * 100)

        if daily_usd_limit > 0:
            pct = daily_cost / daily_usd_limit
            if pct >= 1.0:
                return False, f"Daily quota exceeded (${daily_cost:.4f} / ${daily_usd_limit:.2f})"
            if pct >= 0.8:
                logger.warning("Key %s at %.0f%% of daily quota", key_id[:8], pct * 100)

        return True, ""

    def top_models(self, key_id: str, days: int = 7) -> list[dict[str, Any]]:
        """Return top models by cost for *key_id* in the last *days* days."""
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        rows = self._conn.execute(
            """SELECT model, provider,
                      SUM(requests) as req,
                      SUM(tokens_in+tokens_out) as tokens,
                      SUM(cost_usd) as cost
               FROM gateway_usage_daily
               WHERE key_id = ? AND day_ts >= ?
               GROUP BY model, provider
               ORDER BY cost DESC LIMIT 10""",
            (key_id, cutoff),
        ).fetchall()
        return [
            {"model": r[0], "provider": r[1], "requests": r[2], "tokens": r[3], "cost_usd": round(r[4], 6)}
            for r in rows
        ]


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------

_tracker: UsageTracker | None = None


def get_usage_tracker() -> UsageTracker:
    global _tracker
    if _tracker is None:
        _tracker = UsageTracker()
    return _tracker
