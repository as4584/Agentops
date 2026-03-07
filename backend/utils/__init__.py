"""
Central Logger — Structured logging for all system events.
===========================================================
All agent actions, tool executions, drift events, and system events
are logged through this centralized logger. Provides both file and
in-memory log access for the dashboard.

Governance Note: INV-7 requires all tool executions to be logged.
This module is the enforcement point for that invariant.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from backend.config import LOG_DIR, LOG_LEVEL, MAX_LOG_ENTRIES
from backend.models import (
    ChangeImpactLevel,
    DriftEvent,
    ToolExecutionRecord,
)


class CentralLogger:
    """
    Thread-safe centralized logger for the Agentop system.

    Maintains:
    - Structured JSON log file on disk
    - In-memory ring buffer for dashboard access
    - Separate drift event tracking
    """

    _instance: CentralLogger | None = None
    _lock: Lock = Lock()

    def __new__(cls) -> CentralLogger:
        """Singleton pattern — one logger for the entire system."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # In-memory ring buffers for dashboard access
        self._tool_logs: deque[ToolExecutionRecord] = deque(maxlen=MAX_LOG_ENTRIES)
        self._drift_events: deque[DriftEvent] = deque(maxlen=MAX_LOG_ENTRIES)
        self._general_logs: deque[dict[str, Any]] = deque(maxlen=MAX_LOG_ENTRIES)
        self._write_lock = Lock()

        # File-based log
        self._log_file: Path = LOG_DIR / "system.jsonl"
        self._log_file.touch(exist_ok=True)

        # Standard Python logger for console output
        self._logger = logging.getLogger("agentop")
        self._logger.setLevel(getattr(logging, LOG_LEVEL))
        if not self._logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("[%(asctime)s] %(levelname)s — %(message)s")
            )
            self._logger.addHandler(handler)

    # ----- Tool Execution Logging (INV-7 enforcement) -----

    def log_tool_execution(self, record: ToolExecutionRecord) -> None:
        """
        Log a tool execution. This is MANDATORY for all tool calls (INV-7).
        Appends to both the in-memory buffer and the persistent log file.
        """
        with self._write_lock:
            self._tool_logs.append(record)
            self._write_to_file({
                "type": "TOOL_EXECUTION",
                "data": record.model_dump(mode="json"),
            })
        self._logger.info(
            f"TOOL [{record.tool_name}] by [{record.agent_id}] "
            f"type={record.modification_type} success={record.success}"
        )

    # ----- Drift Event Logging -----

    def log_drift_event(self, event: DriftEvent) -> None:
        """
        Log a drift event. CRITICAL_DRIFT_EVENTs are logged at ERROR level.
        """
        with self._write_lock:
            self._drift_events.append(event)
            self._write_to_file({
                "type": "DRIFT_EVENT",
                "data": event.model_dump(mode="json"),
            })
        if event.severity == ChangeImpactLevel.CRITICAL:
            self._logger.error(
                f"CRITICAL_DRIFT_EVENT: {event.invariant_id} — {event.description}"
            )
        else:
            self._logger.warning(
                f"DRIFT_EVENT: {event.invariant_id} — {event.description}"
            )

    # ----- General Logging -----

    def log(self, level: str, message: str, **kwargs: Any) -> None:
        """General-purpose structured log entry."""
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            **kwargs,
        }
        with self._write_lock:
            self._general_logs.append(entry)
            self._write_to_file({"type": "GENERAL", "data": entry})
        getattr(self._logger, level.lower(), self._logger.info)(message)

    def info(self, message: str, **kwargs: Any) -> None:
        self.log("INFO", message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        self.log("WARNING", message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        self.log("ERROR", message, **kwargs)

    # ----- Query Methods (for dashboard) -----

    def get_recent_tool_logs(self, limit: int = 50) -> list[ToolExecutionRecord]:
        """Return the most recent tool execution logs."""
        return list(self._tool_logs)[-limit:]

    def get_drift_events(self, limit: int = 50) -> list[DriftEvent]:
        """Return the most recent drift events."""
        return list(self._drift_events)[-limit:]

    def get_general_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return the most recent general log entries."""
        return list(self._general_logs)[-limit:]

    # ----- Internal -----

    def _write_to_file(self, entry: dict[str, Any]) -> None:
        """Append a JSON line to the persistent log file."""
        try:
            with open(self._log_file, "a") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as e:
            self._logger.error(f"Failed to write log to file: {e}")


# Module-level singleton accessor
logger = CentralLogger()
