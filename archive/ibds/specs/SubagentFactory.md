SubagentFactory – Specification (and only this component)

────────────────────────────────────────
1. Python interface
────────────────────────────────────────
```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, List, Dict, Any, Optional

class MemoryScope(Protocol):
    """Opaque memory slice that exposes NOTHING except an internal handle."""
    ...

@dataclass(frozen=True)
class AgentTemplate:
    role: str
    system_prompt: str
    allowed_tools: List[str]
    memory_scope: MemoryScope
    cost_ceiling: Optional[float] = None
    escalation_model: str = "default"

class AgentInstance(Protocol):
    """Minimal agent contract. Implementation is outside this spec."""
    def id(self) -> str: ...
    async def run(self, payload: Dict[str, Any]) -> Dict[str, Any]: ...

class SubagentFactory(Protocol):
    """
    A factory that turns an AgentTemplate into a live AgentInstance **without**
    leaking global or non-assigned memory.
    """
    async def spawn(self, template: AgentTemplate) -> AgentInstance:
        """Create and begin agent lifecycle."""
        ...

    async def monitor(self, instance_id: str) -> Optional[AgentInstance]:
        """Return a live instance if already spawned, else None."""
        ...
```

────────────────────────────────────────
2. Core logic – step by step
────────────────────────────────────────
Step 0 – Initialization  
- An `InMemoryAgentMap` Dict[str, AgentInstance] is held internally (thread-safe via lock-free async map or concurrent dictionary).

Step 1 – Input validation  
- Verify that `template.allowed_tools` ⊂ known_tool_registry (Fail fast → `ValueError`).  
- Verify that `template.cost_ceiling is None or 0 ≤ template.cost_ceiling ≤ global_max_cost`.  
- Verify that `template.memory_scope` is not `None` and matches expected MemoryScope type.

Step 2 – Memory guardrail  
- Create a **sealed scope handle** = clone(template.memory_scope).  
- Ensure scope has no implicit reference to any other context slice.

Step 3 – Agent constructor  
- Locate concrete agent class via a registry keyed by `template.role`.  
- Inject only:  
  - `system_prompt`  
  - `allowed_tools`  
  - `cost_ceiling`  
  - `escalation_model`  
  - the **cloned** MemoryScope (`sealed_scope`).  
- The constructor must return an object that satisfies `AgentInstance`.

Step 4 – Lifecycle init  
- Call the agent’s internal `init()` (async).  
- Add resulting instance to `InMemoryAgentMap`.  
- Return the `AgentInstance`.

Step 5 – Monitor  
- O(1) lookup in `InMemoryAgentMap`.

────────────────────────────────────────
3. Edge cases handled
────────────────────────────────────────
1. Duplicate spawn with same template ID → raises `DuplicateAgentError`.
2. Tool in `allowed_tools` misspelled → raises `UnknownToolError`.
3. Negative or non-numeric cost_ceiling → `InvalidCeilingError`.
4. `memory_scope` clone fails (e.g., out of memory limits) → `MemoryScopeError`.
5. Constructor throws during Agent instantiation → bubbles up as `AgentInitError`.
6. Concurrent `spawn` of two identical templates → second one blocked by async lock on InMemoryAgentMap key.

────────────────────────────────────────
4. Explicit Non-responsibilities
────────────────────────────────────────
- The SubagentFactory does **NOT** provide full-context access, storage, or retrieval.  
- It does **NOT** monitor run-time cost enforcement; that is the agent’s job.  
- It does **NOT** decide when to escalate; only the created agent uses the provided escalation_model.  
- It does **NOT** perform inference or agent inference loops.  
- It does **NOT** manage tool execution details.