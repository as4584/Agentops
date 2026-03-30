# backend/agents/ — ★ Core Agentop Orchestration Agents

The Agentop-native infrastructure agents that run the platform itself, not
any specific domain pipeline. These are the agents that govern other agents.

## What lives here

| Agent | ID | Role |
|---|---|---|
| `gatekeeper_agent.py` | `gatekeeper` | Security, policy enforcement, prompt injection defence |
| `gsd_agent.py` | `gsd` | Get Stuff Done — task decomposition, delegation, tracking |

## The ALL_AGENT_DEFINITIONS registry

`backend/agents/__init__.py` exports `ALL_AGENT_DEFINITIONS` — the canonical
dict of every agent the platform knows about. All schedulers, route handlers,
and the orchestrator read from this registry.

**Any new agent in any pillar must be registered here.**

## Conventions

- Core agents do NOT extend `ContentAgent` or `WebgenAgent` — they extend the
  base `Agent` interface directly (or the minimal stub in `__init__.py`)
- Agent IDs are short and unnamespaced: `gatekeeper`, `gsd`, `knowledge_agent`
- These agents run permanently and are started at server boot

## Drift anchors

- Full registry: `docs/AGENT_REGISTRY.md`
- Gatekeeper design: `docs/GATEKEEPER.md`
- GSD methodology: `docs/JACK_CRAIG_METHOD.md`
- A2A protocol: `docs/HYBRID_ARCHITECTURE.md`
