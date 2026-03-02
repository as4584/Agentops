# Agentop — Local-First Multi-Agent Control Center

A production-grade, local-first multi-agent system with **architectural drift governance**, **LangGraph stateful orchestration**, **FastAPI backend**, **Ollama local LLM**, and a **Next.js dashboard**. No cloud dependency. Purely local.

---

## Architecture Overview

```
Next.js Dashboard (localhost:3000)
         │
         │ REST API
         ▼
FastAPI Backend (localhost:8000)
  ├── Drift Guard Middleware (governance enforcement)
  ├── LangGraph Orchestrator (stateful routing)
  │    ├── IT Agent (infrastructure ops)
  │    └── CS Agent (customer support)
  ├── Tool Layer (guarded execution)
  ├── Memory Store (namespaced JSON)
  └── Central Logger (structured logs)
         │
         │ HTTP
         ▼
Ollama LLM (localhost:11434)
```

---

## Quick Start

### Prerequisites

| Requirement | Version  | Purpose            |
|-------------|----------|--------------------|
| Python      | ≥ 3.11   | Backend runtime    |
| Node.js     | ≥ 18     | Frontend runtime   |
| Ollama      | Latest   | Local LLM server   |

### 1. Install Ollama & Pull a Model

```bash
# Install Ollama (https://ollama.com)
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model (default: llama3.2)
ollama pull llama3.2

# Start Ollama server
ollama serve
```

### 2. Start the Backend

```bash
# From project root
pip install -r requirements.txt

# Start FastAPI server on port 8000
python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Start the Frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Open the Dashboard

Navigate to **http://localhost:3000**

---

## Governance Model

This system implements a **documentation-first governance model** to prevent architectural drift. Every structural change must be documented before execution.

### Core Principle

> **Documentation precedes mutation.** No silent architectural changes are permitted.

### Governance Documents

| Document | Purpose |
|----------|---------|
| [docs/SOURCE_OF_TRUTH.md](docs/SOURCE_OF_TRUTH.md) | High-level architecture, agent/tool definitions, data flow |
| [docs/CHANGE_LOG.md](docs/CHANGE_LOG.md) | Chronological record of all structural changes |
| [docs/AGENT_REGISTRY.md](docs/AGENT_REGISTRY.md) | Canonical agent definitions and permissions |
| [docs/DRIFT_GUARD.md](docs/DRIFT_GUARD.md) | Invariants, boundaries, prohibited patterns |

### Architectural Invariants

| ID | Rule |
|----|------|
| INV-1 | LLM layer must not depend on frontend |
| INV-2 | Agents must not directly call each other |
| INV-3 | Tools cannot register new tools dynamically |
| INV-4 | Memory namespaces must not overlap |
| INV-5 | Documentation must precede mutation |
| INV-6 | No agent may modify its own registry entry |
| INV-7 | All tool executions must be logged |
| INV-8 | Dashboard is read-only |
| INV-9 | Shared memory is append-only via orchestrator |
| INV-10 | No circular imports between modules |

### Drift Status Indicator

| Color | Meaning |
|-------|---------|
| 🟢 GREEN | All systems aligned. Documentation matches code. |
| 🟡 YELLOW | Pending documentation update. Operations continue with warning. |
| 🔴 RED | Invariant violation. Execution halted. |

---

## How to Add a New Agent Safely

Follow this exact procedure to avoid drift:

### Step 1: Update Documentation First (INV-5)

1. Add the agent definition to `docs/AGENT_REGISTRY.md`
2. Update the agent table in `docs/SOURCE_OF_TRUTH.md`
3. Add an entry to `docs/CHANGE_LOG.md`
4. Verify the memory namespace is unique (INV-4)

### Step 2: Implement the Agent

1. Create `AgentDefinition` in `backend/agents/__init__.py`
2. Add to the `create_agent()` factory function
3. Add to `get_all_agent_definitions()`

### Step 3: Verify

1. Start the backend — check for namespace collision warnings
2. Open the dashboard — verify agent appears
3. Send a test message — verify response
4. Check drift status — should be GREEN

---

## How to Add a New Tool

### Step 1: Document First

1. Add tool entry to `docs/SOURCE_OF_TRUTH.md` tool table
2. Add entry to `docs/CHANGE_LOG.md`
3. Declare modification type: `READ_ONLY`, `STATE_MODIFY`, or `ARCHITECTURAL_MODIFY`

### Step 2: Implement

1. Create tool function in `backend/tools/__init__.py`
2. Add `ToolDefinition` to `TOOL_REGISTRY`
3. Add to the tool routing in `execute_tool()`
4. Assign to agents in `AGENT_REGISTRY.md`

### Step 3: If ARCHITECTURAL_MODIFY

1. Implement documentation enforcement hook
2. Verify DriftGuard intercepts and validates

---

## How to Modify Architecture

1. **Propose** the change in `CHANGE_LOG.md` with risk assessment
2. **Update** `SOURCE_OF_TRUTH.md` with the new architecture
3. **Check** `DRIFT_GUARD.md` for invariant conflicts
4. **Implement** the change
5. **Verify** drift status is GREEN after implementation

---

## How Drift is Detected

The DriftGuard middleware operates at three levels:

### 1. Tool Call Interception
Every tool call passes through the DriftGuard. If the tool is classified as `ARCHITECTURAL_MODIFY`, the guard checks for a corresponding documentation update.

### 2. Invariant Checking
On each request cycle, the governance check node in the LangGraph state machine validates:
- No namespace overlaps (INV-4)
- No pending documentation updates (INV-5)
- No unresolved violations

### 3. CRITICAL_DRIFT_EVENT
When a critical invariant is violated:
1. Event is logged at ERROR level
2. System is **halted** — no further tool executions
3. Dashboard shows RED drift status
4. Resolution required before operations resume

---

## Project Structure

```
Agentop/
├── backend/
│   ├── __init__.py          # Package init
│   ├── config.py            # Central configuration
│   ├── server.py            # FastAPI application
│   ├── agents/
│   │   └── __init__.py      # Agent definitions (IT, CS)
│   ├── llm/
│   │   └── __init__.py      # Ollama client
│   ├── memory/
│   │   └── __init__.py      # Namespaced JSON store
│   ├── middleware/
│   │   └── __init__.py      # DriftGuard governance
│   ├── models/
│   │   └── __init__.py      # Pydantic data models
│   ├── orchestrator/
│   │   └── __init__.py      # LangGraph state machine
│   ├── tools/
│   │   └── __init__.py      # Guarded tool implementations
│   └── utils/
│       └── __init__.py      # Central logger
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── next.config.js
│   └── src/
│       ├── lib/
│       │   └── api.ts       # API client
│       └── app/
│           ├── layout.tsx
│           ├── globals.css
│           └── page.tsx      # Dashboard
├── docs/
│   ├── SOURCE_OF_TRUTH.md   # System architecture
│   ├── CHANGE_LOG.md        # Change history
│   ├── AGENT_REGISTRY.md    # Agent definitions
│   └── DRIFT_GUARD.md       # Invariants & rules
├── src-tauri/
│   └── tauri.conf.json      # Tauri desktop config
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Tauri Desktop Wrapping

