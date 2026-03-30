ModelRouter Component Specification
==================================

1. Python interface  
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


@dataclass(slots=True)
class ModelRequest:
    task_type: Literal["strategic_planning", "architecture", "ui_refinement",
                       "copy", "iteration", "debug", "minor_fix"]
    default_budget_key: str                # e.g. project_id or user_id


@dataclass(slots=True)
class ModelChoice:
    model: Literal["kimi", "opus", "local"]
    reason: str                           # short string for observability


class ISpendTracker(Protocol):
    def spent(self, budget_key: str) -> float: ...


class ModelRouter:
    """
    Decides which LLM backend to invoke given a task type and budget state.
    """
    def __init__(self, spend_tracker: ISpendTracker) -> None:
        ...

    def select(self, req: ModelRequest) -> ModelChoice:
        """
        Pick the model name to call.

        Must consult SpendTracker.
        Must be instantaneous (<1 ms, no I/O beyond SpendTracker.read()).
        Must be pure / deterministic: same inputs -> same output.
        """
```

2. Core logic (step-by-step)  
a. Read current spend: `current = spend_tracker.spent(req.default_budget_key)`  
b. If `current >= 0.90`: return `ModelChoice(model="local", reason="budget_driven")`.  
c. Else:  
    1. Map task→model:  
        - strategic_planning → kimi  
        - architecture → kimi  
        - ui_refinement → opus  
        - copy → opus  
        - iteration → local  
        - debug → local  
        - minor_fix → local  
    2. Return `ModelChoice(model=<mapped>, reason="task_type_based")`.

3. Edge cases handled  
- SpendTracker returns float ≥ 0 (treat negative as 0; overflow is trunc’d by tracker).  
- Unknown task_type → raise ValueError inside `select`.  
- TaskType spelled with different case/surrounding spaces → normalized before mapping.  
- Spend exactly at $0.90 → triggers local (≥).  
- SpendTracker raises any exception → propagate unchanged (let caller decide).  

4. MUST NOT do  
- Network calls, filesystem access, or any blocking I/O beyond SpendTracker.read().  
- Retry logic or queuing—delegate downstream.  
- Cache model selection result.  
- Mutate SpendTracker, TaskClassifier, or any external state.