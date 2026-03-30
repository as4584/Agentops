---
agent: agent
description: "Python Patterns — idiomatic Python for Agentop's FastAPI backend: type hints, EAFP, async, context managers, exception hierarchies."
tools: [search/codebase]
---

# Python Development Patterns

Idiomatic Python standards for all code in `backend/`. Apply these patterns when writing new agents, routes, skills, and utilities.

## When to Activate

- Writing or reviewing any Python file in `backend/`
- Designing a new agent, service, or pipeline stage
- Refactoring existing code

## Core Principles

**Readability over cleverness.** Code is read far more than it is written.

**Explicit over implicit.** No hidden side effects, no magic.

**EAFP (Easier to Ask Forgiveness than Permission)** — prefer try/except over pre-checking conditions.

**YAGNI** — don't build what isn't needed today.

## Type Hints

Always annotate function signatures. Use Python 3.10+ union syntax:

```python
# ✅ Modern annotations
def get_agent(agent_id: str) -> "AgentConfig | None":
    ...

async def process_brief(brief: dict[str, str], *, timeout: float = 30.0) -> str:
    ...

# Type aliases for complex payloads
type JSON = dict[str, object] | list[object] | str | int | float | bool | None

def parse_llm_response(raw: str) -> JSON:
    return json.loads(raw)
```

Use `Protocol` for duck-typed interfaces:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class AgentLike(Protocol):
    async def run(self, brief: dict) -> str: ...
    def name(self) -> str: ...

def register_agent(agent: AgentLike) -> None:
    ...
```

## Exception Handling

### Custom Hierarchy

```python
class AgentopError(Exception):
    """Base for all application errors."""

class AgentTimeoutError(AgentopError):
    """Agent exceeded allowed execution time."""

class LLMQuotaError(AgentopError):
    """LLM API quota exceeded."""

class ValidationError(AgentopError):
    """Input failed validation."""
```

### Specific Exceptions + Chaining

```python
# ✅ Chain exceptions to preserve traceback context
def load_agent_config(path: str) -> AgentConfig:
    try:
        with open(path) as f:
            return AgentConfig.model_validate_json(f.read())
    except FileNotFoundError as e:
        raise AgentopError(f"Config not found: {path}") from e
    except json.JSONDecodeError as e:
        raise AgentopError(f"Invalid JSON in config: {path}") from e

# ❌ Never use bare except or silent failures
try:
    result = do_something()
except:
    return None  # Swallows the error — don't do this
```

## Async Patterns

Agentop backend uses `asyncio`. Follow these patterns throughout:

```python
import asyncio
from typing import Any

# ✅ Gather independent tasks in parallel
async def run_pipeline_stages(brief: dict) -> dict[str, Any]:
    seo_task = asyncio.create_task(seo_agent.run(brief))
    aeo_task = asyncio.create_task(aeo_agent.run(brief))
    meta_task = asyncio.create_task(meta_agent.run(brief))

    seo, aeo, meta = await asyncio.gather(seo_task, aeo_task, meta_task)
    return {"seo": seo, "aeo": aeo, "meta": meta}

# ✅ Timeout guard
async def safe_llm_call(prompt: str, timeout: float = 30.0) -> str:
    try:
        return await asyncio.wait_for(llm_client.complete(prompt), timeout=timeout)
    except asyncio.TimeoutError:
        raise AgentTimeoutError(f"LLM call timed out after {timeout}s")
```

## Context Managers

Use for all resource acquisition: files, DB sessions, HTTP clients:

```python
from contextlib import asynccontextmanager
from sqlalchemy.ext.asyncio import AsyncSession

@asynccontextmanager
async def get_db_session() -> AsyncSession:
    session = Session()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()

# Usage
async def save_result(job_id: str, html: str) -> None:
    async with get_db_session() as session:
        await session.execute(
            insert(WebgenResult).values(job_id=job_id, html=html)
        )
```

## Dataclasses & Pydantic

Prefer Pydantic models for any external-facing data, plain `dataclass` for internal structs:

```python
from pydantic import BaseModel, field_validator
from dataclasses import dataclass, field

# External API schema — Pydantic
class ClientBrief(BaseModel):
    brand_name: str
    domain: str
    primary_color: str = "#2563EB"
    tone: str = "professional"

    @field_validator("primary_color")
    @classmethod
    def validate_hex(cls, v: str) -> str:
        if not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError(f"Invalid hex color: {v}")
        return v.upper()

# Internal struct — dataclass
@dataclass(frozen=True, slots=True)
class PipelineResult:
    job_id: str
    html: str
    cost_usd: float
    elapsed_s: float
    stages_run: list[str] = field(default_factory=list)
```

## Collections & Iteration

```python
# ✅ Prefer comprehensions for transformations
active_agents = [a for a in agents if a.is_enabled]
agent_map = {a.name: a for a in agents}

# ✅ Use generator expressions for lazy chains without building an intermediate list
total_tokens = sum(r.tokens for r in records if not r.cached)

# ✅ enumerate() for index + value
for i, stage in enumerate(pipeline_stages, start=1):
    logger.info(f"Stage {i}/{len(pipeline_stages)}: {stage.name}")
```

## Naming Conventions

| Category | Convention | Example |
|---|---|---|
| Functions | `verb_noun` | `get_agent`, `run_pipeline`, `validate_brief` |
| Async functions | same as above | `async def fetch_content(url: str)` |
| Classes | PascalCase | `SitePlannerAgent`, `CostTracker` |
| Constants | UPPER_SNAKE | `DEFAULT_TIMEOUT`, `MAX_RETRIES` |
| Private | `_single_underscore` | `_build_prompt`, `_parse_response` |
| Modules | `snake_case` | `site_planner.py`, `cost_tracker.py` |

## Logging

```python
import logging

logger = logging.getLogger(__name__)

# ✅ Use structured log messages
logger.info("Pipeline started", extra={"job_id": job_id, "domain": domain})
logger.error("LLM call failed", extra={"model": model, "error": str(e)}, exc_info=True)

# ❌ Don't use print() in backend code
print("done")  # Replace with logger.debug()
```

## What Not to Do

- **No mutable default arguments** — `def f(items=[])` is a notorious Python bug
- **No `import *`** — always be explicit about what you import
- **No silent `except: pass`** — always log or re-raise
- **No nested functions for one-liners** — use a `lambda` or just inline it
- **No premature caching / memoisation** — profile first, optimise second
