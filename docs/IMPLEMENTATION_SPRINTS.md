# IMPLEMENTATION SPRINTS — Customer Ops + Unified LLM Registry

> Scope: First executable slice of the multi-tenant/customer operations platform requested by owner.
> Date: 2026-03-04

---

## Sprint A (Completed)

### Objectives
- Add unified model/provider registry (Ollama + OpenRouter + OpenAI placeholder + Copilot placeholder)
- Add customer data layer and service assignment API
- Add customer operations UI page with + service assignment flow + confirmation modal
- Stabilize missing route imports that blocked startup and API wiring

### Delivered
- `backend/llm/unified_registry.py`
  - Canonical model specs by provider
  - Task-to-model defaults
  - Unified `generate()` adapter
  - Endpoints exposed at `/llm/registry/models` and `/llm/registry/generate`
- `backend/models/customer.py`
  - Customer, service, and request schemas
- `backend/database/customer_store.py`
  - SQLite store for customers/services/usage
- `backend/routes/customers.py`
  - Create/list/get customer
  - Add service (+ assigns subagent set)
  - Increment token usage
  - Dashboard summary stats
- `frontend/src/app/customers/page.tsx`
  - Simple operations UI
  - Add customer form
  - + button to select service and confirm assignment
  - Per-customer token usage progress bar
- Route modules restored:
  - `backend/routes/agent_control.py`
  - `backend/routes/task_management.py`
  - `backend/routes/memory_management.py`
  - `backend/routes/content_pipeline.py`
  - `backend/routes/llm_registry.py`

### Acceptance Criteria Met
- Owner can create customer records
- Owner can click + and assign a service with confirmation
- Owner can see current token usage per customer
- API has a unified, callable model registry endpoint

---

## Sprint B (Next)

### Objectives
- Add customer profile detail screen with website/social links and active agents
- Persist service execution events + task timeline per service
- Wire service assignment to orchestrator task fan-out (currently logs task creation)
- Add pricing calculator screen in dashboard

### Status Update (2026-03-04)
- Implemented customer profile detail UI at `frontend/src/app/customers/[customerId]/page.tsx`
- Implemented service timeline persistence and endpoint via `service_events` table + `GET /api/customers/{customer_id}/services/{service_id}/timeline`
- Upgraded service assignment fan-out to create parent + child subagent tasks and timeline events
- Implemented pricing calculator screen at `frontend/src/app/pricing/page.tsx`
- Added profile navigation from customer list (`frontend/src/app/customers/page.tsx`)

### Key Specs
- Service state machine: `pending -> in_progress -> completed|failed`
- Task lineage: every service assignment must emit one parent task + child agent tasks
- Customer profile sections: Overview, Services, Agents, Token Usage, Assets

---

## Sprint C (Next)

### Objectives
- Build Website Maker screen (`/webgen`) with 90% generation + edit + deploy workflow
- Add Vercel deployment endpoint and deployment history per customer
- Generate and store QR code for deployed site

### Status Update (2026-03-04)
- Implemented `frontend/src/app/webgen/page.tsx` for generate → edit → deploy flow
- Added backend API module `backend/routes/webgen_builder.py` with endpoints:
  - `POST /api/webgen/generate`
  - `GET /api/webgen/projects`
  - `GET /api/webgen/projects/{project_id}`
  - `PUT /api/webgen/projects/{project_id}/page`
  - `POST /api/webgen/deploy`
  - `POST /api/webgen/qr`
- Added Vercel CLI deployment support and deployment URL persistence to project metadata
- Added QR generation output path under `output/qr/{project_id}/deploy_qr.png`
- Wired router registration in `backend/server.py`

