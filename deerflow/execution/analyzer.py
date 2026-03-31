"""
ExecutionAnalyzer — async post-run LLM analysis of recorded trajectories.

After each agent run completes, the analyzer loads the run's JSONL trajectory,
sends it to the LLM, and extracts:

  - Per-tool judgments: was each tool call healthy, degraded, or broken?
  - Per-skill judgments: should any skills be evolved (fix / derive / capture)?
  - Escalation flags: should self_healer_agent be notified?

Judgments are fed back into ToolHealthMonitor (for health stats) and
ToolRepairEngine (for proactive repair suggestions).

Inspired by HKUDS/OpenSpace's ExecutionAnalyzer.
See docs/INSPIRATIONS.md for attribution.

Usage::

    analyzer = ExecutionAnalyzer(
        llm_client=ollama_client,
        health_monitor=chain.health_monitor,
        repair_engine=chain.repair_engine,          # optional
        skill_registry=get_skill_registry(),         # optional
    )

    # Call this after every /chat completion (fire-and-forget is fine)
    await analyzer.analyze_run(
        run_id=run_id,
        agent_id="devops_agent",
        recorder=recorder,
    )
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

_ANALYSIS_SYSTEM = (
    "You are an AI agent performance auditor. "
    "Read the execution trajectory and return a JSON analysis. "
    "Be concise and specific. Return ONLY valid JSON — no markdown or prose."
)

_ANALYSIS_PROMPT = """\
Analyze this agent run trajectory and identify health issues.

Agent: {agent_id}
User message: {message}
Tool calls ({tool_count} total):
{tool_summary}

Respond with ONLY a JSON object:
{{
  "tool_judgments": [
    {{
      "tool_name": "...",
      "status": "healthy|degraded|broken",
      "issue": "one sentence or null",
      "suggested_fix": "one sentence or null"
    }}
  ],
  "skill_judgments": [
    {{
      "skill_id": "...",
      "action": "fix|derive|capture|none",
      "rationale": "one sentence"
    }}
  ],
  "escalate": false,
  "escalation_reason": null
}}

