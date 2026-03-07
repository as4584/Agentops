# Agentop OpenClaw Adoption Specs + Codex Sprint Plan

> Date: 2026-03-06  
> Scope: Features selected by owner — **1, 3, 4, 5, 7, 8, 9, 10**  
> Intent: Provide implementation-ready specs and micro-sprints for Codex.  
> Constraint: Respect existing architecture and governance in `docs/SOURCE_OF_TRUTH.md`.

---

## 0) Executive Decisions (Locked)

### 0.1 Build Strategy
- Keep REST API as system-of-record for CRUD and deterministic operations.
- Add WebSocket control plane for real-time eventing only.
- Keep all agent orchestration authority in `backend/orchestrator/__init__.py`.
- Preserve DriftGuard + Gatekeeper constraints as non-optional.

### 0.2 Delivery Order (Critical)
1. Feature 10 — Model Failover & Profile Rotation
2. Feature 9 — Cron + Webhook Automation
3. Feature 3 — Skills Platform v2
4. Feature 7 — Agent-to-Agent Messaging
5. Feature 8 — Per-Session Docker Sandboxing
6. Feature 1 — WebSocket Control Plane
7. Feature 4 — Browser Control (CDP/Playwright)
8. Feature 5 — Canvas + A2UI

### 0.3 Global Non-Goals
- No full rewrite of orchestrator.
- No breaking changes to existing REST routes.
- No removal of current sandbox/playbox flow.
- No multi-channel integrations in this phase.

---

## 1) Feature 10 — Model Failover & Profile Rotation

### Problem
Current model routing has limited graceful degradation when a provider/model fails or budget exhausts.

### Goal
Introduce deterministic fallback chains, circuit-breaker health, and credential profile rotation.

### Target Files
- `backend/llm/unified_registry.py`
- `lib/localllm/cloud_client.py`
- `backend/config.py`
- `backend/server.py`
- `backend/tests/test_model_failover.py` (new)
- `backend/tests/test_profile_rotation.py` (new)

### Data Contracts
```python
@dataclass
class ModelHealthState:
    model_id: str
    healthy: bool = True
    consecutive_failures: int = 0
    circuit_open: bool = False
    circuit_opened_at: float = 0.0
    last_error: str | None = None

@dataclass
class CredentialProfile:
    profile_id: str
    provider: str               # openrouter|openai|anthropic
    auth_type: str              # api_key|oauth
    token: str
    monthly_budget_usd: float
    spend_this_month: float
    active: bool = True
```

### Sprint 10.1 — Health + Circuit Breaker
Tasks:
1. Add `ModelHealthState` and `_health_map` to `UnifiedModelRouter`.
2. Implement `_record_success()`, `_record_failure()`, `_is_circuit_open()`.
3. Add env vars:
   - `LLM_CIRCUIT_FAILURE_THRESHOLD=3`
   - `LLM_CIRCUIT_RESET_SECONDS=300`
4. Expose health summary via `/llm/stats` response.

Acceptance:
- 3 consecutive failures opens circuit.
- Open circuit suppresses calls until reset window elapses.

### Sprint 10.2 — Ordered Fallback Execution
Tasks:
1. Extend model spec with `fallback_chain: list[str]`.
2. Refactor `generate()` to evaluate `[primary] + fallback_chain`.
3. On fallback success annotate response metadata:
   - `fallback_used=true`
   - `effective_model=<fallback_model_id>`
4. Implement explicit terminal exception `AllModelsFailedError`.

Acceptance:
- Primary failure + healthy fallback returns successful response.
- Exhaustion raises `AllModelsFailedError` with attempted chain.

### Sprint 10.3 — Profile Rotation
Tasks:
1. Add `ProfileRotator` helper in `backend/llm/profiles.py`.
2. Load provider credentials from env patterns:
   - `OPENROUTER_API_KEY`
   - `OPENROUTER_API_KEY_1..9`
   - `OPENAI_API_KEY_1..9`
   - `ANTHROPIC_API_KEY_1..9`
3. Round-robin active profiles per provider.
4. Persist monthly spend state to `backend/memory/llm_profiles.json`.

Acceptance:
- Requests rotate profile IDs under same provider.
- Over-budget profiles auto-deactivate.

### Sprint 10.4 — Regression + Dashboard Visibility
Tasks:
1. Add tests for fallback chain behavior and circuit reset timing.
2. Add tests for profile round-robin and budget deactivation.
3. Add frontend panel for model health badges (System tab).

