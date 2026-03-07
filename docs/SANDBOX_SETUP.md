# Agentop Sandbox Setup Runbook (Host + Docker Sessions)

> Date: 2026-03-06  
> Audience: owner/operators implementing secure local-model mutation flows  
> Applies to existing routes in `backend/routes/sandbox.py` and session manager in `sandbox/session_manager.py`

---

## 1) What You Already Have

Existing implemented baseline:
- Session creation/listing: `POST /sandbox/create`, `GET /sandbox/sessions`
- Promotion flow:
  - staged path: `POST /sandbox/{id}/stage`
  - gated release path: `POST /sandbox/{id}/release`
  - legacy promote/finalize for non-local sessions
- Local-model enforcement via `SANDBOX_ENFORCEMENT_ENABLED`
- Required checks default: `tests_ok,playwright_ok,lighthouse_mobile_ok`
- Session metadata + reserved port allocation in `sandbox/session_manager.py`

This means you do **not** need to start from zero.

---

## 2) Minimum Secure Configuration (Current System)

Add/update `.env`:

```bash
SANDBOX_ENFORCEMENT_ENABLED=true
SANDBOX_ROOT_DIR=/tmp/ai-sandbox
PLAYBOX_DIR=/root/studio/testing/Agentop/playground/local-llm
LOCAL_LLM_REQUIRED_CHECKS=tests_ok,playwright_ok,lighthouse_mobile_ok
SANDBOX_FRONTEND_PORT_RANGE_START=3100
SANDBOX_FRONTEND_PORT_RANGE_END=3999
SANDBOX_BACKEND_PORT_RANGE_START=8100
SANDBOX_BACKEND_PORT_RANGE_END=8999
```

Verify directories exist and are writable by your runtime user.

---

## 3) Operator Workflow (Today)

### Step A — Create session
```http
POST /sandbox/create
{
  "task": "Implement X feature",
  "model": "local"
}
```

### Step B — Write changes into sandbox workspace
- Place files under `/<SANDBOX_ROOT_DIR>/<session_id>/workspace/...`

### Step C — Stage files
```http
POST /sandbox/{session_id}/stage
{
  "files": ["backend/example.py", "frontend/src/example.tsx"]
}
```

### Step D — Run checks against staged output
Required checks must pass:
- `tests_ok=true`
- `playwright_ok=true`
- `lighthouse_mobile_ok=true`

### Step E — Release
```http
POST /sandbox/{session_id}/release
{
  "files": ["backend/example.py", "frontend/src/example.tsx"],
  "checks": {
    "tests_ok": true,
    "playwright_ok": true,
    "lighthouse_mobile_ok": true
  }
}
```

If gatekeeper approves, files are released from playbox into project root and session is destroyed.

---

## 4) Add Docker Isolation (Next Upgrade)

## 4.1 Why
Current sandbox isolates by directory + process flow, but executes on host. Docker adds process/network isolation per session.

## 4.2 New Config Flags to Add
```bash
SANDBOX_DOCKER_ENABLED=true
SANDBOX_DOCKER_IMAGE=agentop/sandbox:latest
SANDBOX_DOCKER_NETWORK=none
SANDBOX_DOCKER_MEM_LIMIT=1g
SANDBOX_DOCKER_CPU_LIMIT=1.0
SANDBOX_DOCKER_PIDS_LIMIT=256
SANDBOX_DOCKER_READONLY_ROOTFS=true
```

## 4.3 Minimal Dockerfile
Create `sandbox/docker/agentop-sandbox.Dockerfile`:

```dockerfile
FROM python:3.11-slim

RUN useradd -m sandboxuser
WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates nodejs npm \
    && rm -rf /var/lib/apt/lists/*

USER sandboxuser
CMD ["bash", "-lc", "sleep infinity"]
```

Build image:
```bash
docker build -f sandbox/docker/agentop-sandbox.Dockerfile -t agentop/sandbox:latest .
```

