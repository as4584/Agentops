# backend/memory/ — Memory Store Module

Python module providing namespaced JSON persistence for all agents.
**This is code only** — the actual runtime data lives in `data/agents/`.

## What lives here

| File | Role |
|---|---|
| `__init__.py` | `MemoryStore` class — namespaced read/write/append/delete |

## Key design rules (INV-4, INV-9)

- Each agent gets its own isolated namespace (directory inside `data/agents/`)
- Cross-namespace reads are **prohibited** — agents can only read their own data
- The `shared` namespace is the only cross-agent write target, and it is
  **append-only**, exclusively writable by the orchestrator (INV-9)
- `MEMORY_DIR` in `backend/config.py` controls where data directories are
  created (currently `data/agents/`)

## Usage

```python
from backend.memory import MemoryStore

store = MemoryStore()
store.write("my_agent", "last_result", {"status": "ok"})
value = store.read("my_agent", "last_result")
```

## Drift anchors

- Data directory: `data/agents/`
- Drift rules: `docs/DRIFT_GUARD.md` §4 (INV-4), §9 (INV-9)