Acceptance:
- Visual confirmation of open/closed circuits per model.

---

## 2) Feature 9 — Cron + Webhook Automation

### Problem
No persistent job scheduler for autonomous triggers; webhook ingestion is fragmented.

### Goal
Persistent scheduler + signed webhooks routing into orchestrator.

### Target Files
- `backend/scheduler.py` (new)
- `backend/routes/scheduler.py` (new)
- `backend/routes/webhooks.py` (new)
- `backend/server.py`
- `requirements.txt`, `pyproject.toml`
- `backend/tests/test_scheduler.py` (new)
- `backend/tests/test_webhooks.py` (new)

### Sprint 9.1 — Scheduler Kernel
Tasks:
1. Add `apscheduler` dependency.
2. Create `AgentopScheduler` wrapper around `AsyncIOScheduler`.
3. Use SQLite jobstore at `backend/memory/scheduler.db`.
4. Start/stop scheduler in FastAPI lifespan.

Acceptance:
- Jobs survive process restart.

### Sprint 9.2 — Scheduler REST API
Endpoints:
- `GET /scheduler/jobs`
- `POST /scheduler/jobs`
- `GET /scheduler/jobs/{job_id}`
- `PATCH /scheduler/jobs/{job_id}/pause`
- `PATCH /scheduler/jobs/{job_id}/resume`
- `DELETE /scheduler/jobs/{job_id}`

Validation:
- `agent_id` must exist in orchestrator registry.
- Cron expressions validated via `CronTrigger.from_crontab`.

Acceptance:
- Invalid cron returns 422.
- Unknown `agent_id` returns 404.

### Sprint 9.3 — Signed Inbound Webhooks
Endpoints:
- `POST /webhooks/register`
- `GET /webhooks`
- `DELETE /webhooks/{webhook_id}`
- `POST /webhooks/{webhook_id}`

Security:
- Require `X-Agentop-Signature` header.
- Verify HMAC-SHA256 over raw body.
- Reject mismatch with 401.

Dispatch:
- Template payload into message, forward to `_orchestrator.process_message(...)`.

Acceptance:
- Valid signature triggers agent run.
- Invalid signature rejected.

### Sprint 9.4 — Observability + Rate Limits
Tasks:
1. Log scheduler/webhook events into `backend/logs/system.jsonl` with `event_type`.
2. Add per-webhook request rate cap.
3. Add dry-run mode: `POST /webhooks/{id}?dry_run=true`.

Acceptance:
- Operators can inspect run history and failures.

---

## 3) Feature 3 — Skills Platform v2 (Prompt-Injected Skills)

### Problem
Capabilities are currently embedded; there is no modular installable skill surface.

### Goal
Introduce local skill manifests and prompt injection with guardrails.

### Target Files
- `backend/skills/registry.py` (new)
- `backend/skills/loader.py` (new)
- `backend/routes/skills.py` (new)
- `backend/agents/__init__.py`
- `backend/tests/test_skills_registry.py` (new)
- `docs/AGENT_REGISTRY.md` (update)

### Skill Package Structure
```
skills/
  <skill_slug>/
    SKILL.md
    TOOLS.md
    SOUL.md
    skill.json
```

### `skill.json` Schema
```json
{
  "id": "web_research",
  "name": "Web Research",
  "version": "1.0.0",
  "description": "Adds retrieval and citation behavior",
  "allowed_agents": ["knowledge_agent", "cs_agent"],
  "required_tools": ["mcp_fetch_get"],
  "risk_level": "medium",
  "enabled": true
}
```

### Sprint 3.1 — Skill Loader + Validation
Tasks:
1. Implement filesystem scan for skill directories.
2. Validate `skill.json` via Pydantic.
3. Reject malformed or duplicate IDs.

Acceptance:
- Registry builds deterministic index at startup.

### Sprint 3.2 — Prompt Injection Hook
Tasks:
1. Extend agent prompt assembly path to append enabled skill fragments.
2. Inject order: base prompt → soul context → skill prompts → user message.
3. Enforce `allowed_agents` gate per skill.

Acceptance:
- Non-allowed agents do not receive skill prompt fragments.

### Sprint 3.3 — Skills Admin API
Endpoints:
- `GET /skills`
- `GET /skills/{skill_id}`
- `PATCH /skills/{skill_id}` (`enabled` only)
- `POST /skills/reload`