## 4.4 Session Container Launch Contract
On `POST /sandbox/create` for local model sessions:
1. Create session folders as currently done.
2. Start container with:
   - bind mount: session workspace -> `/workspace` (rw)
   - bind mount: repo root -> `/project_ro` (ro)
   - network: `none`
   - memory/cpu/pids limits from env
   - `--read-only` rootfs (with tmpfs `/tmp`)
3. Persist container metadata into session `meta.json`.

Example launch command (reference):
```bash
docker run -d \
  --name agentop-sbx-<session_id> \
  --network none \
  --memory 1g \
  --cpus 1.0 \
  --pids-limit 256 \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,size=256m \
  -v /tmp/ai-sandbox/<session_id>/workspace:/workspace:rw \
  -v /root/studio/testing/Agentop:/project_ro:ro \
  agentop/sandbox:latest
```

## 4.5 Execution Routing
When session has `container_id`, tooling or command execution should use:
```bash
docker exec <container_id> bash -lc "<command>"
```
Never execute mutation commands directly on host for containerized sessions.

## 4.6 Teardown Rules
On release/finalize/destroy:
1. `docker stop <container_id>` (timeout 10s)
2. `docker rm <container_id>`
3. Mark session inactive and append `docs/SANDBOX_LOG.md`
4. Remove sandbox workspace directory

Add stale reaper on startup:
- Detect containers named `agentop-sbx-*` with no active `meta.json`
- Stop/remove orphaned containers.

---

## 5) Security Defaults Checklist

- [ ] `SANDBOX_ENFORCEMENT_ENABLED=true`
- [ ] Docker sessions use `--network none`
- [ ] Container rootfs read-only
- [ ] No privileged mode
- [ ] No host docker socket mount inside sandbox container
- [ ] Strict file allowlist on release
- [ ] Gatekeeper required for every local-model release
- [ ] Secrets scan executed before release (recommended addition)

---

## 6) Tests You Should Keep Green

Existing:
- `backend/tests/test_sandbox_port_allocator.py`
- `backend/tests/test_webgen_sandbox_enforcement.py`

Add with Docker rollout:
- `backend/tests/test_docker_sandbox_lifecycle.py`
  - create -> container running
  - release -> container removed
- `backend/tests/test_docker_sandbox_network.py`
  - ensure container network mode is `none`
- `backend/tests/test_docker_sandbox_exec_path.py`
  - ensure commands route through `docker exec`

---

## 7) Troubleshooting

### Symptom: release blocked with missing checks
Cause: one of required checks absent or false.  
Fix: ensure `checks` payload includes all names in `LOCAL_LLM_REQUIRED_CHECKS` and all are `true`.

### Symptom: no available sandbox ports
Cause: configured ranges exhausted or stale active sessions.  
Fix: widen port ranges and clear stale session metadata under `SANDBOX_ROOT_DIR`.

### Symptom: docker container starts but cannot write files
Cause: workspace mount path mismatch or permissions.  
Fix: verify mount path points to session `workspace` and container user has write access.

### Symptom: orphaned containers
Cause: crash before normal teardown.  
Fix: run reaper at backend startup and on periodic timer.

---

## 8) Recommended Rollout (Low-Risk)

1. Keep current host sandbox flow active (today).
2. Implement Docker session lifecycle behind `SANDBOX_DOCKER_ENABLED=false` default.
3. Test on one internal agent/workflow.
4. Enable Docker isolation for local-model sessions only.
5. After two stable days, default `SANDBOX_DOCKER_ENABLED=true`.

---

## 9) Quick API Smoke Sequence

1. Create session (`/sandbox/create`)
2. Stage files (`/sandbox/{id}/stage`)
3. Release with all checks true (`/sandbox/{id}/release`)
4. Read log (`/sandbox/log`)
5. Confirm session absent in (`/sandbox/sessions`)

This validates the end-to-end operator flow.
