"""
Task Tracker — Centralised task/activity log for the Agentop cluster.
=====================================================================
Every agent action, tool execution, and orchestrator event is recorded
as a Task with status tracking. The dashboard polls these for the
live Task Activity Panel.

Also provides a Server-Sent Events (SSE) bus for real-time live preview
of agent activity. Subscribers receive events as they happen.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from datetime import datetime
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
        self.timestamp = datetime.utcnow().isoformat()

    def to_sse(self) -> str:
        """Format as an SSE message string."""
        payload = {**self.data, "timestamp": self.timestamp}
        return f"event: {self.event_type}\ndata: {json.dumps(payload, default=str)}\n\n"


class TaskTracker:
    """Thread-safe in-memory task log with bounded size + SSE event bus."""

    MAX_TASKS = 500  # Rolling window — oldest tasks evicted

    def __init__(self) -> None:
        self._tasks: deque[dict[str, Any]] = deque(maxlen=self.MAX_TASKS)
        self._lock = threading.Lock()
        self._counter = 0
        # SSE subscriber queues (asyncio.Queue per subscriber)
        self._subscribers: list[asyncio.Queue[ActivityEvent]] = []
        self._sub_lock = threading.Lock()

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
            dead: list[asyncio.Queue] = []
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
                "created_at": datetime.utcnow().isoformat(),
                "started_at": None,
                "completed_at": None,
                "duration_ms": None,
                "error": None,
            }
            if status == TaskStatus.RUNNING:
                task["started_at"] = task["created_at"]
            self._tasks.append(task)

        # Broadcast to SSE subscribers
        self._broadcast(ActivityEvent("task_created", {
            "task_id": task_id, "agent_id": agent_id,
            "action": action, "detail": detail[:200], "status": status,
        }))
        return task_id

    def start_task(self, task_id: str) -> None:
        """Mark a task as RUNNING."""
        with self._lock:
            task = self._find(task_id)
            if task:
                task["status"] = TaskStatus.RUNNING
                task["started_at"] = datetime.utcnow().isoformat()
        self._broadcast(ActivityEvent("task_started", {"task_id": task_id}))

    def complete_task(self, task_id: str, detail: str | None = None) -> None:
        """Mark a task as COMPLETED."""
        duration_ms = None
        agent_id = ""
        with self._lock:
            task = self._find(task_id)
            if task:
                now = datetime.utcnow()
                task["status"] = TaskStatus.COMPLETED
                task["completed_at"] = now.isoformat()
                agent_id = task.get("agent_id", "")
                if detail:
                    task["detail"] = detail
                if task.get("started_at"):
                    started = datetime.fromisoformat(task["started_at"])
                    task["duration_ms"] = int((now - started).total_seconds() * 1000)
                    duration_ms = task["duration_ms"]

        self._broadcast(ActivityEvent("task_completed", {
            "task_id": task_id, "agent_id": agent_id,
            "detail": (detail or "")[:200], "duration_ms": duration_ms,
        }))

    def fail_task(self, task_id: str, error: str) -> None:
        """Mark a task as FAILED."""
        agent_id = ""
        with self._lock:
            task = self._find(task_id)
            if task:
                now = datetime.utcnow()
                task["status"] = TaskStatus.FAILED
                task["completed_at"] = now.isoformat()
                task["error"] = error
                agent_id = task.get("agent_id", "")
                if task.get("started_at"):
                    started = datetime.fromisoformat(task["started_at"])
                    task["duration_ms"] = int((now - started).total_seconds() * 1000)

        self._broadcast(ActivityEvent("task_failed", {
            "task_id": task_id, "agent_id": agent_id, "error": error[:200],
        }))

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


# Module-level singleton
task_tracker = TaskTracker()
