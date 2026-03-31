"""
Ordered middleware chain — composable before/after hooks for tool execution
and LLM calls, inspired by DeerFlow's 12-middleware pipeline.

Agentop's DriftGuard becomes one slot in the chain rather than the only
interception point. Each middleware is a class with optional hooks:

    before_tool(ctx) -> ctx | None   (return None to block)
    after_tool(ctx, result) -> result
    before_llm(messages, meta) -> messages
    after_llm(response, meta) -> response

The chain executes hooks in registration order (before_*) and reverse
order (after_*), matching standard middleware semantics.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("deerflow.middleware")


# ---------------------------------------------------------------------------
# Context objects passed through the chain
# ---------------------------------------------------------------------------


@dataclass
class ToolContext:
    """Immutable snapshot of an incoming tool call, enriched by middleware."""

    tool_name: str
    agent_id: str
    kwargs: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    blocked: bool = False
    block_reason: str = ""


@dataclass
class LLMContext:
    """Metadata travelling alongside an LLM call through the chain."""

    agent_id: str
    task: str = "general"
    token_budget: int = 2048
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base middleware class — override any hook you need
# ---------------------------------------------------------------------------


class Middleware:
    """Base class for chain middleware. Override only the hooks you need."""

    name: str = "unnamed"
    priority: int = 100  # lower = runs earlier

    async def before_tool(self, ctx: ToolContext) -> ToolContext | None:
        """Return ctx to continue, or None to block the tool call."""
        return ctx

    async def after_tool(self, ctx: ToolContext, result: dict[str, Any]) -> dict[str, Any]:
        return result

    async def before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        return messages

    async def after_llm(self, response: str, meta: LLMContext) -> str:
        return response


# ---------------------------------------------------------------------------
# Adapter: wrap Agentop's existing DriftGuard as a Middleware
# ---------------------------------------------------------------------------


class DriftGuardMiddleware(Middleware):
    """Wraps Agentop's DriftGuard singleton so it participates in the chain."""

    name = "drift_guard"
    priority = 10  # runs first — governance is non-negotiable

    def __init__(self) -> None:
        # Lazy import to avoid circular deps at module load time
        self._guard = None

    def _get_guard(self):
        if self._guard is None:
            from backend.middleware import drift_guard

            self._guard = drift_guard  # type: ignore[assignment]
        return self._guard

    async def before_tool(self, ctx: ToolContext) -> ToolContext | None:
        guard = self._get_guard()
        if guard.is_halted:
            ctx.blocked = True
            ctx.block_reason = "System halted — critical drift violation"
            return None
        return ctx

    async def after_tool(self, ctx: ToolContext, result: dict[str, Any]) -> dict[str, Any]:
        guard = self._get_guard()
        report = guard.check_invariants()
        result["_drift_status"] = report.status.value
        return result


# ---------------------------------------------------------------------------
# Logging middleware — records timing & outcomes
# ---------------------------------------------------------------------------


class LoggingMiddleware(Middleware):
    """Structured logging for every tool and LLM call passing through the chain."""

    name = "logging"
    priority = 20

    async def before_tool(self, ctx: ToolContext) -> ToolContext:
        ctx.metadata["_start_ns"] = time.perf_counter_ns()
        logger.info("tool.start agent=%s tool=%s", ctx.agent_id, ctx.tool_name)
        return ctx

    async def after_tool(self, ctx: ToolContext, result: dict[str, Any]) -> dict[str, Any]:
        start = ctx.metadata.get("_start_ns", 0)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        logger.info(
            "tool.done  agent=%s tool=%s elapsed=%.1fms ok=%s",
            ctx.agent_id,
            ctx.tool_name,
            elapsed_ms,
            "error" not in result,
        )
        return result

    async def before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        meta.metadata["_start_ns"] = time.perf_counter_ns()
        logger.info(
            "llm.start  agent=%s msgs=%d budget=%d",
            meta.agent_id,
            len(messages),
            meta.token_budget,
        )
        return messages

    async def after_llm(self, response: str, meta: LLMContext) -> str:
        start = meta.metadata.get("_start_ns", 0)
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        logger.info(
            "llm.done   agent=%s chars=%d elapsed=%.1fms",
            meta.agent_id,
            len(response),
            elapsed_ms,
        )
        return response


