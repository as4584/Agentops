# MemoryManagementRoutes Specification

## 1. Python Interface

```python
from typing import Dict, List
from uuid import UUID
from fastapi import APIRouter
from pydantic import BaseModel

# Response Models
class DeleteResponse(BaseModel):
    namespace: str
    entries_deleted: int

class EventsClearResponse(BaseModel):
    events_cleared: int

class MemoryStatEntry(BaseModel):
    agent_id: UUID
    namespace: str
    size_bytes: int

# Request/Response Models
NamespaceContent = Dict[str, Dict]

# Router Interface
class MemoryManagementRoutes:
    def __init__(self, memory_service: MemoryServiceInterface):
        self.router = APIRouter(prefix="/memory", tags=["memory"])
        
    def _delete_namespace(self, namespace: str) -> DeleteResponse:
        pass
        
    def _clear_events(self) -> EventsClearResponse:
        pass
        
    def _get_namespace(self, namespace: str) -> NamespaceContent:
        pass
        
    def _get_stats(self) -> List[MemoryStatEntry]:
        pass
```

## 2. Core Logic

### Router Setup
1. Initialize APIRouter with prefix "/memory" and tags ["memory"]
2. Register routes with appropriate HTTP methods and paths

### DELETE /memory/{namespace}
1. Validate namespace parameter is non-empty string
2. Call memory_service.delete_namespace(namespace)
3. If namespace doesn't exist, raise HTTPException with status 404
4. Return DeleteResponse with namespace and count of deleted entries

### DELETE /memory/events
1. Call memory_service.clear_events()
2. Return EventsClearResponse with count of cleared events

### GET /memory/{namespace}
1. Validate namespace parameter is non-empty string
2. Call memory_service.get_namespace(namespace)
3. If namespace doesn't exist, raise HTTPException with status 404
4. Return namespace contents as dict structure

### GET /memory/stats
1. Call memory_service.get_all_namespaces_stats()
2. Convert stats to list of MemoryStatEntry objects
3. Sort by size_bytes in descending order
4. Return sorted list

## 3. Edge Cases Handled

1. **Empty namespace parameter**: Validate namespace is non-empty string in both GET and DELETE operations
2. **Non-existent namespace**: Return 404 status code for both GET and DELETE operations
3. **Stats with no data**: Return empty list when no namespaces exist
4. **Zero events to clear**: Return events_cleared=0 response
5. **Case sensitivity**: Treat namespace strings as case-sensitive for exact matching
6. **Invalid UUID in stats**: Skip any entries with malformed agent_id

## 4. What It Must NOT Do

1. NOT create any namespaces (only read/delete existing ones)
2. NOT provide CRUD operations for individual memory entries within namespaces
3. NOT implement authentication or authorization
4. NOT handle actual memory storage (delegates to memory_service)
5. NOT modify agent_id formatting in stats
6. NOT cache responses or implement rate limiting
7. NOT log internal operation details