# Agentop Port Registry

> **DRAFT STATUS**: Canonical port assignments and collision prevention protocol.
> This document is the single source of truth for all network ports used by the Agentop system.

## Quick Reference

| Port | Service | Default Bind | Protocol | Status | Notes |
|------|---------|--------------|----------|--------|-------|
| 3000 | Next.js Dashboard (dev) | `localhost` | HTTP | Optional alt | Frontend dev server |
| 3007 | Next.js Dashboard (alt) | `localhost` | HTTP | **Active** | Primary frontend port |
| 3009 | ML Lab Viewer | `localhost` | HTTP | Dev only | WebGen drift monitor (`ml-lab-viewer/`) |
| 5000 | MLflow UI | `localhost` | HTTP | Optional | ML experiment dashboard |
| 5002 | GLM-OCR Sidecar | `localhost` | HTTP | Optional | Document/image OCR |
| 6333 | Qdrant Vector Store | `localhost` | HTTP | Optional | Knowledge semantic search |
| 6379 | Redis | `localhost` | TCP | Optional | Gateway rate limiting — credentials in `.env` |
| 8000 | FastAPI Backend | `127.0.0.1` | HTTP | **Active** | Primary backend API |
| 8100-8999 | Sandbox Backend Range | `127.0.0.1` | HTTP | Dynamic | Per-session allocation |
| 3100-3999 | Sandbox Frontend Range | `localhost` | HTTP | Dynamic | Per-session allocation |
| 8765 | YouTube OAuth Callback | `localhost` | HTTP | Ephemeral | Opened only during token generation |
| 8811 | Docker MCP Gateway | `localhost` | HTTP | Optional | MCP tool gateway |
| 11434 | Ollama LLM | `localhost` | HTTP | **Active** | Local LLM inference |

> **Credential note:** Any port that requires auth (Redis 6379, Qdrant 6333, etc.) — store connection strings in `.env` only, never in docs or code.

## Port Assignments by Component

### Production/Dev Services (Fixed Ports)

```yaml
Frontend Dashboard:
  Port: 3000
  Default: NEXT_PUBLIC_API_URL=http://localhost:8000
  Alternate: 3007 (used in some CORS configs)
  Files:
    - frontend/src/lib/api.ts
    - frontend/src/app/*/page.tsx
    - backend/server.py (CORS origins)

Backend API:
  Port: 8000
  Config: BACKEND_PORT=8000
  Bind: 127.0.0.1 (default, secure)
  Files:
    - backend/config.py
    - backend/server.py
    - README.md

Ollama LLM:
  Port: 11434
  Config: OLLAMA_BASE_URL=http://localhost:11434
  Files:
    - backend/config.py
    - backend/llm/__init__.py

MCP Gateway (optional):
  Port: 8811
  Config: MCP_GATEWAY_PORT=8811  (set in .env)
  Files:
    - backend/config.py
    - backend/mcp/__init__.py

GLM-OCR Sidecar (optional):
  Port: 5002
  Config: GLMOCR_URL=http://localhost:5002  (set in .env)
  Purpose: Document/image OCR via file_reader tool auto-routing
  Files:
    - backend/ocr/__init__.py
    - backend/config.py

Gateway Redis (optional):
  Port: 6379
  Config: GATEWAY_REDIS_URL=redis://localhost:6379/0  (set in .env — includes auth if needed)
  Purpose: Rate limiting for /v1/* gateway routes
  Files:
    - backend/config_gateway.py
  Note: Only active when GATEWAY_ENABLED=true

Qdrant Vector Store (optional):
  Port: 6333
  Config: QDRANT_URL=http://localhost:6333  (set in .env)
  Purpose: Knowledge agent semantic search
  Start: docker run -p 6333:6333 qdrant/qdrant
  Files:
    - backend/knowledge/

MLflow UI (optional):
  Port: 5000
  Purpose: ML experiment tracking dashboard
  Start: mlflow ui --port 5000
  Files:
    - backend/ml/mlflow_tracker.py

YouTube OAuth Callback (ephemeral):
  Port: 8765
  Purpose: Localhost redirect_uri for YouTube OAuth flow — opened temporarily during token generation, not a persistent service
  Files:
    - backend/content/publishers/youtube_auth.py

ML Lab Viewer (standalone WebGen drift monitor):
  Port: 3009
  Start: cd ml-lab-viewer && npm run dev
  Files:
    - ml-lab-viewer/package.json
    - backend/routes/ml_webgen.py  (API routes it calls)
    - backend/config.py            (CORS: localhost:3009 registered)
```

### Sandbox/Isolation Services (Dynamic Port Ranges)

```yaml
Sandbox Backend Instances:
  Range: 8100-8999
  Config: SANDBOX_BACKEND_PORT_RANGE_START=8100
          SANDBOX_BACKEND_PORT_RANGE_END=8999
  Allocation: Runtime per-session
  Files:
    - backend/config.py
    - sandbox/session_manager.py

Sandbox Frontend Preview:
  Range: 3100-3999
  Config: SANDBOX_FRONTEND_PORT_RANGE_START=3100
          SANDBOX_FRONTEND_PORT_RANGE_END=3999
  Allocation: Runtime per-session
  Files:
    - backend/config.py
    - sandbox/session_manager.py
```

