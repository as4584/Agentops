# data/

Runtime data store for the Agentop platform. **Not source code.**

This directory is created automatically at startup and is excluded from git.
To restore a fresh environment: `mkdir -p data/agents`

## Structure

```
data/
  agents/           # Namespaced JSON memory stores — one folder per agent
  customers.db      # SQLite customer database (created on first run)
  scheduler.db      # APScheduler job persistence (created on first run)
  webhooks.json     # Webhook registrations (created on first run)
```

## Agent memory namespaces (`data/agents/`)

Each agent writes to its own isolated subdirectory via `backend/memory/`.
Cross-namespace reads are prohibited (INV-4, see `docs/DRIFT_GUARD.md`).

The namespace name matches the agent ID used in the agent registry
(`docs/AGENT_REGISTRY.md`).

## Conventions

- **Never manually edit** agent store files while the server is running.
- Schema changes must be documented in `docs/CHANGE_LOG.md`.
- The `data/agents/shared/` namespace is the only cross-agent write target
  and is append-only via the orchestrator (INV-9).