The frontend is Tauri-ready for desktop deployment:

```bash
# Build static export for Tauri
cd frontend
TAURI_BUILD=true npm run build

# Initialize Tauri (requires Rust toolchain)
cargo install tauri-cli
cargo tauri dev
```

The Tauri config restricts HTTP access to `localhost:8000` only — maintaining the local-first constraint.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Default LLM model |
| `OLLAMA_TIMEOUT` | `120` | LLM request timeout (seconds) |
| `BACKEND_HOST` | `0.0.0.0` | Backend bind address |
| `BACKEND_PORT` | `8000` | Backend port |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/status` | Full system status |
| POST | `/chat` | Send message to agent |
| GET | `/agents` | List all agents |
| GET | `/agents/{id}` | Get agent details |
| GET | `/tools` | List all tools |
| GET | `/drift` | Drift report |
| GET | `/drift/events` | Drift events |
| GET | `/logs` | Tool execution logs |
| GET | `/memory` | Memory namespaces |
| GET | `/memory/{ns}` | Namespace data |
| GET | `/events` | Shared events |

---

## Design Principles

1. **Local-first**: No cloud, no paid APIs, no external dependencies at runtime
2. **Documentation-first**: Documentation precedes code mutation
3. **Agent isolation**: Strict namespace and tool boundaries
4. **Observable**: Every action logged, every state visible
5. **Drift-resistant**: Architectural invariants enforced automatically
6. **Modular**: Clean separation of concerns with no circular dependencies
7. **Typed**: Full Python type hints, TypeScript frontend