### Extension/Integration Services

```yaml
VS Code Extension:
  Backend URL: http://localhost:8000
  Config: agentop.backendUrl
  Files:
    - vscode-extension/package.json
    - vscode-extension/src/extension.ts
    - vscode-extension/README.md

Tauri Desktop:
  Dev Server: http://localhost:3000
  Backend Scope: http://localhost:8000/**
  Files:
    - src-tauri/tauri.conf.json
```

## Port Collision Prevention Protocol

### Problem Statement

We experienced collisions because:
1. Long-running background processes held ports (`uvicorn` from yesterday)
2. Multiple developers starting services on same ports
3. No pre-flight check before attempting bind
4. Silent failures - server starts but on wrong port

### Solution Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Port Collision Prevention System                        │
├─────────────────────────────────────────────────────────┤
│  1. RESERVATION TRACKER (.port-reservations.json)       │
│     - Tracks which process owns which port              │
│     - Auto-cleanup on process death                     │
│                                                          │
│  2. PRE-FLIGHT CHECKER (backend/port_guard.py)          │
│     - Before starting: verify port available            │
│     - Check against reservation registry                │
│     - Provide clear conflict messages                   │
│                                                          │
│  3. LIFECYCLE MANAGER                                   │
│     - On startup: claim port, write reservation         │
│     - On shutdown: release port, cleanup registry       │
│     - Heartbeat: refresh reservation every 30s          │
│                                                          │
│  4. DIAGNOSTIC COMMANDS                                 │
│     - `python -m backend.port_guard status`             │
│     - `python -m backend.port_guard release <port>`     │
│     - `python -m backend.port_guard kill <port>`        │
└─────────────────────────────────────────────────────────┘
```

## Usage

### Starting Services (Correct Way)

```bash
# 1. Check port status first
python -m backend.port_guard status

# 2. Start with port reservation
python -m backend.port_guard serve backend.server:app --port 8000

# Or with explicit reservation:
BACKEND_PORT=8000 python -m backend.port_guard serve backend.server:app
```

### Emergency Port Release

```bash
# If you get "Address already in use" and don't know what owns it:

# See all reservations
python -m backend.port_guard status

# Force release a stuck port
python -m backend.port_guard release 8000

# Kill whatever is using the port
python -m backend.port_guard kill 8000
```

### Environment Variables for Port Control

Port overrides are configured via `.env` (never committed). See `.env` for actual values.

```bash
# Override backend port — set in .env, not in shell history
# BACKEND_PORT=<port>          (see .env)
# NEXT_PUBLIC_API_URL=<url>    (see .env)

# Verify active bind after start
python -m backend.port_guard status
```

## Reserved Port Blocks

| Range | Purpose | Status |
|-------|---------|--------|
| 3000-3009 | Frontend development | Reserved |
| 8000-8009 | Backend API services | Reserved |
| 8100-8999 | Sandbox backend (dynamic) | Allocated |
| 3100-3999 | Sandbox frontend (dynamic) | Allocated |
| 8810-8819 | MCP services | Reserved |
| 11434 | Ollama | External dependency |

## Adding New Ports

**Rule**: Any new port MUST be documented here BEFORE code is merged.

Process:
1. Propose port in PR with justification
2. Update this PORTS.md table
3. Add to port guard registry
4. Update collision prevention ranges if needed

## Troubleshooting

### "Address already in use" errors

```bash
# Find what's using port 8000
lsof -i :8000
# or
ss -ltnp | grep :8000

# Kill all uvicorn instances
pkill -f "uvicorn backend.server:app"

# Use the port guard to force clear
python -m backend.port_guard kill 8000
```

### Multiple instances running

Symptom: API returns old data, routes missing, changes not reflected

```bash
# Check for multiple uvicorn processes
ps aux | grep uvicorn

# Kill via port_guard (correct way — preserves reservation state)
python -m backend.port_guard kill 8000
python -m backend.port_guard serve backend.server:app --port 8000
```

> **Never use `pkill -f uvicorn` directly** — it bypasses port_guard and leaves stale reservations.

### Port works but wrong instance

Symptom: `/api/customers/` returns 404 but `/health` works

Cause: Old server instance without new routes is bound to the port

Fix:
```bash
# Verify which process owns the port
python -m backend.port_guard status

# Kill and restart
python -m backend.port_guard kill 8000
python -m backend.port_guard serve backend.server:app --port 8000
```

---

## Kubernetes Cluster Ports (k8s/ only)

These are pod/service ports inside the `agent-ops` namespace — not exposed on localhost unless you run `kubectl port-forward` explicitly.

| Port | Service | k8s Component | Access |
|------|---------|--------------|--------|
| 8080 | Browser Worker API | `k8s/browser-worker/` | Internal cluster only |
| 6080 | Browser Worker noVNC | `k8s/browser-worker/` | `kubectl port-forward` + VNC viewer |
| 3001 | Uptime Kuma | `k8s/uptime-kuma/` | `kubectl port-forward` |
| 19999 | Netdata | `k8s/netdata/` | `kubectl port-forward` |
| 6060 | AdGuard Home | `k8s/adguard-home/` | `kubectl port-forward` |

> These ports do **not** conflict with local dev services. No reservation in port_guard needed.
