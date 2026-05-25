"""
Audit store — append-only audit log for the approval loop.

Every proposed action, approval, rejection, and execution result writes
exactly one row here. The log is queryable but never mutable in place.

See: docs/WEEK_2_SPRINT.md §A3.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.models.actions import ActionAuditRow, ActionSource

DEFAULT_DB_PATH = Path("data/agentop.db")


class AuditStore:
    """SQLite-backed append-only audit log."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    operator TEXT,
                    agent_id TEXT,
                    action_type TEXT,
                    payload_json TEXT NOT NULL,
                    result_json TEXT,
                    ip TEXT,
                    source TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_audit_operator ON audit_log(operator);
                CREATE INDEX IF NOT EXISTS idx_audit_source ON audit_log(source);

                PRAGMA journal_mode=WAL;
                """
            )
            conn.commit()

    # ---- writes -----------------------------------------------------------

    def write(
        self,
        *,
        operator: str | None,
        agent_id: str | None,
        action_type: str | None,
        payload: dict[str, Any],
        result: dict[str, Any] | None = None,
        ip: str | None = None,
        source: ActionSource | str = ActionSource.WEB,
    ) -> ActionAuditRow:
        """Append a single audit row. Returns the row written."""
        row = ActionAuditRow(
            operator=operator,
            agent_id=agent_id,
            action_type=action_type,
            payload_json=payload,
            result_json=result,
            ip=ip,
            source=ActionSource(source) if isinstance(source, str) else source,
        )
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO audit_log
                (id, ts, operator, agent_id, action_type, payload_json, result_json, ip, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.id,
                    row.ts.isoformat(),
                    row.operator,
                    row.agent_id,
                    row.action_type,
                    json.dumps(row.payload_json, default=str),
                    json.dumps(row.result_json, default=str) if row.result_json is not None else None,
                    row.ip,
                    row.source.value,
                ),
            )
            conn.commit()
        return row

    # ---- reads ------------------------------------------------------------

    def query(
        self,
        *,
        limit: int = 100,
        since: datetime | None = None,
        operator: str | None = None,
        source: ActionSource | str | None = None,
    ) -> list[ActionAuditRow]:
        """Paginated read. Newest first."""
        sql = "SELECT * FROM audit_log WHERE 1=1"
        params: list[Any] = []
        if since is not None:
            sql += " AND ts >= ?"
            params.append(since.isoformat())
        if operator is not None:
            sql += " AND operator = ?"
            params.append(operator)
        if source is not None:
            sql += " AND source = ?"
            params.append(source.value if isinstance(source, ActionSource) else source)
        sql += " ORDER BY ts DESC LIMIT ?"
        params.append(int(limit))

        with self.connection() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [_row_to_model(r) for r in rows]


def _row_to_model(row: sqlite3.Row) -> ActionAuditRow:
    return ActionAuditRow(
        id=row["id"],
        ts=datetime.fromisoformat(row["ts"]),
        operator=row["operator"],
        agent_id=row["agent_id"],
        action_type=row["action_type"],
        payload_json=json.loads(row["payload_json"]) if row["payload_json"] else {},
        result_json=json.loads(row["result_json"]) if row["result_json"] else None,
        ip=row["ip"],
        source=ActionSource(row["source"]),
    )


# Module-level singleton (mirrors customer_store.py pattern).
audit_store = AuditStore()


def reset_default_store(db_path: Path) -> AuditStore:
    """Test helper — swap the module-level singleton to a temp database."""
    global audit_store
    audit_store = AuditStore(db_path=db_path)
    return audit_store
