PYTHON INTERFACE (type stubs)

```py
from typing import Dict, TypedDict
from fastapi import APIRouter
from pydantic import BaseModel
from datetime import datetime

# Pydantic models ― wire protocol
class TaskCreateRequest(BaseModel):
    agent_id: str
    action: str
    payload: Dict[str, object]

class TaskResponse(BaseModel):
    task_id: str
    status: str  # queued | running | completed | cancelled
    created_at: datetime

# Router contract
router: APIRouter
```

CORE LOGIC (step-by-step)

1. Boot
   1.1 Instantiate router = APIRouter(prefix="/tasks", tags=["tasks"])
   1.2 In-memory store: _tasks: dict[str, dict] = {}

2. POST /tasks
   2.1 Receive TaskCreateRequest body.
   2.2 Generate UUID4 → task_id.
   2.3 created_at = datetime.utcnow().
   2.4 status = "queued".
   2.5 Persist: _tasks[task_id] = { "agent_id", "action", "payload", "status", "created_at" }.
   2.6 Return TaskResponse.

3. DELETE /tasks/{task_id}
   3.1 Lookup task in _tasks.
   3.2 If absent → raise HTTPException(status_code=404).
   3.3 If status in {"running", "completed"} → raise HTTPException(status_code=409).
   3.4 Update status = "cancelled".
   3.5 Return 200 (empty body).

EDGE CASES IT MUST HANDLE
- UUID collision (theoretical only).
- Concurrent DELETE on same task (idempotent already handled since status becomes "cancelled").
- Malformed JSON (caught by Pydantic automatically).

WHAT IT MUST NOT DO
- Persist to file/database.
- Communicate with or invoke agents.
- Enforce policy/authorization.
- Schedule or execute queued tasks.