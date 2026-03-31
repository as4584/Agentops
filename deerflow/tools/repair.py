"""
ToolRepairEngine — LLM-powered analysis and repair for failing tools.

When a tool fails, the repair engine sends the failure context to the LLM
and asks it to suggest either a parameter fix (mutate), a retry, or an
escalation to self_healer_agent.  If confidence is high enough, it
automatically retries the repaired call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from deerflow.tools.health import ToolHealthMonitor

_REPAIR_SYSTEM = (
    "You are a tool repair specialist for an AI agent system. "
    "Analyze tool failures and return ONLY a JSON repair suggestion."
)

_REPAIR_PROMPT = """\
A tool call failed. Analyze the failure and suggest the best recovery action.

Tool: {tool_name}
Agent: {agent_id}
Error: {error}
Original kwargs: {kwargs}

Recent failure history for this tool (last 5):
{history}

Respond with ONLY a JSON object — no markdown, no explanation outside the JSON:
{{
  "strategy": "retry|mutate|skip|escalate",
  "suggested_kwargs": {{ ... }},
  "rationale": "one sentence explanation",
  "confidence": 0.0
}}

Strategy meanings:
- retry    : same kwargs, looks like a transient error (timeout, flake)
- mutate   : change the kwargs to fix the root cause
- skip     : tool is unavailable, return empty result gracefully
- escalate : requires self_healer_agent or human intervention
"""

# Confidence threshold above which the engine will auto-execute the repair
_AUTO_RETRY_THRESHOLD = 0.75


@dataclass
class RepairSuggestion:
    """The LLM's repair recommendation for a failed tool call."""

    strategy: str  # retry | mutate | skip | escalate
    suggested_kwargs: dict[str, Any] = field(default_factory=dict)
    rationale: str = ""
    confidence: float = 0.0

    @classmethod
    def skip(cls, rationale: str) -> RepairSuggestion:
        """Convenience constructor for a no-op skip suggestion."""
        return cls(strategy="skip", rationale=rationale, confidence=1.0)

    @classmethod
    def escalate(cls, rationale: str) -> RepairSuggestion:
        """Convenience constructor for an escalation suggestion."""
        return cls(strategy="escalate", rationale=rationale, confidence=1.0)


class ToolRepairEngine:
    """
    Uses the LLM to analyze tool failures and suggest (or auto-execute)
    repaired parameter sets.

    Usage::

        engine = ToolRepairEngine(llm_client, health_monitor)

        # Just get a suggestion
        suggestion = await engine.suggest_repair(
            tool_name="safe_shell",
            agent_id="devops_agent",
            error="command not found: docker",
            original_kwargs={"command": "docker ps"},
        )

        # Auto-retry if confidence is high enough
        result, suggestion = await engine.attempt_repair(
            tool_name="safe_shell",
            agent_id="devops_agent",
            error="command not found: docker",
            original_kwargs={"command": "docker ps"},
            execute_fn=execute_tool_wrapper,
        )
    """

    def __init__(self, llm_client: Any, health_monitor: ToolHealthMonitor) -> None:
        self._llm = llm_client
        self._monitor = health_monitor
        # Anti-loop guard (OpenSpace-inspired): tracks (tool_name, error_fingerprint)
        # pairs that have already been attempted so we don't retry the same repair
        # indefinitely.  Maps tool_name -> set of error fingerprints addressed.
        self._addressed_degradations: dict[str, set[str]] = {}

    async def suggest_repair(
        self,
        tool_name: str,
        agent_id: str,
        error: str,
        original_kwargs: dict[str, Any],
    ) -> RepairSuggestion:
        """
        Ask the LLM to suggest a repair strategy for a failed tool call.
        Always returns a RepairSuggestion (falls back to 'skip' on LLM error).
        """
        stats = self._monitor.get_stats(tool_name)

        # Short-circuit: chronic tool should go straight to escalation
        if stats.is_chronic:
            return RepairSuggestion.escalate(
                f"Tool '{tool_name}' has failed {stats.total_failures} times. Route to self_healer_agent."
            )

        # Anti-loop guard: if this exact (tool, error) combo was already addressed,
        # escalate rather than looping through the same LLM repair attempt again.
        fingerprint = error[:120]  # first 120 chars as a stable fingerprint
        if fingerprint in self._addressed_degradations.get(tool_name, set()):
            return RepairSuggestion.escalate(
                f"Repair for '{tool_name}' (error: {fingerprint!r}) already attempted. "
                "Escalating to prevent repair loop."
            )

        history_lines = [
            f"  [{i + 1}] error={f.error!r} kwargs={f.kwargs}" for i, f in enumerate(stats.recent_failures[-5:])
        ]
        history = "\n".join(history_lines) or "  (no prior failures)"

        prompt = _REPAIR_PROMPT.format(
            tool_name=tool_name,
            agent_id=agent_id,
            error=error,
            kwargs=json.dumps(original_kwargs, default=str),
            history=history,
        )

        try:
            raw = await self._llm.generate(prompt, system=_REPAIR_SYSTEM)
            # Strip markdown code fences if the LLM wrapped the JSON
            raw = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`").strip()
            data = json.loads(raw)
            suggestion = RepairSuggestion(
                strategy=data.get("strategy", "skip"),
                suggested_kwargs=data.get("suggested_kwargs") or {},
                rationale=data.get("rationale", ""),
                confidence=float(data.get("confidence", 0.0)),
            )
            # Mark this degradation as addressed so we don't loop
            self._addressed_degradations.setdefault(tool_name, set()).add(fingerprint)
            return suggestion
        except Exception as exc:
            return RepairSuggestion.skip(f"Repair LLM unavailable: {exc}")

    async def attempt_repair(
        self,
        tool_name: str,
        agent_id: str,
        error: str,
        original_kwargs: dict[str, Any],
        execute_fn: Callable[..., Awaitable[dict]],
    ) -> tuple[dict | None, RepairSuggestion]:
        """
        Combine suggest_repair with an optional auto-execution of the repair.

        If the suggestion strategy is 'retry' or 'mutate' AND confidence
        meets the threshold, the repaired call is executed via ``execute_fn``.

        Returns:
            (repaired_result_or_None, suggestion)
        """
        suggestion = await self.suggest_repair(tool_name, agent_id, error, original_kwargs)

        if suggestion.strategy in ("skip", "escalate"):
            return None, suggestion

        if suggestion.confidence < _AUTO_RETRY_THRESHOLD:
            return None, suggestion

        kwargs = (
            suggestion.suggested_kwargs
            if suggestion.strategy == "mutate" and suggestion.suggested_kwargs
            else original_kwargs
        )

        try:
            result = await execute_fn(tool_name, agent_id, **kwargs)
            return result, suggestion
        except Exception as exc:
            suggestion.rationale += f" | Auto-repair execution failed: {exc}"
            return None, suggestion
