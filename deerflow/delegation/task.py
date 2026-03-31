"""
Sub-agent task delegation — fan out subtasks to specialist agents through
the orchestrator, collect results, and synthesize.

Inspired by DeerFlow's sub-agent delegation pattern, but built on top of
Agentop's AgentOrchestrator.process_message() so that:
  - INV-2 is respected (no direct agent-to-agent calls)
  - DriftGuard governance applies to every subtask
  - Each subtask gets isolated context

Usage::

    delegator = TaskDelegator(orchestrator)
    result = await delegator.delegate(
        parent_agent="gsd_agent",
        subtasks=[
            SubTask(agent_id="security_agent", instruction="Scan /app for secrets"),
            SubTask(agent_id="code_review_agent", instruction="Review PR #42 diffs"),
        ],
    )
    # result.outcomes = [TaskOutcome(...), TaskOutcome(...)]
    # result.synthesis = "Security scan found 0 issues. Code review flagged 2 style nits."
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("deerflow.delegation")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class SubTask:
    """A single unit of work to delegate to a specialist agent."""

    agent_id: str
    instruction: str
    context: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float = 120.0


@dataclass
class TaskOutcome:
    """Result of one subtask execution."""

    agent_id: str
    instruction: str
    response: str
    success: bool
    error: str | None = None
    elapsed_seconds: float = 0.0
    drift_status: str = "GREEN"


@dataclass
class TaskResult:
    """Aggregated result of all subtasks."""

    parent_agent: str
    outcomes: list[TaskOutcome] = field(default_factory=list)
    synthesis: str = ""
    total_elapsed: float = 0.0


# ---------------------------------------------------------------------------
# TaskDelegator
# ---------------------------------------------------------------------------


class TaskDelegator:
    """
    Fans out subtasks to specialist agents via the orchestrator.

    Tasks can run concurrently (``parallel=True``) or sequentially.
    A synthesis step optionally combines all outcomes into a summary
    using the parent agent's LLM capabilities.
    """

    def __init__(self, orchestrator: Any) -> None:
        self._orch = orchestrator

    async def delegate(
        self,
        parent_agent: str,
        subtasks: list[SubTask],
        parallel: bool = True,
        synthesize: bool = True,
    ) -> TaskResult:
        """
        Execute *subtasks* and return aggregated results.

        Parameters
        ----------
        parent_agent : str
            The agent requesting the delegation (for audit trail).
        subtasks : list[SubTask]
            Work items to dispatch.
        parallel : bool
            If True, run all subtasks concurrently.
        synthesize : bool
            If True, produce a natural-language synthesis of outcomes.
        """
        if not subtasks:
            return TaskResult(parent_agent=parent_agent)

        available = set(self._orch.get_available_agents())
        valid_tasks = []
        outcomes: list[TaskOutcome] = []

        for st in subtasks:
            if st.agent_id not in available:
                outcomes.append(
                    TaskOutcome(
                        agent_id=st.agent_id,
                        instruction=st.instruction,
                        response="",
                        success=False,
                        error=f"Agent '{st.agent_id}' not registered",
                    )
                )
            else:
                valid_tasks.append(st)

        start = time.monotonic()

        if parallel:
            results = await asyncio.gather(
                *[self._run_one(st) for st in valid_tasks],
                return_exceptions=True,
            )
            for st, res in zip(valid_tasks, results):
                if isinstance(res, BaseException):
                    outcomes.append(
                        TaskOutcome(
                            agent_id=st.agent_id,
                            instruction=st.instruction,
                            response="",
                            success=False,
                            error=str(res),
                        )
                    )
                else:
                    outcomes.append(res)
        else:
            for st in valid_tasks:
                try:
                    outcome = await self._run_one(st)
                    outcomes.append(outcome)
                except Exception as exc:
                    outcomes.append(
                        TaskOutcome(
                            agent_id=st.agent_id,
                            instruction=st.instruction,
                            response="",
                            success=False,
                            error=str(exc),
                        )
                    )

        total = time.monotonic() - start

        result = TaskResult(
            parent_agent=parent_agent,
            outcomes=outcomes,
            total_elapsed=total,
        )

        if synthesize and any(o.success for o in outcomes):
            result.synthesis = await self._synthesize(parent_agent, outcomes)

        logger.info(
            "delegation.done parent=%s tasks=%d ok=%d elapsed=%.1fs",
            parent_agent,
            len(subtasks),
            sum(1 for o in outcomes if o.success),
            total,
        )

        return result

    # -- internals ----------------------------------------------------------

    async def _run_one(self, st: SubTask) -> TaskOutcome:
        """Execute a single subtask through the orchestrator."""
        start = time.monotonic()

        try:
            resp = await asyncio.wait_for(
                self._orch.process_message(
                    agent_id=st.agent_id,
                    message=st.instruction,
                    context=st.context,
                ),
                timeout=st.timeout_seconds,
            )
        except TimeoutError:
            return TaskOutcome(
                agent_id=st.agent_id,
                instruction=st.instruction,
                response="",
                success=False,
                error=f"Timeout after {st.timeout_seconds}s",
                elapsed_seconds=time.monotonic() - start,
            )

        elapsed = time.monotonic() - start
        error = resp.get("error")

        return TaskOutcome(
            agent_id=st.agent_id,
            instruction=st.instruction,
            response=resp.get("response", ""),
            success=error is None,
            error=error,
            elapsed_seconds=elapsed,
            drift_status=resp.get("drift_status", "GREEN"),
        )

    async def _synthesize(self, parent_agent: str, outcomes: list[TaskOutcome]) -> str:
        """Combine subtask results into a concise synthesis."""
        parts = []
        for o in outcomes:
            status = "OK" if o.success else f"FAILED: {o.error}"
            parts.append(f"[{o.agent_id}] ({status}) {o.response[:500]}")

        prompt = (
            "Synthesize these subtask results into a brief summary "
            "highlighting key findings and any failures:\n\n" + "\n---\n".join(parts)
        )

        try:
            return await self._orch.process_message(
                agent_id=parent_agent,
                message=prompt,
                context={"_delegation_synthesis": True},
            ).get("response", "")  # type: ignore[union-attr]
        except Exception:
            # Fallback: just concatenate
            return " | ".join(f"{o.agent_id}: {'ok' if o.success else 'fail'}" for o in outcomes)
