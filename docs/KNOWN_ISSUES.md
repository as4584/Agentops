# Known Issues & Root Cause Analysis

> Generated from the debugging sessions leading up to commit that ships this file.
> Last updated: 2025-07-18

---

## 1. 404 Page in Electron Window

**Symptom:** Electron opens and shows a "404 — This page could not be found" error
instead of the Agentop dashboard.

**Root Causes (3 separate bugs, all fixed):**

| # | Component | Bug | Fix |
|---|-----------|-----|-----|
| 1 | `frontend/electron/main.js` — `waitForPort()` | Accepted any HTTP status < 500 as "ready", including 404. Next.js returns 404 during initial compilation before the page is built. | Changed to require **HTTP 200** specifically. |
| 2 | `frontend/electron/main.js` — `waitForPort()` | On timeout, called `resolve()` silently instead of rejecting — Electron loaded the URL even if Next.js never became ready. | Now **rejects with an error** on timeout. Timeout increased from 30s → 60s. |
| 3 | `frontend/electron/main.js` — page load | Once a 404 was rendered, there was no retry mechanism. | Added `did-fail-load` and `did-finish-load` handlers that **auto-retry after 3 seconds** if the page is a 404 or fails to load. |

**How to verify:** Kill all processes, run `python3 app.py`. Electron should wait until
Next.js is fully compiled before showing the window. If Next.js is slow, Electron retries
automatically.

---

## 2. "Backend unreachable: Failed to fetch" / HTTP 429 Rate Limit

**Symptom:** Random "Backend unreachable" toast errors in the dashboard. Backend logs
show `429 Too Many Requests`.

**Root Cause:**

The dashboard frontend polls **12 API endpoints** every 5 seconds:

```
Promise.all → /health, /agents, /tools, /drift, /logs?n=30, /memory/agents, /soul/goals
Sequential  → /tasks, /status, /llm/stats, /llm/capacity, /webgen/projects
```

That's **144 requests per minute** minimum, and any page navigation or manual refresh
adds more. The rate limiter was set to 120 RPM (original) and then 600 RPM.

**Fix:**

Rate limiting is now **skipped for local traffic** (`127.0.0.1` / `::1`). The dashboard
runs on localhost, so there is no security risk. Remote callers (if the API is exposed
externally) still get rate-limited.

| Setting | Before | After |
|---------|--------|-------|
| `RATE_LIMIT_RPM` | 120 → 600 | 600 (remote only) |
| Local (`127.0.0.1`) | Rate-limited | **Exempt** |

---

## 3. Zombie / Stale Processes Blocking Ports

**Symptom:** After a crash or Ctrl+C, running `python3 app.py` again says "Backend
already running" / "Dashboard already running" — but the old process is dead or
unresponsive. Electron opens a 404.

**Root Cause:**

`app.py` checked `_is_port_open(port)` which only tests if the TCP socket accepts
connections. A crashed/zombie process can hold a socket open even though it returns errors.
If the port was "open", app.py skipped starting a new service.

**Fix:**

- **Health check instead of port check**: `_is_healthy(port, path)` makes an actual HTTP
  request and verifies the response is HTTP 200.
- **Stale process killer**: If a port is occupied but unhealthy, `_kill_port(port)` uses
  `lsof` to find and kill the stale PID before starting a fresh service.
- Both backend (`:8000/health`) and frontend (`:3007/`) are health-checked.

---

## 4. D-Bus / GTK / WSL Warnings

**Symptom:** Console shows warnings like:
```
Failed to connect to the bus: Could not parse server address: ...
libGL: ... swrast ... DRI driver
```

**Root Cause:** WSL does not have a full desktop session bus. Electron doesn't need
D-Bus for rendering — these are harmless warnings from shared libraries.

**Status:** **Not a bug.** Suppressed by Electron flags (`--no-sandbox`, `--disable-gpu`).
No fix needed.

---

## 5. Multiple Electron Windows

**Symptom:** Running `python3 app.py` a second time (while the first is still running)
opens a second Electron window, doubling API traffic and causing confusion.

**Mitigation:** The port health-check in `app.py` now properly detects a running
healthy frontend and reuses it. The stale-kill logic only fires if the port is
occupied *and unhealthy*.

For full prevention, use the operating system's process lock (`flock`) or check for
an existing Electron PID before launching.

---

## 6. Cloud LLMs Not Showing

**Symptom:** The "Model Capacity" section only listed local Ollama models. Cloud models
(GPT-4o, Claude, etc.) were invisible.

**Root Cause:** `/llm/capacity` endpoint only queried Ollama (`lib/localllm/models.py`).
Cloud models defined in `lib/localllm/cloud_client.py` were never included.

**Fix (previously applied):** The endpoint now imports `CLOUD_MODELS` from
`cloud_client.py` and appends them with `provider: "cloud"`, pricing, and availability
keyed off `OPENROUTER_API_KEY` presence.