Rules:
- Only include tool_judgments for tools that had issues (status != healthy).
- Only include skill_judgments where action != "none".
- Set escalate=true only for systemic failures needing human review.
- Keep all text under 100 chars.
"""

_MAX_TOOL_SUMMARY_LINES = 30  # cap prompt size


@dataclass
class AnalysisJudgment:
    """Result of analyzing one agent run."""

    run_id: str
    agent_id: str
    analyzed_at: float = field(default_factory=time.time)
    tool_judgments: list[dict] = field(default_factory=list)
    skill_judgments: list[dict] = field(default_factory=list)
    escalate: bool = False
    escalation_reason: str | None = None
    raw_response: str = ""


class ExecutionAnalyzer:
    """
    Async post-run analyzer that reads a completed run's trajectory,
    asks the LLM to judge tool and skill health, then feeds those judgments
    back into ToolHealthMonitor and ToolRepairEngine.

    Designed to run fire-and-forget after every agent run completes:

        asyncio.ensure_future(analyzer.analyze_run(run_id, agent_id, recorder))
    """

    def __init__(
        self,
        llm_client: Any,
        health_monitor: Any,
        repair_engine: Any | None = None,
        skill_registry: Any | None = None,
    ) -> None:
        self._llm = llm_client
        self._monitor = health_monitor
        self._repair = repair_engine
        self._skills = skill_registry

    async def analyze_run(
        self,
        run_id: str,
        agent_id: str,
        recorder: Any,
    ) -> AnalysisJudgment | None:
        """
        Load the JSONL trajectory for ``run_id``, run the LLM analysis, and
        apply judgments to ToolHealthMonitor / ToolRepairEngine.

        Returns the ``AnalysisJudgment`` (for testing / logging) or ``None``
        if the run has no tool calls to analyze.
        """
        entries = recorder.load_run(agent_id, run_id)
        tool_calls = [e for e in entries if e.get("_type") == "tool_call"]
        if not tool_calls:
            return None

        run_meta: dict[str, Any] = next((e for e in entries if e.get("_type") == "run_start"), {})
        message = run_meta.get("message", "")

        prompt = self._build_prompt(agent_id, message, tool_calls)
        judgment = await self._run_analysis(run_id, agent_id, prompt)

        await self._apply_judgments(agent_id, tool_calls, judgment)
        return judgment

    # ── prompt building ──────────────────────────────────────────────────────

    def _build_prompt(
        self,
        agent_id: str,
        message: str,
        tool_calls: list[dict],
    ) -> str:
        lines = []
        for entry in tool_calls[-_MAX_TOOL_SUMMARY_LINES:]:
            status = "FAIL" if entry.get("failed") else "OK"
            err = f" | error: {entry['error']}" if entry.get("error") else ""
            lines.append(f"  [{status}] {entry['tool_name']} ({entry.get('duration_ms', 0):.0f}ms){err}")
        return _ANALYSIS_PROMPT.format(
            agent_id=agent_id,
            message=message[:200],
            tool_count=len(tool_calls),
            tool_summary="\n".join(lines),
        )

    # ── LLM call ─────────────────────────────────────────────────────────────

    async def _run_analysis(
        self,
        run_id: str,
        agent_id: str,
        prompt: str,
    ) -> AnalysisJudgment:
        judgment = AnalysisJudgment(run_id=run_id, agent_id=agent_id)
        try:
            raw = await self._llm.generate(prompt, system=_ANALYSIS_SYSTEM)
            judgment.raw_response = raw
            raw = re.sub(r"```(?:json)?\n?", "", raw).strip().rstrip("`").strip()
            data = json.loads(raw)
            judgment.tool_judgments = data.get("tool_judgments") or []
            judgment.skill_judgments = self._validate_skill_judgments(data.get("skill_judgments") or [])
            judgment.escalate = bool(data.get("escalate"))
            judgment.escalation_reason = data.get("escalation_reason")
        except Exception:
            # Non-fatal — analysis is best-effort
            pass
        return judgment

    # ── judgment application ─────────────────────────────────────────────────

    async def _apply_judgments(
        self,
        agent_id: str,
        tool_calls: list[dict],
        judgment: AnalysisJudgment,
    ) -> None:
        """Feed LLM judgments back into ToolHealthMonitor and ToolRepairEngine."""
        tasks = []

        for tj in judgment.tool_judgments:
            if tj.get("status") in ("degraded", "broken") and tj.get("issue"):
                tasks.append(
                    self._record_degradation(
                        agent_id=agent_id,
                        tool_name=tj["tool_name"],
                        issue=tj["issue"],
                    )
                )

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _record_degradation(
        self,
        agent_id: str,
        tool_name: str,
        issue: str,
    ) -> None:
        """
        Record analyzer-detected degradation into ToolHealthMonitor.
        Optionally triggers ToolRepairEngine for a proactive repair suggestion.
        """
        if self._monitor:
            self._monitor.record_failure(
                tool_name=tool_name,
                agent_id=agent_id,
                error=f"[analyzer] {issue}",
            )

        if self._repair:
            try:
                await self._repair.suggest_repair(
                    tool_name=tool_name,
                    agent_id=agent_id,
                    error=issue,
                    original_kwargs={},
                )
            except Exception:
                pass

    # ── skill ID validation ───────────────────────────────────────────────────

    def _validate_skill_judgments(self, judgments: list[dict]) -> list[dict]:
        """
        Drop or fuzzy-correct skill IDs that don't exist in the registry.

        If no registry is supplied, all judgments pass through unchecked.
        Inspired by OpenSpace's Levenshtein-based _correct_skill_ids().
        """
        if not self._skills or not judgments:
            return judgments

        try:
            known = set(self._skills.list_skill_ids() if hasattr(self._skills, "list_skill_ids") else [])
        except Exception:
            return judgments

        if not known:
            return judgments

        valid = []
        for j in judgments:
            sid = j.get("skill_id", "")
            if sid in known:
                valid.append(j)
            else:
                corrected = _fuzzy_match(sid, known)
                if corrected:
                    j = dict(j, skill_id=corrected)
                    valid.append(j)
                # else: drop the hallucinated ID entirely
        return valid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fuzzy_match(target: str, candidates: set[str], max_distance: int = 3) -> str | None:
    """
    Return the best candidate within ``max_distance`` edit distance, or None.
    Simple O(n) loop — registry is small enough that this is fine.
    """
    best: str | None = None
    best_dist = max_distance + 1
    for candidate in candidates:
        dist = _levenshtein(target, candidate)
        if dist < best_dist:
            best_dist = dist
            best = candidate
    return best if best_dist <= max_distance else None


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (ca != cb)))
        prev = curr
    return prev[-1]