### Status Update (2026-03-04, Deployment Lineage)
- Added `customer_deployments` persistence table in `backend/database/customer_store.py`
- Added customer deployment API endpoint: `GET /api/customers/{customer_id}/deployments`
- Updated `POST /api/webgen/generate` to persist optional `customer_id` in project metadata
- Updated `POST /api/webgen/deploy` to auto-link deployments to customer, persist `qr_path`, and return linkage metadata
- Updated customer profile assets tab (`frontend/src/app/customers/[customerId]/page.tsx`) to display deployment history
- Updated webgen page (`frontend/src/app/webgen/page.tsx`) with optional linked-customer selection and customer-aware deploy

### Status Update (2026-03-04, Deployment UX)
- Added secure QR file retrieval endpoint: `GET /api/webgen/qr/file?path=...`
- Added one-click `Open QR` action from customer deployment history rows
- Added deployment search/filter controls in customer profile (query + QR presence)
- Added `webgenQrFileUrl()` helper in frontend API client for consistent QR links

### Key Specs
- 3-stage flow: Generate -> Edit -> Deploy
- Deploy metadata: URL, commit hash or snapshot ID, deploy timestamp, customer_id
- QR output saved under `output/qr/{customer_id}/`

---

## Sprint D (Next)

### Objectives
- Marketing site deployment + AI assistant + FAQ wall
- Connect assistant to unified model registry and system FAQ corpus
- Business-facing copy aligned with package tiers

### Status Update (2026-03-04)
- Implemented backend marketing API module `backend/routes/marketing.py`:
  - `GET /api/marketing/faq`
  - `POST /api/marketing/ask`
  - `POST /api/marketing/deploy`
- Implemented marketing console UI `frontend/src/app/marketing/page.tsx`:
  - FAQ wall
  - AI assistant prompt panel
  - Deploy + QR trigger
- Added customer-context personalization to assistant Q&A:
  - `POST /api/marketing/ask` now accepts optional `customer_id`
  - Assistant prompt now injects selected customer tier, services, token usage, and assets
  - Marketing UI now includes a customer selector for demo-specific responses
- Added dashboard quick-launch links in `frontend/src/app/page.tsx` for:
  - `/customers`, `/pricing`, `/webgen`, `/marketing`
- Registered marketing router in `backend/server.py`

### Key Specs
- Website is intentionally simple and trust-first
- FAQ answers should resolve from canonical docs before model synthesis
- Assistant must return concise and transparent responses about system behavior

---

## Drift/Governance Notes
- New mutation routes are explicit and auditable
- No agent-to-agent direct calls were introduced
- All LLM access for new registry path is centralized in `unified_registry.py`
- Future architecture changes must update:
  - `docs/SOURCE_OF_TRUTH.md`
  - `docs/AGENT_REGISTRY.md`
  - `docs/CHANGE_LOG.md`

---

## Runtime Hardening (2026-03-04)

### Objectives
- Eliminate recurring local port collisions across backend/frontend/dev tooling
- Add deterministic port visibility and diagnostics
- Prevent launcher from killing unrelated non-Agentop processes

### Delivered
- Added canonical port registry doc: `PORTS.md`
- Added collision tool: `backend/port_guard.py`
  - `status`, `serve`, `claim`, `release`, `kill`
  - stale reservation cleanup and process ownership diagnostics
- Added preflight script: `scripts/port-check.sh`
- Hardened desktop launcher `app.py`:
  - process ownership checks before kill
  - fallback backend port selection (`8765-8799`) when 8000 is externally occupied
  - fallback dashboard port selection (`3008-3099`) when 3007 is externally occupied
  - dynamic `NEXT_PUBLIC_API_URL` wiring for fallback backend port
- Clarified backend startup logs in `backend/server.py` (configured port vs actual bind)

### Key Specs
- Do not kill foreign processes bound to default ports
- Prefer fallback ports over destructive behavior
- Keep startup observable with explicit owner/process diagnostics

---

## Security Hardening (2026-03-04)

### Objectives
- Remediate SECURITY_AUDIT.md findings before any further feature development
- Close all CRITICAL/HIGH vulnerabilities; reduce attack surface across MEDIUM/LOW