# ---------------------------------------------------------------------------
# Rate-limit middleware — per-agent tool call throttle
# ---------------------------------------------------------------------------


class RateLimitMiddleware(Middleware):
    """Per-agent rate limiter. Blocks tools if agent exceeds call budget."""

    name = "rate_limit"
    priority = 15

    def __init__(self, max_calls_per_minute: int = 60) -> None:
        self._max = max_calls_per_minute
        self._windows: dict[str, list[float]] = {}

    async def before_tool(self, ctx: ToolContext) -> ToolContext | None:
        now = time.time()
        window = self._windows.setdefault(ctx.agent_id, [])
        # prune stale entries
        cutoff = now - 60
        self._windows[ctx.agent_id] = [t for t in window if t > cutoff]
        window = self._windows[ctx.agent_id]

        if len(window) >= self._max:
            ctx.blocked = True
            ctx.block_reason = f"Rate limit: {ctx.agent_id} exceeded {self._max} tool calls/min"
            logger.warning("rate_limit.blocked agent=%s", ctx.agent_id)
            return None

        window.append(now)
        return ctx


# ---------------------------------------------------------------------------
# The chain itself
# ---------------------------------------------------------------------------


class MiddlewareChain:
    """
    Ordered pipeline of Middleware instances.

    Usage::

        chain = MiddlewareChain()
        chain.add(DriftGuardMiddleware())
        chain.add(LoggingMiddleware())
        chain.add(RateLimitMiddleware(max_calls_per_minute=30))

        # Tool execution
        ctx = ToolContext(tool_name="safe_shell", agent_id="devops_agent", kwargs={...})
        ctx = await chain.run_before_tool(ctx)
        if ctx is not None:
            result = await actual_tool_fn(**ctx.kwargs)
            result = await chain.run_after_tool(ctx, result)

        # LLM call
        messages = await chain.run_before_llm(messages, meta)
        response = await llm.chat(messages)
        response = await chain.run_after_llm(response, meta)
    """

    def __init__(self) -> None:
        self._middlewares: list[Middleware] = []
        self._sorted = False

    # -- registration -------------------------------------------------------

    def add(self, mw: Middleware) -> MiddlewareChain:
        """Add a middleware to the chain. Returns self for chaining."""
        self._middlewares.append(mw)
        self._sorted = False
        return self

    def remove(self, name: str) -> bool:
        """Remove middleware by name. Returns True if found."""
        before = len(self._middlewares)
        self._middlewares = [m for m in self._middlewares if m.name != name]
        return len(self._middlewares) < before

    @property
    def stack(self) -> list[str]:
        """Current middleware names in execution order."""
        self._ensure_sorted()
        return [m.name for m in self._middlewares]

    # -- tool hooks ---------------------------------------------------------

    async def run_before_tool(self, ctx: ToolContext) -> ToolContext | None:
        """Run before_tool hooks in priority order. None = blocked."""
        self._ensure_sorted()
        for mw in self._middlewares:
            result = await mw.before_tool(ctx)
            if result is None:
                logger.info(
                    "chain.blocked middleware=%s tool=%s agent=%s reason=%s",
                    mw.name,
                    ctx.tool_name,
                    ctx.agent_id,
                    ctx.block_reason,
                )
                return None
            ctx = result
        return ctx

    async def run_after_tool(self, ctx: ToolContext, result: dict[str, Any]) -> dict[str, Any]:
        """Run after_tool hooks in reverse priority order."""
        self._ensure_sorted()
        for mw in reversed(self._middlewares):
            result = await mw.after_tool(ctx, result)
        return result

    # -- LLM hooks ----------------------------------------------------------

    async def run_before_llm(
        self,
        messages: list[dict[str, str]],
        meta: LLMContext,
    ) -> list[dict[str, str]]:
        """Run before_llm hooks in priority order."""
        self._ensure_sorted()
        for mw in self._middlewares:
            messages = await mw.before_llm(messages, meta)
        return messages

    async def run_after_llm(self, response: str, meta: LLMContext) -> str:
        """Run after_llm hooks in reverse priority order."""
        self._ensure_sorted()
        for mw in reversed(self._middlewares):
            response = await mw.after_llm(response, meta)
        return response

    # -- internals ----------------------------------------------------------

    def _ensure_sorted(self) -> None:
        if not self._sorted:
            self._middlewares.sort(key=lambda m: m.priority)
            self._sorted = True