Acceptance:
- Toggle state persists to `backend/memory/skills_state.json`.

### Sprint 3.4 — Tests + Safety
Tasks:
1. Unit tests for manifest parsing, duplicate prevention, gating.
2. Verify disabled skills are omitted from prompt payload.
3. Audit required tools vs known tools registry.

Acceptance:
- Skill requiring unknown tool is flagged invalid and skipped.

---

## 4) Feature 7 — Agent-to-Agent Messaging (A2A)

### Problem
Agents coordinate only through user-directed flows; no explicit session-to-session queueing.

### Goal
Add orchestrator-mediated A2A mailbox with loop protection.

### Target Files
- `backend/orchestrator/__init__.py`
- `backend/routes/agent_control.py` (if route exposure needed)
- `backend/memory/shared/events.json`
- `backend/tests/test_agent_to_agent.py` (new)

### Message Envelope
```python
class AgentMessage(BaseModel):
    message_id: str
    from_agent: str
    to_agent: str
    parent_message_id: str | None = None
    depth: int = 0
    purpose: str
    payload: dict[str, Any]
    created_at: str
```

### Sprint 7.1 — Core Mailbox API (internal)
Tasks:
1. Add orchestrator methods:
   - `send_agent_message(...)`
   - `list_agent_messages(agent_id, limit=50)`
   - `get_message_history(thread_id)`
2. Persist mailbox events append-only into shared events.

Acceptance:
- Agents can send structured requests to other agents.

### Sprint 7.2 — Loop Guard + Policy
Tasks:
1. Add max relay depth env `A2A_MAX_DEPTH=4`.
2. Reject self-send unless explicit `allow_self=true`.
3. Add dedupe guard by `message_id`.

Acceptance:
- Ping-pong loops terminate deterministically.

### Sprint 7.3 — Optional External Endpoints
Endpoints (optional for dashboard tooling):
- `GET /agents/messages?agent_id=...`
- `POST /agents/messages/send`
- `GET /agents/messages/thread/{thread_id}`

Acceptance:
- Endpoint-driven A2A debugging possible without touching internal memory files.

---

## 5) Feature 8 — Per-Session Docker Sandboxing

### Current Reality (Already Present)
You already have:
- sandbox session metadata + reserved ports (`sandbox/session_manager.py`)
- stage/release/finalize routes (`backend/routes/sandbox.py`)
- gatekeeper checks for local-model mutation discipline
- playbox release gating in WebGen pipeline

### Gap
Current sandbox is filesystem/process isolation; not container-backed per session.

### Goal
Run each local-model mutation session in a dedicated Docker container while preserving current stage/release semantics.

### Target Files
- `sandbox/session_manager.py`
- `backend/routes/sandbox.py`
- `backend/config.py`
- `backend/agents/gatekeeper_agent.py`
- `backend/tests/test_docker_sandbox.py` (new)
- `sandbox/docker/agentop-sandbox.Dockerfile` (new)

### Sprint 8.1 — Container Metadata + Lifecycle
Tasks:
1. Extend session meta with:
   - `container_id`
   - `container_name`
   - `container_status`
2. Add `SandboxSession.start_container()` and `stop_container()`.
3. Docker image default: `agentop/sandbox:latest` (configurable).

Acceptance:
- Session creation can optionally start container and persist IDs.

### Sprint 8.2 — Exec Routing
Tasks:
1. Add execution helper for session-scoped commands in container.
2. Mount session workspace at `/workspace` (rw).
3. Mount project root read-only at `/project_ro`.
4. Disable privileged mode; drop capabilities; set `no-new-privileges`.

Acceptance:
- Command execution happens inside container, not host, for containerized sessions.

### Sprint 8.3 — Hardened Defaults
Tasks:
1. Add config:
   - `SANDBOX_DOCKER_ENABLED=true`
   - `SANDBOX_DOCKER_IMAGE=agentop/sandbox:latest`
   - `SANDBOX_DOCKER_NETWORK=none`
   - `SANDBOX_DOCKER_MEM_LIMIT=1g`
   - `SANDBOX_DOCKER_CPU_LIMIT=1.0`
2. Enforce read-only rootfs where feasible.
3. Add tempfs mount for `/tmp`.

Acceptance:
- Container launch denies external network by default.

### Sprint 8.4 — Cleanup + TTL Reaper
Tasks:
1. Add periodic cleanup for stale containers linked to inactive sessions.
2. Add endpoint `POST /sandbox/{session_id}/terminate`.
3. On session destroy, stop+remove container and reclaim metadata.

