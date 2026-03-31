"""
ExecutionRecorder — per-agent-run trajectory logging.

Writes one JSONL file per run to::

    data/agents/{agent_id}/runs/{run_id}.jsonl

Each line in the file is a JSON-serialised ToolCallEntry (one per tool call in
the run).  A final ``run_end`` sentinel line is appended when the run finishes.

The recorder keeps at most ``max_runs_per_agent`` files on disk, pruning the
oldest when the limit is exceeded.

Inspired by OpenSpace's conversations.jsonl + traj.jsonl pattern.
See docs/INSPIRATIONS.md for attribution.

Usage::

    recorder = ExecutionRecorder(base_dir=Path("data/agents"))

    run_id = recorder.start_run(agent_id="devops_agent", message="check CI")

    recorder.record_tool_call(
        run_id=run_id,
        agent_id="devops_agent",
        tool_name="safe_shell",
        kwargs={"command": "git status"},
        result={"stdout": "nothing to commit", "return_code": 0},
        duration_ms=42,
        failed=False,
    )

    recorder.end_run(run_id=run_id, agent_id="devops_agent", response="All good.")
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_MAX_RUNS_PER_AGENT = 10  # JSONL files to keep per agent (prune oldest)
_MAX_RESULT_CHARS = 2000  # truncate large tool results in the trace


@dataclass
class ToolCallEntry:
    """A single tool call recorded within a run."""

    run_id: str
    agent_id: str
    tool_name: str
    kwargs: dict[str, Any]
    result: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    duration_ms: float = 0.0
    failed: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["_type"] = "tool_call"
        return d


@dataclass
class RunRecord:
    """Metadata about a single agent run."""

    run_id: str
    agent_id: str
    message: str
    started_at: float = field(default_factory=time.time)
    ended_at: float | None = None
    response: str | None = None
    tool_call_count: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["_type"] = "run_end"
        return d


class ExecutionRecorder:
    """
    Records every tool call in an agent run to a JSONL file on disk.

    Files are written to ``{base_dir}/{agent_id}/runs/{run_id}.jsonl``.
    The directory is created on first write.  A lightweight in-memory
    registry tracks open runs (``_open_runs``).
    """

    def __init__(self, base_dir: Path | str = Path("data/agents")) -> None:
        self._base = Path(base_dir)
        self._open_runs: dict[str, RunRecord] = {}

    # ── path helpers ─────────────────────────────────────────────────────────

    def _runs_dir(self, agent_id: str) -> Path:
        return self._base / agent_id / "runs"

    def _run_path(self, agent_id: str, run_id: str) -> Path:
        return self._runs_dir(agent_id) / f"{run_id}.jsonl"

    # ── public API ───────────────────────────────────────────────────────────

    def start_run(self, agent_id: str, message: str) -> str:
        """
        Open a new run and return its ``run_id``.

        Creates the run directory if needed and writes a ``run_start``
        sentinel line to the file.
        """
        run_id = str(uuid.uuid4())[:12]
        record = RunRecord(run_id=run_id, agent_id=agent_id, message=message[:500])
        self._open_runs[run_id] = record

        runs_dir = self._runs_dir(agent_id)
        runs_dir.mkdir(parents=True, exist_ok=True)

        path = self._run_path(agent_id, run_id)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "_type": "run_start",
                        "run_id": run_id,
                        "agent_id": agent_id,
                        "message": message[:500],
                        "timestamp": record.started_at,
                    }
                )
                + "\n"
            )

        return run_id

    def record_tool_call(
        self,
        run_id: str,
        agent_id: str,
        tool_name: str,
        kwargs: dict[str, Any],
        result: dict[str, Any],
        duration_ms: float = 0.0,
        failed: bool = False,
        error: str | None = None,
    ) -> None:
        """Append one tool call entry to the run's JSONL file."""
        entry = ToolCallEntry(
            run_id=run_id,
            agent_id=agent_id,
            tool_name=tool_name,
            kwargs={k: str(v)[:200] for k, v in kwargs.items()},
            result=_truncate_result(result),
            duration_ms=duration_ms,
            failed=failed,
            error=error[:300] if error else None,
        )

        if run_id in self._open_runs:
            self._open_runs[run_id].tool_call_count += 1

        path = self._run_path(agent_id, run_id)
        if path.exists():
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict()) + "\n")

    def end_run(
        self,
        run_id: str,
        agent_id: str,
        response: str | None = None,
    ) -> RunRecord | None:
        """
        Close the run and write a ``run_end`` sentinel line.

        Returns the completed ``RunRecord``, or ``None`` if the run was
        never started (e.g. recorder created mid-request).
        """
        record = self._open_runs.pop(run_id, None)
        if record is None:
            return None

        record.ended_at = time.time()
        record.response = (response or "")[:500]

        path = self._run_path(agent_id, run_id)
        if path.exists():
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record.to_dict()) + "\n")

        self._prune_old_runs(agent_id)
        return record

    def load_run(self, agent_id: str, run_id: str) -> list[dict]:
        """Read all entries from a run's JSONL file."""
        path = self._run_path(agent_id, run_id)
        if not path.exists():
            return []
        entries = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def list_runs(self, agent_id: str) -> list[str]:
        """Return run IDs for an agent, sorted oldest-first."""
        runs_dir = self._runs_dir(agent_id)
        if not runs_dir.exists():
            return []
        files = sorted(runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        return [p.stem for p in files]

    # ── internal ─────────────────────────────────────────────────────────────

    def _prune_old_runs(self, agent_id: str) -> None:
        """Delete the oldest runs if we exceed _MAX_RUNS_PER_AGENT."""
        run_ids = self.list_runs(agent_id)
        excess = len(run_ids) - _MAX_RUNS_PER_AGENT
        for run_id in run_ids[:excess]:
            path = self._run_path(agent_id, run_id)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_result(result: Any) -> dict:
    """Return a truncated copy of a tool result dict safe for disk storage."""
    if not isinstance(result, dict):
        return {"_raw": str(result)[:_MAX_RESULT_CHARS]}
    truncated = {}
    for k, v in result.items():
        if k.startswith("_"):
            continue  # skip internal keys like _health
        s = str(v)
        truncated[k] = s[:_MAX_RESULT_CHARS] if len(s) > _MAX_RESULT_CHARS else v
    return truncated