---

## 7. Model Status Shows "NOT PULLED"

**Symptom:** All local models show "NOT PULLED" even though `ollama list` shows them.

**Root Cause:** The Ollama API call in `/llm/capacity` returned the *registry* of known
models. Pulled status was checked by comparing against `ollama list` output, but the
API call or comparison could fail silently (especially if Ollama is slow to respond).

**Status:** Intermittent. Refresh usually resolves it. The dashboard polls every 5s
so it self-corrects.

---

## Architecture Notes

### Polling Budget

| Endpoint | Method | Frequency | Purpose |
|----------|--------|-----------|---------|
| `/health` | GET | 5s | Backend heartbeat |
| `/agents` | GET | 5s | Agent list + statuses |
| `/tools` | GET | 5s | Available tools |
| `/drift` | GET | 5s | Configuration drift |
| `/logs?n=30` | GET | 5s | Recent log lines |
| `/memory/agents` | GET | 5s | Memory-enabled agents |
| `/soul/goals` | GET | 5s | Soul-core active goals |
| `/tasks` | GET | 5s | Task queue |
| `/status` | GET | 5s | System status |
| `/llm/stats` | GET | 5s | Token usage stats |
| `/llm/capacity` | GET | 5s | Model list |
| `/webgen/projects` | GET | 5s | Web generator projects |

**Total: ~144 req/min** from localhost alone. This is why local traffic is exempt from
rate limiting.

### WSL + Electron

Agentop runs in WSL but renders via Electron through WSLg (Wayland/X11 forwarding).
Key flags: `--no-sandbox`, `--disable-gpu`, `--disable-software-rasterizer`.
The Windows `.bat` launcher at `C:\Users\<you>\Desktop\Agentop.bat` invokes WSL.

### Process Lifecycle

```
app.py (main)
  ├── uvicorn (backend :8000)
  ├── next dev (frontend :3007)
  └── electron (native window)
      └── loads http://localhost:3007
```

`atexit` handler kills all child processes when app.py exits. Electron exit triggers
app.py exit (via `electron_proc.wait()`).

---

## 8. Recurring Electron Crash on WSL — IPC Buffer Overflow

> Added: 2026-03-31 | Severity: **HIGH** (recurring)

**Symptom:** Electron crashes immediately or within seconds of launch with:
```
ERROR:connection.cc(711) Cannot send request of length 17301536
```
Or: Electron window appears blank/black, then the process exits silently.

**Root Cause (composite — 3 contributing factors):**

| # | Factor | Detail |
|---|--------|--------|
| 1 | **Chromium shared-memory IPC overflow** | On WSL2, the `/dev/shm` partition is small by default. Chromium's GPU process tries to allocate a ~17 MB IPC buffer via shared memory, which fails when the compositor can't handle it through WSLg's virtual display. |
| 2 | **Missing GPU isolation flags** | `--disable-hardware-acceleration` alone is not enough in WSL. Chromium still spawns a GPU process that attempts software rasterization through the display compositor, which triggers the same IPC failure. Required flags: `--disable-software-rasterizer`, `--disable-gpu-compositing`, `--in-process-gpu`. |
| 3 | **Backend startup race** | Electron waited only for the frontend (Next.js on `:3007`) but not the backend (`:8000`). If the backend is slow (MCP bridge init, Ollama cold start), the dashboard loads but shows errors, causing the user to kill/restart Electron — leading to zombie processes and port conflicts on the next attempt. |

**Fix (applied 2026-03-31):**

| File | Change |
|------|--------|
| `frontend/electron/main.js` | Added Chromium flags: `disable-software-rasterizer`, `disable-gpu-compositing`, `in-process-gpu` |
| `frontend/electron/main.js` | Added backend health pre-check: `waitForPort('http://localhost:8000/health', 90000)` before loading frontend |
| `frontend/electron/main.js` | `waitForPort()` now uses exponential backoff (800ms → 3s cap) instead of fixed 800ms polling |
| `app.py` | Backend health timeout raised from 30s → 90s to allow for slow MCP bridge initialization |

**How to verify:**
```bash
# Clean start
pkill -f "electron" 2>/dev/null; pkill -f "next dev" 2>/dev/null
cd /root/studio/testing/Agentop && source .venv/bin/activate && python3 app.py
# Electron should open without the connection.cc error
```

**Permanent fix plan (if issue recurs):**
1. **Increase `/dev/shm` size** — Add `[wsl2] memory=8GB` to `.wslconfig` or mount tmpfs: `sudo mount -t tmpfs -o size=512m tmpfs /dev/shm`
2. **Switch to browser-only mode** — Set `AGENTOP_USE_BROWSER=1` to skip Electron entirely and open in the default browser
3. **Migrate to Tauri** — Tauri uses the system WebView (WebKitGTK on Linux) which doesn't have Chromium's GPU process IPC issues. This would eliminate the entire class of WSL+Electron display bugs.
