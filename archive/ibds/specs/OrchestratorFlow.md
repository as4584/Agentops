1. Interface  
```python
from __future__ import annotations
from typing import TypedDict, Any, Literal
from dataclasses import dataclass
import asyncio

# --- Public input / output ----------------------------------------------

class UserRequest(TypedDict, total=True):
    """Exactly what a REST handler receives."""
    user_id: str
    query: str
    thread_id: str

@dataclass(slots=True)
class OrchestratorResult:
    """One-liner delivered to caller."""
    summary: str                 # "< 120-char single-line sentence"
    memory_id: str                 # ID of stored memory entry
    status: Literal["ok", "spend_limit", "error"]

# --- Internal types -----------------------------------------------------

@dataclass(slots=True)
class TaskContext:
    request: UserRequest
    task_type: str                 # value returned by TaskClassifier
    allowed_models: list[str]      # filtered by SpendTracker
    chosen_model: str              # returned by ModelRouter
    chosen_agent: str              # returned by SubagentFactory
    agent_result: Any              # raw output from agent
    one_liner: str                 # compressed summary

# --- Public API ---------------------------------------------------------

class OrchestratorFlow:
    """
    Singleton. Keeps *zero* component instances itself – caller injects
    everything in __init__.
    """

    def __init__(
        self,
        *,
        task_classifier,      # sync call: classify(request) -> str
        spend_tracker,        # async check: check(user_id, projected_cost) -> bool
        model_router,         # sync choose(task_type, allowed_models, query) -> str
        subagent_factory,     # sync build(task_type, model) -> object implementing execute()
        compression_service,  # async compress(raw_result) -> str
        memory_store,         # async append(thread_id, summary) -> memory_id
        logger = None,        # optional logger adapter – standard interface used when provided
    ):
        ...

    async def run(self, request: UserRequest) -> OrchestratorResult:
        """
        Main pipeline. Never raises to caller; instead returns a status !=
        'ok'. All exceptions are logged and translated into
        status='error' with a generic user-facing summary.
        """
        ...
```

2. Core logic (run() step-by-step)  
```python
async def run(self, request: UserRequest) -> OrchestratorResult:
    ctx = TaskContext(request=request, task_type="", allowed_models=[],
                      chosen_model="", chosen_agent="", agent_result=None,
                      one_liner="")
    try:
        # 1. TaskClassifier
        ctx.task_type = self.task_classifier.classify(request)

        # 2. SpendTracker projection check
        projected = await self.spend_tracker.project(ctx.request["user_id"])
        ok = await self.spend_tracker.check(ctx.request["user_id"], projected)
        if not ok:
            return OrchestratorResult(
                summary="Monthly usage limit reached.",
                memory_id="",
                status="spend_limit"
            )
        ctx.allowed_models = projected.get("allowed_models", [])

        # 3. ModelRouter
        ctx.chosen_model = self.model_router.choose(
            ctx.task_type, ctx.allowed_models, ctx.request["query"]
        )

        # 4. SubagentFactory
        agent = self.subagent_factory.build(ctx.task_type, ctx.chosen_model)

        # 5. Execute (async – agents may do remote work)
        ctx.agent_result = await agent.execute(ctx.request["query"])

        # 6. Compress → one-liner
        ctx.one_liner = await self.compression_service.compress(
            ctx.agent_result
        )
        if len(ctx.one_liner) > 120:
            ctx.one_liner = ctx.one_liner[:117] + "..."

        # 7. Write to memory
        memory_id = await self.memory_store.append(
            ctx.request["thread_id"],
            {"query": ctx.request["query"], "summary": ctx.one_liner}
        )

        return OrchestratorResult(
            summary=ctx.one_liner,
            memory_id=memory_id,
            status="ok"
        )

    except asyncio.CancelledError:          # respect cancellation
        raise
    except Exception as exc:                # catch-all: log and mask
        if self.logger:                     # optional logger usage
            self.logger.error("OrchestratorFlow error", extra={"context": ctx})
        return OrchestratorResult(
            summary="An internal error occurred, please try again later.",
            memory_id="",
            status="error"
        )
```

3. Edge-cases to handle  
- Spend limit reached must short-circuit (no agent executed) and return status="spend_limit".  
- Empty allowed_models from SpendTracker ⇒ Router should never be called; treat as error (caught by general handler).  
- Agent.execute() raises ⇒ bubble into generic error summary, do NOT leak trace.  
- Compression returning >120 chars ⇒ clip to 117 chars + "...".  
- Simultaneous requests for same user_id—each request treated independently; SpendTracker must be internally thread-safe on projection/quota.  
- Cancellation (asyncio.CancelledError) must re-raise to let ASGI server cancel cleanly.  
- All other exceptions become status="error" with hard-coded generic message.  

4. What OrchestratorFlow MUST NOT do  
- Store history or state between requests.  
- Implement retry logic; if agent fails, the request ends in error.  
- Parse or validate the final summary/JSON returned to user/client – it merely passes along what compression_service produces.  
- Decide model costs / thresholds – that lives in SpendTracker.  
- Choose task descriptors or model names – delegated to TaskClassifier and ModelRouter.  
- Expose internal TaskContext to callers; only OrchestratorResult is returned.