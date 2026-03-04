===============================
1. Python Interface
===============================
File: agent_control_routes.py

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, StrictStr

class AgentStatusResponse(BaseModel):
    agent_id: StrictStr
    status:  StrictStr   # "running" OR "stopped"
    message: StrictStr   # success / already / error text

router: APIRouter = APIRouter(prefix="/agents", tags=["agents"])

# Methods bound to router below
# -------------------------------------------------
# POST /agents/{agent_id}/start -> AgentStatusResponse
# POST /agents/{agent_id}/stop  -> AgentStatusResponse
```

===============================
2. Core Logic
===============================
File: agent_control_routes.py (method bodies)

Assumption: an external singleton registry object named `AgentRegistry` is injected that implements:

```python
class AgentRegistry:
    async def get_status(self, agent_id: str) -> str:  # "running"|"stopped"
        ...
    async def start_agent(self, agent_id: str) -> None:
        ...
    async def stop_agent(self, agent_id: str) -> None:
        ...
```

Step-by-step for `/start`:

1. Receive POST request at `/agents/{agent_id}/start`.
2. Call `AgentRegistry.get_status(agent_id)`.
3. If step 2 raises KeyError → raise FastAPI 404.
4. If returned status == "running" → return 200 with payload  
   `AgentStatusResponse(agent_id=..., status="running", message="already running")`.
5. Otherwise call `AgentRegistry.start_agent(agent_id)`.
6. Return 200 payload  
   `AgentStatusResponse(agent_id=..., status="running", message="started")`.

Step-by-step for `/stop` is identical, substituting `stop_agent()` call, target message “already stopped”, final status "stopped".

Mounting in main FastAPI app **outside** this router:

```python
from agent_control_routes import router as agent_control_router
app.include_router(agent_control_router)
```

===============================
3. Edge Cases Handled
===============================
- agent_id not found → 404  
- agent already in requested state → 200 with “already ...” message  
- AgentRegistry raises any exception → propagate 500 (FastAPI default).  
- Malformed or non-string agent_id handled by FastAPI path conversion, returns 422 automatically.  

===============================
4. Explicit Non-Responsibilities
===============================
- MUST NOT persist state to disk.  
- MUST NOT schedule or manage threads/processes internally.  
- MUST NOT perform health or deep supervision of agents.  
- MUST NOT expose any endpoints other than described.