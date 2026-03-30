# backend/

FastAPI Python backend for the Agentop platform. This is the platform core —
routing, agent infrastructure, LLM integration, memory, and all domain
pipelines live here.

## Architecture pillars

```
backend/
  ├── content/         ★ PILLAR — Content Creation pipeline & agents
  ├── webgen/          ★ PILLAR — Website Generation pipeline & agents
  ├── agents/          ★ PILLAR — Core Agentop orchestration agents
  │
  ├── orchestrator/    Agent lifecycle & A2A dispatch
  ├── gateway/         MCP/AI gateway — ACL, auth, rate limiting, streaming
  ├── routes/          FastAPI routers (one per domain)
  ├── memory/          MemoryStore Python module (data lives in data/agents/)
  ├── llm/             LLM client registry & profiles
  ├── database/        SQLite stores (customers, gsd)
  ├── skills/          Skill loader & registry
  ├── a2ui/            Agent-to-UI messaging bus
  ├── websocket/       WebSocket control plane hub
  ├── browser/         Browser automation tooling
  ├── knowledge/       Knowledge base (LLM model catalogue)
  ├── middleware/       Drift guard middleware
  ├── mcp/             MCP bridge to Docker MCP Gateway
  ├── tools/           Tool execution & TOOL_REGISTRY
  ├── models/          Pydantic shared models
  ├── utils/           Tool IDs, validation, logger
  └── tests/           All backend tests
```

## Key invariants (see `docs/DRIFT_GUARD.md` for full list)

- **INV-1**: All LLM calls go through `backend/llm/unified_registry.py`
- **INV-4**: Agent memory namespaces are isolated — no cross-namespace reads
- **INV-9**: Shared memory is append-only via orchestrator
- **INV-12**: All routes must be registered in `server.py`; no route auto-discovery

## Adding a new domain pillar

1. Create `backend/<pillar>/` with its own `__init__.py` and `README.md`
2. Add domain agents under `backend/<pillar>/agents/`
3. Add a route file under `backend/routes/<pillar>_routes.py` (or `<pillar>.py` if simple)
4. Register the router in `backend/server.py`
5. Update this README and `docs/AGENT_REGISTRY.md`
