"""
Tool health middleware and unified failure detection.

detect_tool_failure()   — normalises all 12 native tool result shapes into
                           a single (is_failure, error_message) tuple.
ToolHealthMiddleware    — deerflow Middleware that records calls/failures and
                           optionally triggers LLM-guided repair.
"""

from __future__ import annotations

from typing import Any

from deerflow.middleware.chain import Middleware, ToolContext
from deerflow.tools.health import ToolHealthMonitor
from deerflow.tools.repair import ToolRepairEngine


# ---------------------------------------------------------------------------
# Unified failure detection
# ---------------------------------------------------------------------------

def detect_tool_failure(result: Any) -> tuple[bool, str | None]:
    """
    Inspect any tool result dict and return ``(is_failure, error_message)``.

    Handles ALL 12 native tool result schemas so callers don't need to know
    which keys each tool uses.

    Failure conditions detected:
    - ``error`` key present and truthy                (all tools)
    - ``success == False``                            (doc_updater, webhook_send, process_restart)
    - ``reachable == False``                          (health_check)
    - ``exists == False``                             (file_reader)
    - ``return_code != 0`` and not blocked            (safe_shell)
    - ``dispatched == False``                         (alert_dispatch)
    """
    if not isinstance(result, dict):
        return False, None

    # Explicit error key
    if result.get("error"):
        return True, str(result["error"])

    # Boolean success flag
    if result.get("success") is False:
        msg = result.get("message") or result.get("error") or "success=False"
        return True, str(msg)

    # Reachability (health_check)
    if result.get("reachable") is False:
        url = result.get("url", "unknown")
        return True, f"unreachable: {url}"

    # File existence (file_reader)
    if result.get("exists") is False:
        return True, "file not found"

    # Non-zero exit code (safe_shell) — only when NOT blocked
    rc = result.get("return_code")
    if rc is not None and rc != 0 and not result.get("blocked"):
        stderr = str(result.get("stderr", ""))[:200]
        return True, f"exit code {rc}" + (f": {stderr}" if stderr else "")

    # Dispatch failure (alert_dispatch)
    if result.get("dispatched") is False:
        return True, "alert_dispatch failed"

    return False, None


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class ToolHealthMiddleware(Middleware):
    """
    Middleware that sits in the deerflow chain and:

    1. Records every tool call via ``ToolHealthMonitor.record_call()``.
    2. After execution, detects failures across all tool result schemas.
    3. Records failures and annotates results with ``_health`` metadata.
    4. For non-chronic failures, optionally invokes ``ToolRepairEngine``
       to attempt an LLM-guided auto-repair.
    5. For chronic failures, appends a self_healer_agent recommendation.

    Priority 8 — runs just before DriftGuard (priority 10).
    """

    priority = 8
    name = "tool_health"

    def __init__(
        self,
        health_monitor: ToolHealthMonitor,
        repair_engine: ToolRepairEngine | None = None,
    ) -> None:
        super().__init__()
        self._monitor = health_monitor
        self._repair = repair_engine

    async def before_tool(self, ctx: ToolContext) -> ToolContext:
        self._monitor.record_call(ctx.tool_name)
        return ctx

    async def after_tool(self, ctx: ToolContext, result: Any) -> Any:
        if not isinstance(result, dict):
            return result

        is_failure, error_msg = detect_tool_failure(result)

        if not is_failure:
            result["_health"] = {"status": "ok", "tool": ctx.tool_name}
            return result

        # Record the failure
        self._monitor.record_failure(
            tool_name=ctx.tool_name,
            agent_id=ctx.agent_id,
            error=error_msg or "unknown",
            kwargs=ctx.kwargs,
        )

        stats = self._monitor.get_stats(ctx.tool_name)
        result["_health"] = {
            "status": "failed",
            "tool": ctx.tool_name,
            "error": error_msg,
            "is_chronic": stats.is_chronic,
            "total_failures": stats.total_failures,
        }

        # Chronic tools → skip repair, escalate immediately
        if stats.is_chronic:
            result["_health"]["recommendation"] = (
                f"Tool '{ctx.tool_name}' has failed {stats.total_failures} times "
                f"in the last hour. Invoke self_healer_agent to investigate."
            )
            return result

        # Attempt LLM-guided repair if engine is wired in
        if self._repair is not None:
            # Lazy import to avoid circular dep at module level
            from backend.tools import execute_tool as _execute_tool

            async def _exec(tn: str, aid: str, **kw: Any) -> dict:
                return await _execute_tool(
                    tool_name=tn,
                    agent_id=aid,
                    allowed_tools=list(kw.keys()),  # permissive for repair attempt
                    **kw,
                )

            repaired, suggestion = await self._repair.attempt_repair(
                tool_name=ctx.tool_name,
                agent_id=ctx.agent_id,
                error=error_msg or "",
                original_kwargs=ctx.kwargs,
                execute_fn=_exec,
            )

            if repaired is not None:
                repaired["_health"] = {
                    "status": "repaired",
                    "tool": ctx.tool_name,
                    "strategy": suggestion.strategy,
                    "rationale": suggestion.rationale,
                    "confidence": suggestion.confidence,
                }
                return repaired

            # Repair was suggested but not executed — surface the advice
            result["_health"]["repair_suggestion"] = {
                "strategy": suggestion.strategy,
                "rationale": suggestion.rationale,
                "confidence": suggestion.confidence,
            }

        return result
