"""
Actions store — SQLite persistence for proposed actions.

Mirrors backend/database/customer_store.py patterns: module-level singleton,
context-managed connections, WAL journaling. State transitions are enforced
at this layer; routes only translate HTTP → store calls.

See: docs/WEEK_2_SPRINT.md §A2.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from backend.models.actions import ActionSource, ActionStatus, ProposedAction

DEFAULT_DB_PATH = Path("data/agentop.db")


class ActionsStore:
    """SQLite storage for ``ProposedAction`` rows."""

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
                CREATE TABLE IF NOT EXISTS actions (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    action_type TEXT NOT NULL,
                    parameters_json TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    operator TEXT,
                    reason TEXT,
                    result_json TEXT,
                    executed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status);
                CREATE INDEX IF NOT EXISTS idx_actions_created ON actions(created_at DESC);

                PRAGMA journal_mode=WAL;
                """
            )
            conn.commit()

    # ---- writes -----------------------------------------------------------

    def insert(self, action: ProposedAction) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO actions
                (id, agent_id, action_type, parameters_json, summary, status, source,
                 created_at, operator, reason, result_json, executed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.id,
                    action.agent_id,
                    action.action_type,
                    json.dumps(action.parameters, default=str),
                    action.summary,
                    action.status.value,
                    action.source.value,
                    action.created_at.isoformat(),
                    action.operator,
                    action.reason,
                    json.dumps(action.result, default=str) if action.result is not None else None,
                    action.executed_at.isoformat() if action.executed_at else None,
                ),
            )
            conn.commit()

    def update(self, action: ProposedAction) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE actions
                   SET status = ?, operator = ?, reason = ?, result_json = ?, executed_at = ?
                 WHERE id = ?
                """,
                (
                    action.status.value,
                    action.operator,
                    action.reason,
                    json.dumps(action.result, default=str) if action.result is not None else None,
                    action.executed_at.isoformat() if action.executed_at else None,
                    action.id,
                ),
            )
            conn.commit()

    # ---- reads ------------------------------------------------------------

    def get(self, action_id: str) -> ProposedAction | None:
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        return _row_to_model(row) if row else None

    def list_by_status(self, status: ActionStatus, limit: int = 100) -> list[ProposedAction]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM actions WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status.value, int(limit)),
            ).fetchall()
        return [_row_to_model(r) for r in rows]


def _row_to_model(row: sqlite3.Row) -> ProposedAction:
    result_raw = row["result_json"]
    return ProposedAction(
        id=row["id"],
        agent_id=row["agent_id"],
        action_type=row["action_type"],
        parameters=json.loads(row["parameters_json"]) if row["parameters_json"] else {},
        summary=row["summary"] or "",
        status=ActionStatus(row["status"]),
        source=ActionSource(row["source"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        operator=row["operator"],
        reason=row["reason"],
        result=json.loads(result_raw) if result_raw else None,
        executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
    )


# Module-level singleton — overridable in tests via reset_default_store().
actions_store = ActionsStore()


def reset_default_store(db_path: Path) -> ActionsStore:
    """Test helper — swap the module-level singleton to a temp database."""
    global actions_store
    actions_store = ActionsStore(db_path=db_path)
    return actions_store