Acceptance:
- No orphaned containers after normal finalize/release.

---

## 6) Feature 1 — WebSocket Control Plane

### Problem
Current frontend is poll-heavy; no low-latency event stream for tasks, agents, and live logs.

### Goal
Add WS gateway for real-time notifications while retaining REST for request/response.

### Target Files
- `backend/ws/hub.py` (new)
- `backend/ws/models.py` (new)
- `backend/server.py`
- `frontend/src/lib/ws.ts` (new)
- `frontend/src/app/page.tsx`
- `frontend/tests/ws_events.spec.ts` (new)

### Protocol (v1)
Inbound:
```json
{ "type": "subscribe", "channels": ["tasks", "agents", "logs"] }
```
Outbound:
```json
{ "type": "event", "channel": "tasks", "event": "task_created", "payload": {"id":"..."} }
```
Heartbeat:
- Server ping every 20s.
- Client pong timeout 45s.

### Sprint 1.1 — WS Endpoint + Connection Manager
Tasks:
1. Add `WebSocket` endpoint `/ws/control`.
2. Track connection state and channel subscriptions.
3. Handle reconnect-safe session IDs.

Acceptance:
- Multiple clients can subscribe to distinct channels.

### Sprint 1.2 — Event Emitters
Tasks:
1. Publish task tracker events (`task_created`, `task_completed`).
2. Publish orchestrator events (`agent_response`, `agent_error`).
3. Publish health events (`mcp_status`, `llm_health`).

Acceptance:
- Events appear in subscribed clients within <1s locally.

### Sprint 1.3 — Frontend WS Client
Tasks:
1. Add singleton WS client in `frontend/src/lib/ws.ts`.
2. Add reconnect with capped exponential backoff.
3. Bridge incoming events into UI state store.

Acceptance:
- Dashboard updates without polling for subscribed panes.

### Sprint 1.4 — Poll/WS Hybrid
Tasks:
1. Keep REST as fallback when WS disconnected.
2. Add small “Live” connection indicator.
3. Feature flag via `NEXT_PUBLIC_WS_ENABLED`.

Acceptance:
- Existing UI still functional with WS disabled.

---

## 7) Feature 4 — Browser Control (Playwright/CDP)

### Problem
Agents cannot reliably perform web UI tasks requiring full browser interactions.

### Goal
Provide controlled browser automation via explicit toolset.

### Target Files
- `backend/browser/session.py` (new)
- `backend/browser/tooling.py` (new)
- `backend/tools/__init__.py`
- `backend/tests/test_browser_tools.py` (new)

### Tool Surface
- `browser_open(url)`
- `browser_click(selector)`
- `browser_type(selector, text)`
- `browser_select(selector, value)`
- `browser_snapshot()`
- `browser_screenshot(path)`
- `browser_upload(selector, file_path)`
- `browser_close()`

### Sprint 4.1 — Browser Session Manager
Tasks:
1. Start Playwright Chromium context per agent session.
2. Isolate storage state per session.
3. Add TTL auto-close (default 10 min idle).

Acceptance:
- Sessions are independent and cleaned up on idle timeout.

### Sprint 4.2 — Safe Tool Wrappers
Tasks:
1. Implement tools with allowlist for URL schemes (`http`, `https`).
2. Block local/private network targets by default (align with SSRF policy).
3. Enforce max navigation timeout and action retries.

Acceptance:
- Tool calls fail safely with structured error payload.

### Sprint 4.3 — Artifacts + Audit
Tasks:
1. Save screenshots under `output/browser/<session_id>/`.
2. Log all browser actions into system logs.
3. Add action redaction for secrets in typed fields.

Acceptance:
- Full action trace available for each session.

### Sprint 4.4 — Agent Permissioning
Tasks:
1. Add browser tool permissions only to selected agents initially.
2. Update `docs/AGENT_REGISTRY.md` allowed tools list.
3. Add tests ensuring unauthorized agents cannot call browser tools.

Acceptance:
- Permission checks enforced identically to existing tool model.

---

## 8) Feature 5 — Canvas + A2UI

### Problem
Text-only interface limits complex workflows where agents should render structured UI elements.

### Goal
Create an agent-to-UI protocol allowing server-driven cards, forms, and status blocks.

