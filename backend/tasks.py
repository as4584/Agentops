"""
Task Tracker — Centralised task/activity log for the Agentop cluster.
=====================================================================
Every agent action, tool execution, and orchestrator event is recorded
as a Task with status tracking. The dashboard polls these for the
live Task Activity Panel.

Also provides a Server-Sent Events (SSE) bus for real-time live preview
of agent activity. Subscribers receive events as they happen.

Sprint 2 (PR 4): SQLite durability layer.  Tasks are persisted to SQLite
so the recent task window survives process restarts.  The in-memory deque
is still the primary read path (fast, bounded); SQLite provides the
durable tail of the last MAX_PERSISTED_TASKS tasks.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections import deque
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timezone

# UTC timezone compatibility (Python 3.10 and earlier)
UTC = timezone.utc
from pathlib import Path
from typing import Any


class TaskStatus:
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ActivityEvent:
    """A lightweight event pushed to SSE subscribers."""

    __slots__ = ("event_type", "data", "timestamp")

    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.event_type = event_type
        self.data = data
        self.timestamp = datetime.now(UTC).isoformat()

    def to_sse(self) -> str:
        """Format as an SSE message string."""
        payload: dict[str, Any] = {**self.data, "timestamp": self.timestamp}
        return f"event: {self.event_type}\ndata: {json.dumps(payload, default=str)}\n\n"


class TaskTracker:
    """Thread-safe in-memory task log with bounded size + SSE event bus.

    Sprint 2: SQLite durability — completed/failed tasks are persisted so the
    recent task window survives restarts.  The in-memory deque is seeded from
    SQLite on init so the dashboard sees recent history immediately after restart.
    """

    MAX_TASKS = 500  # Rolling window — oldest tasks evicted
    MAX_PERSISTED_TASKS = 200  # Tasks flushed to SQLite (newest-first)

    # Default DB path — override in tests by passing db_path to __init__.
    _DEFAULT_DB_PATH: Path = Path("data") / "tasks.db"

    def __init__(self, db_path: Path | None = None) -> None:
        self._tasks: deque[dict[str, Any]] = deque(maxlen=self.MAX_TASKS)
        self._lock = threading.Lock()
        self._counter = 0
        # SSE subscriber queues (asyncio.Queue per subscriber)
        self._subscribers: list[asyncio.Queue[ActivityEvent]] = []
        self._sub_lock = threading.Lock()
        # SQLite durability
        self._db_path: Path = db_path if db_path is not None else self._DEFAULT_DB_PATH
        self._init_db()
        self._load_from_db()

    # ----- SQLite Durability -----

    @contextmanager
    def _db_conn(self) -> Generator[sqlite3.Connection, None, None]:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create the tasks, conversations, and messages tables if they do not exist."""
        with self._db_conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL DEFAULT '',
                    detail TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'QUEUED',
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    duration_ms INTEGER,
                    error TEXT,
                    raw_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks (created_at DESC)")

            # Conversation durability — persists chat threads across restarts
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_agent ON conversations (agent_id, updated_at DESC)"
            )

            # Message log — append-only per conversation
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
                    run_id TEXT,
                    role TEXT NOT NULL DEFAULT 'user',
                    content TEXT NOT NULL DEFAULT '',
                    agent_id TEXT NOT NULL DEFAULT '',
                    timestamp TEXT NOT NULL,
                    ordo_trace_json TEXT,
                    message_meta_json TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages (conversation_id, timestamp ASC)"
            )
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "message_meta_json" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN message_meta_json TEXT")

    def _load_from_db(self) -> None:
        """Seed the in-memory deque with the most recent tasks from SQLite."""
        try:
            with self._db_conn() as conn:
                rows = conn.execute(
                    "SELECT raw_json FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (self.MAX_PERSISTED_TASKS,),
                ).fetchall()
            # Rows are newest-first; reverse so the deque is oldest-first.
            for row in reversed(rows):
                try:
                    task = json.loads(row["raw_json"])
                    self._tasks.append(task)
                    # Sync counter so new task IDs don't collide.
                    seq = task.get("id", "").replace("task_", "")
                    if seq.isdigit():
                        self._counter = max(self._counter, int(seq))
                except Exception:
                    pass
        except Exception:
            pass  # DB not accessible — start with empty in-memory store

    def _persist_task(self, task: dict[str, Any]) -> None:
        """Upsert a task to SQLite (best-effort — never raises)."""
        try:
            with self._db_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO tasks
                        (id, agent_id, action, detail, status, created_at,
                         started_at, completed_at, duration_ms, error, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        status=excluded.status,
                        started_at=excluded.started_at,
                        completed_at=excluded.completed_at,
                        duration_ms=excluded.duration_ms,
                        error=excluded.error,
                        raw_json=excluded.raw_json
                    """,
                    (
                        task["id"],
                        task.get("agent_id", ""),
                        task.get("action", ""),
                        task.get("detail", "")[:500],
                        task.get("status", "QUEUED"),
                        task.get("created_at", ""),
                        task.get("started_at"),
                        task.get("completed_at"),
                        task.get("duration_ms"),
                        task.get("error"),
                        json.dumps(task, default=str),
                    ),
                )
            # Prune oldest rows beyond MAX_PERSISTED_TASKS
            with self._db_conn() as conn:
                conn.execute(
                    """
                    DELETE FROM tasks WHERE id NOT IN (
                        SELECT id FROM tasks ORDER BY created_at DESC LIMIT ?
                    )
                    """,
                    (self.MAX_PERSISTED_TASKS,),
                )
        except Exception:
            pass  # Persistence is best-effort; never break the runtime path

    # ----- SSE Subscription -----

    def subscribe(self) -> asyncio.Queue[ActivityEvent]:
        """Register a new SSE subscriber and return their event queue."""
        q: asyncio.Queue[ActivityEvent] = asyncio.Queue(maxsize=200)
        with self._sub_lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[ActivityEvent]) -> None:
        """Remove a subscriber queue."""
        with self._sub_lock:
            try:
                self._subscribers.remove(q)
            except ValueError:
                pass

    def _broadcast(self, event: ActivityEvent) -> None:
        """Push an event to all subscribers (non-blocking)."""
        with self._sub_lock:
            dead: list[asyncio.Queue[ActivityEvent]] = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.append(q)  # drop slow subscribers
            for d in dead:
                try:
                    self._subscribers.remove(d)
                except ValueError:
                    pass

    # ----- Task CRUD -----

    def create_task(
        self,
        agent_id: str,
        action: str,
        detail: str = "",
        status: str = TaskStatus.QUEUED,
    ) -> str:
        """Create a new task entry and return its ID."""
        with self._lock:
            self._counter += 1
            task_id = f"task_{self._counter}"
            task: dict[str, Any] = {
                "id": task_id,
                "agent_id": agent_id,
                "action": action,
                "detail": detail,
                "status": status,
                "created_at": datetime.now(UTC).isoformat(),
                "started_at": None,
                "completed_at": None,
                "duration_ms": None,
                "error": None,
            }
            if status == TaskStatus.RUNNING:
                task["started_at"] = task["created_at"]
            self._tasks.append(task)

        self._persist_task(task)
        # Broadcast to SSE subscribers
        self._broadcast(
            ActivityEvent(
                "task_created",
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "action": action,
                    "detail": detail[:200],
                    "status": status,
                },
            )
        )
        return task_id

    def start_task(self, task_id: str) -> None:
        """Mark a task as RUNNING."""
        with self._lock:
            task = self._find(task_id)
            if task:
                task["status"] = TaskStatus.RUNNING
                task["started_at"] = datetime.now(UTC).isoformat()
        self._broadcast(ActivityEvent("task_started", {"task_id": task_id}))

    def complete_task(self, task_id: str, detail: str | None = None) -> None:
        """Mark a task as COMPLETED."""
        duration_ms = None
        agent_id = ""
        task_snapshot: dict[str, Any] | None = None
        with self._lock:
            task = self._find(task_id)
            if task:
                now = datetime.now(UTC)
                task["status"] = TaskStatus.COMPLETED
                task["completed_at"] = now.isoformat()
                agent_id = task.get("agent_id", "")
                if detail:
                    task["detail"] = detail
                if task.get("started_at"):
                    started = datetime.fromisoformat(task["started_at"])
                    task["duration_ms"] = int((now - started).total_seconds() * 1000)
                    duration_ms = task["duration_ms"]
                task_snapshot = dict(task)

        if task_snapshot:
            self._persist_task(task_snapshot)
        self._broadcast(
            ActivityEvent(
                "task_completed",
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "detail": (detail or "")[:200],
                    "duration_ms": duration_ms,
                },
            )
        )

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as FAILED."""
        agent_id = ""
        task_snapshot: dict[str, Any] | None = None
        with self._lock:
            task = self._find(task_id)
            if task:
                now = datetime.now(UTC)
                task["status"] = TaskStatus.FAILED
                task["completed_at"] = now.isoformat()
                task["error"] = error
                agent_id = task.get("agent_id", "")
                if task.get("started_at"):
                    started = datetime.fromisoformat(task["started_at"])
                    task["duration_ms"] = int((now - started).total_seconds() * 1000)
                task_snapshot = dict(task)

        if task_snapshot:
            self._persist_task(task_snapshot)
        self._broadcast(
            ActivityEvent(
                "task_failed",
                {
                    "task_id": task_id,
                    "agent_id": agent_id,
                    "error": error[:200],
                },
            )
        )

    # ----- Custom activity events (non-task) -----

    def emit_activity(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an arbitrary activity event to SSE subscribers (e.g. tool_call, llm_request)."""
        self._broadcast(ActivityEvent(event_type, data))

    # ----- Query -----

    def get_tasks(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        """Return recent tasks, newest first."""
        with self._lock:
            tasks = list(self._tasks)
            if status:
                tasks = [t for t in tasks if t["status"] == status]
            return list(reversed(tasks[-limit:]))

    def get_stats(self) -> dict[str, int]:
        """Return task count by status."""
        with self._lock:
            stats: dict[str, int] = {
                "total": len(self._tasks),
                "queued": 0,
                "running": 0,
                "completed": 0,
                "failed": 0,
            }
            for task in self._tasks:
                key = task["status"].lower()
                stats[key] = stats.get(key, 0) + 1
            return stats

    def _find(self, task_id: str) -> dict[str, Any] | None:
        """Find a task by ID (must be called with lock held)."""
        for task in reversed(self._tasks):
            if task["id"] == task_id:
                return task
        return None

    # ----- Conversation / Message Durability -----

    def create_or_attach_conversation(
        self,
        agent_id: str,
        conversation_id: str | None = None,
    ) -> str:
        """Return conversation_id — creates a new row if conversation_id is None or unknown."""
        import uuid as _uuid

        now = datetime.now(UTC).isoformat()
        if conversation_id:
            # Check if it already exists
            try:
                with self._db_conn() as conn:
                    row = conn.execute(
                        "SELECT conversation_id FROM conversations WHERE conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    if row:
                        # Touch updated_at
                        conn.execute(
                            "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                            (now, conversation_id),
                        )
                        return conversation_id
            except Exception:
                pass

        # Create a new conversation
        new_id = conversation_id or f"conv_{_uuid.uuid4().hex[:12]}"
        try:
            with self._db_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO conversations (conversation_id, agent_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                    (new_id, agent_id, now, now),
                )
        except Exception:
            pass
        return new_id

    def append_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        agent_id: str = "",
        run_id: str | None = None,
        ordo_trace: dict[str, Any] | None = None,
        message_meta: dict[str, Any] | None = None,
    ) -> str:
        """Persist a message and return its stable message_id."""
        import uuid as _uuid

        message_id = f"msg_{_uuid.uuid4().hex[:16]}"
        timestamp = datetime.now(UTC).isoformat()
        ordo_json = json.dumps(ordo_trace) if ordo_trace else None
        meta_json = json.dumps(message_meta) if message_meta else None
        try:
            with self._db_conn() as conn:
                conn.execute(
                    """
                    INSERT INTO messages
                        (
                            message_id,
                            conversation_id,
                            run_id,
                            role,
                            content,
                            agent_id,
                            timestamp,
                            ordo_trace_json,
                            message_meta_json
                        )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message_id,
                        conversation_id,
                        run_id,
                        role,
                        content,
                        agent_id,
                        timestamp,
                        ordo_json,
                        meta_json,
                    ),
                )
                conn.execute(
                    "UPDATE conversations SET updated_at = ? WHERE conversation_id = ?",
                    (timestamp, conversation_id),
                )
        except Exception:
            pass
        return message_id

    def get_messages(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return messages for a conversation oldest-first, up to *limit*."""
        try:
            with self._db_conn() as conn:
                rows = conn.execute(
                    """
                    SELECT message_id, conversation_id, run_id, role, content,
                           agent_id, timestamp, ordo_trace_json, message_meta_json
                    FROM messages
                    WHERE conversation_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
            result = []
            for row in rows:
                entry: dict[str, Any] = dict(row)
                if entry.get("ordo_trace_json"):
                    try:
                        entry["ordo_trace"] = json.loads(entry["ordo_trace_json"])
                    except Exception:
                        entry["ordo_trace"] = None
                if entry.get("message_meta_json"):
                    try:
                        meta = json.loads(entry["message_meta_json"])
                        if isinstance(meta, dict):
                            entry.update(meta)
                    except Exception:
                        pass
                del entry["ordo_trace_json"]
                del entry["message_meta_json"]
                result.append(entry)
            return result
        except Exception:
            return []

    def get_active_conversation(self, agent_id: str) -> dict[str, Any] | None:
        """Return the most recently updated conversation for *agent_id*, or None."""
        try:
            with self._db_conn() as conn:
                row = conn.execute(
                    """
                    SELECT conversation_id, agent_id, created_at, updated_at
                    FROM conversations
                    WHERE agent_id = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """,
                    (agent_id,),
                ).fetchone()
            return dict(row) if row else None
        except Exception:
            return None


# Module-level singleton
task_tracker = TaskTracker()
