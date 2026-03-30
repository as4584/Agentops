"""
ToolHealthMonitor — per-tool failure tracking persisted via MemoryStore.

Tracks call counts and failure records for every tool in the system.
Records are stored in the 'tool_health' memory namespace shared across all
agents so failure patterns are visible system-wide.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any

_HEALTH_NS = "tool_health"
_FAILURE_KEY = "failure_log"
_CALLS_KEY = "call_log"

# Sliding window (seconds) used to detect chronic failures
_CHRONIC_WINDOW = 3600  # 1 hour
_CHRONIC_THRESHOLD = 3  # failures within the window = chronic


@dataclass
class ToolFailureRecord:
    """A single recorded tool failure."""

    tool_name: str
    agent_id: str
    error: str
    kwargs: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    attempt: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ToolFailureRecord":
        return cls(
            tool_name=d["tool_name"],
            agent_id=d["agent_id"],
            error=d["error"],
            kwargs=d.get("kwargs", {}),
            timestamp=d.get("timestamp", 0.0),
            attempt=d.get("attempt", 1),
        )


_SKILL_KEY = "skill_selection_log"


@dataclass
class ToolHealthStats:
    """Aggregated health statistics for a single tool."""

    tool_name: str
    total_calls: int = 0
    total_failures: int = 0
    failure_rate: float = 0.0
    last_error: str | None = None
    is_chronic: bool = False
    recent_failures: list[ToolFailureRecord] = field(default_factory=list)
    # OpenSpace-inspired: skill selection vs. application tracking
    selected_count: int = 0   # times this skill was chosen by the router
    applied_count: int = 0    # times it was actually executed/completed
    fallback_rate: float = 0.0  # (selected - applied) / selected — canary for stale skills


class ToolHealthMonitor:
    """
    Tracks per-tool call counts and failure records, persisted in MemoryStore
    under the 'tool_health' namespace so stats survive agent restarts.

    Usage::

        monitor = ToolHealthMonitor(memory_store)

        # Record every call
        monitor.record_call("safe_shell")

        # Record a failure
        monitor.record_failure("safe_shell", "devops_agent", "exit code 127", kwargs={...})

        # Query health
        stats = monitor.get_stats("safe_shell")
        if stats.is_chronic:
            # route to self_healer_agent
    """

    def __init__(self, memory_store: Any) -> None:
        self._store = memory_store

    # ── internal storage helpers ─────────────────────────────────────────────

    def _read_failures(self) -> list[dict]:
        raw = self._store.read(_HEALTH_NS, _FAILURE_KEY)
        return raw if isinstance(raw, list) else []

    def _write_failures(self, records: list[dict]) -> None:
        # Cap at 2000 entries to prevent unbounded growth
        self._store.write(_HEALTH_NS, _FAILURE_KEY, records[-2000:])

    def _read_calls(self) -> dict[str, int]:
        raw = self._store.read(_HEALTH_NS, _CALLS_KEY)
        return raw if isinstance(raw, dict) else {}

    def _write_calls(self, calls: dict[str, int]) -> None:
        self._store.write(_HEALTH_NS, _CALLS_KEY, calls)

    # ── public API ───────────────────────────────────────────────────────────

    def record_call(self, tool_name: str) -> None:
        """Increment the call counter for a tool."""
        calls = self._read_calls()
        calls[tool_name] = calls.get(tool_name, 0) + 1
        self._write_calls(calls)

    def record_failure(
        self,
        tool_name: str,
        agent_id: str,
        error: str,
        kwargs: dict[str, Any] | None = None,
        attempt: int = 1,
    ) -> None:
        """Persist a failure record for a tool call."""
        # Sanitize kwargs values to prevent unbounded storage
        safe_kwargs = {k: str(v)[:300] for k, v in (kwargs or {}).items()}
        record = ToolFailureRecord(
            tool_name=tool_name,
            agent_id=agent_id,
            error=error[:500],
            kwargs=safe_kwargs,
            attempt=attempt,
        )
        failures = self._read_failures()
        failures.append(record.to_dict())
        self._write_failures(failures)

    def get_stats(self, tool_name: str) -> ToolHealthStats:
        """Return aggregated health statistics for a single tool."""
        calls = self._read_calls()
        all_failures = self._read_failures()

        tool_failures = [
            ToolFailureRecord.from_dict(f)
            for f in all_failures
            if f.get("tool_name") == tool_name
        ]

        total_calls = calls.get(tool_name, 0)
        total_failures = len(tool_failures)
        failure_rate = (total_failures / total_calls) if total_calls else 0.0

        now = time.time()
        recent = [f for f in tool_failures if now - f.timestamp <= _CHRONIC_WINDOW]
        is_chronic = len(recent) >= _CHRONIC_THRESHOLD

        return ToolHealthStats(
            tool_name=tool_name,
            total_calls=total_calls,
            total_failures=total_failures,
            failure_rate=failure_rate,
            last_error=tool_failures[-1].error if tool_failures else None,
            is_chronic=is_chronic,
            recent_failures=recent[-10:],  # last 10 only
        )

    def record_skill_selected(self, skill_id: str) -> None:
        """Record that a skill was selected (chosen by the routing layer)."""
        data = self._store.read(_HEALTH_NS, _SKILL_KEY) or {}
        entry = data.get(skill_id, {"selected": 0, "applied": 0})
        entry["selected"] += 1
        data[skill_id] = entry
        self._store.write(_HEALTH_NS, _SKILL_KEY, data)

    def record_skill_applied(self, skill_id: str) -> None:
        """Record that a skill was actually applied (not just selected)."""
        data = self._store.read(_HEALTH_NS, _SKILL_KEY) or {}
        entry = data.get(skill_id, {"selected": 0, "applied": 0})
        entry["applied"] += 1
        data[skill_id] = entry
        self._store.write(_HEALTH_NS, _SKILL_KEY, data)

    def get_skill_fallback_stats(self) -> dict[str, dict]:
        """Return selection/application counts and fallback_rate per skill."""
        data = self._store.read(_HEALTH_NS, _SKILL_KEY) or {}
        result = {}
        for skill_id, counts in data.items():
            sel = counts.get("selected", 0)
            app = counts.get("applied", 0)
            fallback = ((sel - app) / sel) if sel else 0.0
            result[skill_id] = {
                "selected_count": sel,
                "applied_count": app,
                "fallback_rate": round(fallback, 4),
            }
        return result

    def get_all_stats(self) -> dict[str, ToolHealthStats]:
        """Return health stats for every tool that has been called or failed."""
        calls = self._read_calls()
        failures = self._read_failures()
        all_tools: set[str] = set(calls.keys()) | {
            f.get("tool_name", "") for f in failures
        }
        return {t: self.get_stats(t) for t in all_tools if t}

    def build_health_report(self) -> str:
        """
        Return a Markdown-formatted tool health digest for prompt injection
        or dashboard display.
        """
        stats = self.get_all_stats()
        skill_stats = self.get_skill_fallback_stats()
        if not stats and not skill_stats:
            return ""

        lines = ["## Tool Health Report"]

        chronic = [s for s in stats.values() if s.is_chronic]
        degraded = [
            s for s in stats.values()
            if not s.is_chronic and s.total_failures > 0 and s.failure_rate >= 0.2
        ]

        if chronic:
            lines.append("\n### Chronic Failures (action required)")
            for s in sorted(chronic, key=lambda x: x.total_failures, reverse=True):
                lines.append(
                    f"- **{s.tool_name}**: {s.total_failures} failures in last hour — "
                    f"last error: `{s.last_error}`"
                )

        if degraded:
            lines.append("\n### Degraded Tools (elevated failure rate)")
            for s in sorted(degraded, key=lambda x: x.failure_rate, reverse=True):
                lines.append(
                    f"- `{s.tool_name}`: {s.failure_rate:.0%} failure rate "
                    f"({s.total_failures}/{s.total_calls} calls)"
                )

        high_fallback = [
            (sid, s) for sid, s in skill_stats.items() if s["fallback_rate"] >= 0.3
        ]
        if high_fallback:
            lines.append("\n### High Fallback Rate Skills (instructions may be stale)")
            for sid, s in sorted(high_fallback, key=lambda x: -x[1]["fallback_rate"]):
                lines.append(
                    f"- `{sid}`: {s['fallback_rate']:.0%} fallback "
                    f"({s['applied_count']}/{s['selected_count']} applied)"
                )

        if not chronic and not degraded and not high_fallback:
            lines.append("\nAll tracked tools are healthy.")

        return "\n".join(lines)
