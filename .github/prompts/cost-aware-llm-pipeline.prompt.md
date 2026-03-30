---
agent: agent
description: "Cost-Aware LLM Pipeline — model routing by task complexity, immutable cost tracking, retry logic, and budget guards for Agentop's backend/llm/."
tools: [search/codebase]
---

# Cost-Aware LLM Pipeline

Patterns for controlling LLM API costs in `backend/llm/` without sacrificing output quality. Combine model routing, immutable cost tracking, retry logic, and budget guards.

## When to Activate

- Adding a new LLM call anywhere in the pipeline
- Designing a new agent that calls Claude/OpenAI
- Reviewing `backend/llm/` or any file importing an LLM client
- Suspected cost overrun — debug with these patterns

---

## Core Pattern 1: Model Routing by Task Complexity

Not every call needs Sonnet. Route by complexity to cut costs 3-4x on simple tasks:

```python
# backend/llm/routing.py
MODEL_SONNET = "claude-sonnet-4-5"
MODEL_HAIKU  = "claude-haiku-4-5-20251001"

_TEXT_THRESHOLD  = 10_000  # chars — long inputs need stronger model
_ITEM_THRESHOLD  = 30      # items — many items need stronger model

def select_model(
    text_length: int,
    item_count: int = 1,
    force_model: str | None = None,
) -> str:
    """Select cheapest model that can handle the task."""
    if force_model is not None:
        return force_model
    if text_length >= _TEXT_THRESHOLD or item_count >= _ITEM_THRESHOLD:
        return MODEL_SONNET
    return MODEL_HAIKU  # 3-4x cheaper — use it when possible
```

**Task routing guide for Agentop agents:**

| Task | Model |
|---|---|
| Structure extraction from HTML | Haiku |
| Brief-to-palette mapping | Haiku |
| Single-section content generation | Haiku |
| Full page HTML generation | Sonnet |
| SEO audit + recommendations | Sonnet |
| Multi-page site planning | Sonnet |
| Architecture decision / root-cause analysis | Sonnet |

---

## Core Pattern 2: Immutable Cost Tracker

Track spend as frozen dataclasses — never mutate state, always return a new tracker:

```python
# backend/llm/cost_tracker.py
from dataclasses import dataclass

# Pricing per 1M tokens (update when pricing changes)
_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.00, 15.00),   # input, output per MTok
    "claude-haiku-4-5-20251001": (0.25, 1.25),
}

@dataclass(frozen=True, slots=True)
class CostRecord:
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        inp, out = _PRICES.get(self.model, (3.00, 15.00))
        return (self.input_tokens * inp + self.output_tokens * out) / 1_000_000

@dataclass(frozen=True, slots=True)
class CostTracker:
    budget_usd: float = 1.00
    records: tuple[CostRecord, ...] = ()

    def add(self, record: CostRecord) -> "CostTracker":
        """Return a new tracker — never mutates self."""
        return CostTracker(
            budget_usd=self.budget_usd,
            records=(*self.records, record),
        )

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    @property
    def over_budget(self) -> bool:
        return self.total_cost > self.budget_usd

    def summary(self) -> str:
        return (
            f"Total: ${self.total_cost:.4f} / ${self.budget_usd:.2f} budget "
            f"({len(self.records)} calls)"
        )
```

---

## Core Pattern 3: Retry Logic (Narrow Scope)

Only retry on transient errors. Never swallow permanent errors silently:

```python
# backend/llm/retry.py
import asyncio
import logging
from anthropic import RateLimitError, APIStatusError

logger = logging.getLogger(__name__)

async def call_with_retry(
    fn,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs,
):
    """Call fn with exponential backoff on transient errors.
    
    Retries on: RateLimitError, 529 (overloaded), 503 (service unavailable).
    Does NOT retry on: 400 (bad request), 401 (auth error), 404.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except RateLimitError as e:
            last_exc = e
            delay = base_delay * (2 ** attempt)
            logger.warning(f"Rate limited (attempt {attempt+1}/{max_retries}), retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
        except APIStatusError as e:
            if e.status_code in (503, 529):
                last_exc = e
                delay = base_delay * (2 ** attempt)
                logger.warning(f"API overloaded ({e.status_code}), retrying in {delay:.1f}s")
                await asyncio.sleep(delay)
            else:
                raise  # permanent error — don't retry
    raise last_exc  # max retries exhausted
```

---

## Core Pattern 4: Budget Guard

Wrap every pipeline with a budget check to prevent runaway costs:

```python
# backend/llm/budget_guard.py
from backend.llm.cost_tracker import CostTracker, CostRecord

class BudgetExceededError(Exception):
    pass

async def run_with_budget(
    pipeline_fn,
    brief: dict,
    budget_usd: float = 0.50,
) -> tuple[str, CostTracker]:
    """Run the pipeline, raising BudgetExceededError if cost exceeds budget."""
    tracker = CostTracker(budget_usd=budget_usd)

    async def tracked_complete(prompt: str, model: str) -> str:
        nonlocal tracker
        if tracker.over_budget:
            raise BudgetExceededError(
                f"Budget ${budget_usd:.2f} exceeded at ${tracker.total_cost:.4f} "
                f"before completing pipeline"
            )
        response = await llm_client.complete(prompt, model=model)
        record = CostRecord(
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        tracker = tracker.add(record)
        return response.content

    result = await pipeline_fn(brief, complete_fn=tracked_complete)
    return result, tracker
```

---

## Prompt Caching (Where Applicable)

For repeated system prompts (like design system context), use Anthropic's prompt caching to cut input costs ~90%:

```python
messages = [
    {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": DESIGN_SYSTEM_CONTEXT,        # large repeated block
                "cache_control": {"type": "ephemeral"}, # mark for caching
            },
            {
                "type": "text",
                "text": f"Generate a page for: {brief}",
            }
        ]
    }
]
```

Cache a block when:
- It is >1024 tokens (minimum cacheable size)
- It will appear in >2 requests in the same session
- It changes less frequently than your call rate

---

## Cost Logging

Always log cost at the end of a pipeline run so anomalies surface in logs:

```python
import logging

logger = logging.getLogger(__name__)

async def run_webgen_pipeline(brief: dict) -> str:
    result, tracker = await run_with_budget(pipeline_fn, brief, budget_usd=0.50)
    logger.info(
        "Webgen pipeline complete",
        extra={
            "job_id": brief.get("job_id"),
            "total_cost_usd": tracker.total_cost,
            "call_count": len(tracker.records),
            "over_budget": tracker.over_budget,
        }
    )
    return result
```

---

## Cost Audit Checklist

Before shipping any feature with new LLM calls:

- [ ] Is the cheapest viable model selected? (Haiku first, Sonnet only if complexity warrants)
- [ ] Is `CostTracker` threading through the pipeline?
- [ ] Is there a `budget_usd` guard that raises before silent overrun?
- [ ] Are retries limited to transient error codes only?
- [ ] Are cost values logged at pipeline completion?
- [ ] Is prompt caching applied to any repeated system context blocks?
