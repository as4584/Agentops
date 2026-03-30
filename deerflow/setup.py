"""
DeerFlow setup — one-call factory that builds a fully-wired MiddlewareChain
with all five components active.

Usage from Agentop backend::

    from deerflow.setup import create_deerflow_chain

    chain = create_deerflow_chain(
        llm_client=ollama_client,
        memory_store=memory_store,
        skill_registry=get_skill_registry(),
        orchestrator=orchestrator,
    )

    # Use the chain for tool execution
    ctx = ToolContext(tool_name="safe_shell", agent_id="devops_agent", kwargs={...})
    ctx = await chain.run_before_tool(ctx)
    if ctx:
        result = await actual_tool(**ctx.kwargs)
        result = await chain.run_after_tool(ctx, result)

    # Use the chain for LLM calls
    meta = LLMContext(agent_id="devops_agent")
    messages = await chain.run_before_llm(messages, meta)
    response = await llm.chat(messages)
    response = await chain.run_after_llm(response, meta)
"""

from __future__ import annotations

from typing import Any

from deerflow.delegation.task import TaskDelegator
from deerflow.memory.facts import FactMemory
from deerflow.memory.middleware import FactMemoryMiddleware
from deerflow.middleware.chain import (
    DriftGuardMiddleware,
    LoggingMiddleware,
    MiddlewareChain,
    RateLimitMiddleware,
)
from deerflow.middleware.summarization import SummarizationMiddleware
from deerflow.skills.progressive import ProgressiveSkillLoader
from deerflow.tools.health import ToolHealthMonitor
from deerflow.tools.middleware import ToolHealthMiddleware
from deerflow.tools.repair import ToolRepairEngine


def create_deerflow_chain(
    llm_client: Any,
    memory_store: Any,
    skill_registry: Any,
    orchestrator: Any | None = None,
    *,
    max_history: int = 20,
    keep_recent: int = 6,
    max_skills: int = 3,
    rate_limit_rpm: int = 60,
    enable_auto_repair: bool = False,
) -> MiddlewareChain:
    """
    Build a fully-wired MiddlewareChain with all DeerFlow components.

    Middleware execution order (by priority):
         8 - Tool health tracking + repair
        10 - DriftGuard (governance gate)
        15 - Rate limiter
        20 - Logging
        40 - Fact memory (inject + extract)
        45 - Progressive skills
        50 - Context summarization

    Args:
        enable_auto_repair: If True, wire ToolRepairEngine so the chain
            will automatically retry failing tools with LLM-suggested
            parameter fixes. Defaults to False (track only).

    Returns the chain. Also attaches helper objects as attributes:
        chain.fact_memory     — FactMemory instance
        chain.skill_loader    — ProgressiveSkillLoader instance
        chain.health_monitor  — ToolHealthMonitor instance
        chain.repair_engine   — ToolRepairEngine (if enable_auto_repair)
        chain.delegator       — TaskDelegator (if orchestrator provided)
    """
    chain = MiddlewareChain()

    # 0. Tool health tracking — priority 8 (outermost tool wrapper)
    health_monitor = ToolHealthMonitor(memory_store)
    repair_engine = ToolRepairEngine(llm_client, health_monitor) if enable_auto_repair else None
    chain.add(ToolHealthMiddleware(health_monitor, repair_engine))

    # 1. Governance — priority 10
    chain.add(DriftGuardMiddleware())

    # 2. Rate limiting — priority 15
    chain.add(RateLimitMiddleware(max_calls_per_minute=rate_limit_rpm))

    # 3. Logging — priority 20
    chain.add(LoggingMiddleware())

    # 4. Fact memory — priority 40
    fact_mem = FactMemory(llm_client, memory_store)
    chain.add(FactMemoryMiddleware(fact_mem))

    # 5. Progressive skills — priority 45
    skill_loader = ProgressiveSkillLoader(skill_registry)
    chain.add(skill_loader.as_middleware(max_skills=max_skills))

    # 6. Context summarization — priority 50
    chain.add(
        SummarizationMiddleware(
            llm_client,
            max_history=max_history,
            keep_recent=keep_recent,
        )
    )

    # Attach helpers for direct access
    chain.fact_memory = fact_mem  # type: ignore[attr-defined]
    chain.skill_loader = skill_loader  # type: ignore[attr-defined]
    chain.health_monitor = health_monitor  # type: ignore[attr-defined]
    if repair_engine is not None:
        chain.repair_engine = repair_engine  # type: ignore[attr-defined]

    if orchestrator is not None:
        chain.delegator = TaskDelegator(orchestrator)  # type: ignore[attr-defined]

    return chain