### Sprint 1 — Path Traversal & Authentication (P0)

**Files modified:** `backend/server.py`, `backend/routes/webgen_builder.py`, `backend/tools/__init__.py`

| Finding | Fix |
|---------|-----|
| PATH-001 — `/folders/browse` path traversal | `resolve()` → `os.path.normpath()`; bounds check now bypass-proof |
| PATH-002 — QR file path traversal | Same fix in `_resolve_qr_file_path()` |
| All `resolve()` calls on user paths in tools layer | Replaced across 7 call sites in `tools/__init__.py` |

Auth: Added startup warning when `AGENTOP_API_SECRET` is unset.

### Sprint 2 — Input Validation & Tiered Rate Limiting (P1)

**Files modified:** `backend/security_middleware.py`, `backend/config.py`, `backend/models/customer.py`, `backend/server.py`

| Change | Detail |
|--------|--------|
| `TieredRateLimitMiddleware` | LLM endpoints: 30 RPM / General: 600 RPM (per-IP, sliding window) |
| `LLM_RATE_LIMIT_RPM` env var | Default 30; controls LLM endpoint tier |
| `CustomerCreate` validators | `@field_validator` — strips whitespace, blocks `<>"';&|`, normalises email |
| Prompt injection heuristic | Chat endpoint blocks common override phrases (10 patterns) |

LLM endpoints rate-limited at 30 RPM: `/chat`, `/agents/message`, `/llm/generate`, `/campaign/generate`, `/intake/start`, `/intake/answer`

### Sprint 3 — Error Sanitization & Secure Temp Files (P1)

**Files modified:** `backend/server.py`, `backend/port_guard.py`

| Change | Detail |
|--------|--------|
| Global exception handler | Returns `{"error": "Internal server error", "request_id": "<8-char>"}` — no paths/stack traces |
| Secure temp file creation | `tempfile.mkstemp()` + `chmod 0o600` in `PortRegistry._save()` |

### Sprint 4 — CORS Hardening & Security Headers (P2)

**Files modified:** `backend/config.py`, `backend/server.py`, `backend/security_middleware.py`

| Change | Detail |
|--------|--------|
| `AGENTOP_CORS_ORIGINS` env var | Comma-separated origin list; wildcard `*` rejected; falls back to `localhost:3007` |
| `SecurityHeadersMiddleware` expanded | Added `Strict-Transport-Security`, `Permissions-Policy`, tightened `Content-Security-Policy`, `Cache-Control: no-store` |

### Open Item

CMD-001 (subprocess `cwd` validation before `vercel` CLI call in `webgen_builder.py` / `marketing.py`) is deferred to a future sprint.

---

## OpenClaw Adoption Track (2026-03-06)

### Objectives
- Implement owner-selected OpenClaw-inspired capabilities: **1, 3, 4, 5, 7, 8, 9, 10**
- Preserve current Agentop invariants and avoid REST API regressions
- Phase in Docker-backed sandboxing without disrupting existing sandbox/playbox flow

### Planning Artifacts
- Master spec + sprint breakdown: `docs/OPENCLAW_ADOPTION_SPECS.md`
- Sandbox implementation runbook: `docs/SANDBOX_SETUP.md`

### Locked Execution Order
1. Feature 10 — Model Failover & Profile Rotation
2. Feature 9 — Cron + Webhook Automation
3. Feature 3 — Skills Platform v2
4. Feature 7 — Agent-to-Agent Messaging
5. Feature 8 — Per-Session Docker Sandboxing
6. Feature 1 — WebSocket Control Plane
7. Feature 4 — Browser Control
8. Feature 5 — Canvas + A2UI

### Delivery Notes
- This track is intentionally split into small Codex-executable sprints with explicit file targets, tests, and acceptance criteria.
- Any tool-permission change must update `docs/AGENT_REGISTRY.md`.
- Any architectural invariant change must update `docs/SOURCE_OF_TRUTH.md`.