### Target Files
- `backend/a2ui/schema.py` (new)
- `backend/a2ui/bus.py` (new)
- `frontend/src/components/canvas/AgentCanvas.tsx` (new)
- `frontend/src/components/canvas/widgets/*` (new)
- `frontend/src/lib/a2ui.ts` (new)
- `backend/tests/test_a2ui_schema.py` (new)

### Message Schema
```json
{
  "ui_event_id": "uuid",
  "session_id": "...",
  "agent_id": "...",
  "op": "render",
  "target": "canvas/main",
  "component": "status_card",
  "props": {"title": "Deploy", "state": "running"},
  "timestamp": "iso8601"
}
```

Allowed ops v1:
- `render`
- `replace`
- `append`
- `clear`

### Sprint 5.1 — Protocol + Validation
Tasks:
1. Add strict Pydantic validation for A2UI messages.
2. Reject unknown components or disallowed props.
3. Add schema tests.

Acceptance:
- Invalid A2UI payloads are rejected with clear diagnostics.

### Sprint 5.2 — Transport
Tasks:
1. Deliver A2UI events over WS control plane channels.
2. Add sequence numbers to handle out-of-order frames.

Acceptance:
- Frontend receives ordered canvas operations.

### Sprint 5.3 — Frontend Canvas Shell
Tasks:
1. Add `AgentCanvas` panel with bounded widget registry.
2. Implement v1 widgets:
   - `status_card`
   - `task_list`
   - `kv_table`
3. No dynamic JS evaluation.

Acceptance:
- Agents can render controlled visual blocks.

### Sprint 5.4 — Interaction Loop
Tasks:
1. Add `onAction` callback path from widget -> backend action endpoint.
2. Backend maps action to agent message dispatch with context.

Acceptance:
- UI button clicks can continue agent workflows safely.

### Sprint 5.5 — Guardrails
Tasks:
1. Per-agent component allowlists.
2. Per-session canvas quota (max widgets/events).
3. Clear-all endpoint for operator reset.

Acceptance:
- Misbehaving agent cannot flood UI.

---

## 9) Codex Execution Contract (How to Hand Off)

For each sprint, provide Codex this exact structure:
1. **Scope**: one sprint only.
2. **Files to edit**: explicit list.
3. **Tests to run**: focused first, then broader.
4. **Done criteria**: measurable conditions.
5. **Non-goals**: explicitly ban extras.

Template:
```markdown
Implement Sprint <ID> from docs/OPENCLAW_ADOPTION_SPECS.md.

Constraints:
- Do not modify unrelated files.
- Preserve existing API behavior unless sprint states otherwise.
- Add/update tests listed in sprint.

Required output:
- Summary of changed files
- Test command results
- Any follow-up risks
```

---

## 10) Milestone Gates

### Gate A (after Features 10 + 9)
- Failover + scheduler/webhooks operational.
- No regressions in existing chat/orchestrator flows.

### Gate B (after Features 3 + 7 + 8)
- Skills + A2A + Docker sandbox integrated with governance.
- Sandbox cleanup proven in test + manual run.

### Gate C (after Features 1 + 4 + 5)
- Real-time UX path complete with WS + browser tools + canvas.
- Poll fallback verified.

---

## 11) Risks and Mitigations

1. **Event complexity explosion** (WS + A2UI + A2A):
   - Mitigation: strict schemas, sequence numbers, per-channel limits.
2. **Sandbox operational overhead**:
   - Mitigation: feature flags + TTL reaper + default network isolation.
3. **Provider drift in failover pricing/perf**:
   - Mitigation: profile budgets + health metrics + explicit fallback order.
4. **Debuggability degradation**:
   - Mitigation: trace IDs across scheduler, webhook, A2A, and WS events.

---

## 12) Owner Checklist Before Starting Sprint 10.1

- [ ] Decide initial fallback model chains.
- [ ] Populate provider API keys/profile env vars.
- [ ] Confirm Docker availability on host for Feature 8 later.
- [ ] Confirm frontend can add one panel in System tab for health state.
- [ ] Freeze unrelated feature work during Gate A.

---

## 13) Definition of Done (Program-Level)

All selected features are done when:
1. Each sprint has passing tests and documented endpoints.
2. `docs/CHANGE_LOG.md` updated per sprint batch.
3. `docs/AGENT_REGISTRY.md` updated for any tool permission changes.
4. `docs/SOURCE_OF_TRUTH.md` updated if any invariant or architecture rule changes.
5. No critical regressions in existing REST UX and webgen sandbox enforcement.
