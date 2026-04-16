# SOURCE OF TRUTH — Agentop Multi-Agent System

> **Last Updated:** 2026-04-16T00:00:00Z
> **Updated By:** architecture-governor
> **Version:** 2.3.0

> **Deployment Contract:** `AGENTOP_DEPLOYMENT_MODE=operator_only`
> This system is operated by a single privileged operator on a local or trusted private network.
> Multi-user RBAC, public sign-up, session auth, and org isolation are NOT part of the current
> architecture and will not be added in the active sprint program. This is a deliberate architectural
> decision recorded here as the canonical source of truth.

---

## 1. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                     VS CODE EXTENSION (@agentop)                       │
│                  Chat Participant — Orchestration Layer                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ /soul    │ │ /devops  │ │ /monitor │ │ /security│ │ /review …  │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
│  Routes intent → FastAPI /chat  ·  Streams response → VS Code panel   │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ HTTP (localhost:8000)
┌───────────────────────────────┴────────────────────────────────────────┐
│                         NEXT.JS DASHBOARD                              │
│                           (localhost:3007)                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐  │
│  │ Soul     │ │ Agents   │ │ Tool     │ │ Drift    │ │ Memory     │  │
│  │ Panel    │ │ by Tier  │ │ Registry │ │ Monitor  │ │ Overview   │  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └────────────┘  │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ REST API (polling every 5s)
┌───────────────────────────────┴────────────────────────────────────────┐
│                          FASTAPI BACKEND                               │
│                           (localhost:8000)                             │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                  DRIFT GUARD MIDDLEWARE                          │   │
│  │  – Intercepts all tool calls                                    │   │
│  │  – Detects structural modifications                             │   │
│  │  – Enforces documentation-before-mutation                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                        │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐    │
│  │  LANGGRAPH           │    │  AGENT REGISTRY (ALL_AGENT_DEFS)   │    │
│  │  ORCHESTRATOR        │◄──►│  Tier 0: soul_core (SoulAgent)     │    │
│  │  – State machine     │    │  Tier 1: devops, monitor, healer   │    │
│  │  – Intent routing    │    │  Tier 2: code_review, security,    │    │
│  │  – Soul boot seq.    │    │          data                      │    │
│  │  – Fan-out dispatch  │    │  Tier 3: comms, cs, it, knowledge  │    │
│  └──────────┬───────────┘    └────────────────────────────────────┘    │
│             │                                                          │
│  ┌──────────┴───────────┐    ┌────────────────────────────────────┐    │
│  │  SOUL AGENT          │    │  BASE AGENTS (×9)                  │    │
│  │  – boot() on startup │    │  – process_message()               │    │
│  │  – reflect(trigger)  │    │  – tool_permissions enforced       │    │
│  │  – goal lifecycle    │    │  – namespaced memory               │    │
│  │  – trust scoring     │    └────────────────────────────────────┘    │
│  └──────────┬───────────┘                                              │
│             │                                                          │
│  ┌──────────┴────────────────────────────────────────────────────┐     │
│  │  TOOL LAYER (38 tools — 12 native + 26 MCP)                  │     │
│  │  READ_ONLY: file_reader · system_info · git_ops · health_check│     │
│  │             log_tail · secret_scanner · db_query              │     │
│  │  STATE_MODIFY: safe_shell · webhook_send · alert_dispatch     │     │
│  │                process_restart                                │     │
│  │  ARCH_MODIFY: doc_updater                                     │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────┐     │
│  │  MCP GATEWAY BRIDGE (docker mcp CLI)                         │     │
│  │  github(7) · filesystem(5) · docker(5) · time(2)             │     │
│  │  fetch(1) · sqlite(3) · slack(3)                             │     │
│  │  Restricted per-agent · Degrades gracefully if CLI absent    │     │
│  └──────────────────────────────────────────────────────────────┘     │
│                                                                        │
│  ┌──────────────────────┐    ┌────────────────────────────────────┐    │
│  │  KNOWLEDGE VECTOR DB │    │  MEMORY STORE (namespaced JSON)    │    │
│  │  – Cosine search     │    │  – 11 agent namespaces             │    │
│  │  – local embeddings  │    │  – shared/events.json              │    │
│  └──────────────────────┘    └────────────────────────────────────┘    │
│                                                                        │
│  ┌────────────────────────────────────────────────────────────────┐    │
│  │  CENTRAL LOGGER                                                │    │
│  │  – Structured JSON (backend/logs/system.jsonl)                 │    │
│  │  – Per-agent log streams · Drift event tracking                │    │
│  └────────────────────────────────────────────────────────────────┘    │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ HTTP
┌───────────────────────────────┴────────────────────────────────────────┐
│                          OLLAMA LLM LAYER                              │
│                           (localhost:11434)                            │
│  – Local model inference (llama3.2)                                    │
│  – No cloud dependency · Configurable model selection                  │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent Definitions

| Agent               | Class       | Tier | Role                                               | Namespace           | Impact Level |
|---------------------|-------------|------|----------------------------------------------------|---------------------|-------------|
| `soul_core`         | SoulAgent   | 0    | Persistent cluster conscience, goal & trust mgmt  | `soul_core`         | CRITICAL    |
| `devops_agent`      | BaseAgent   | 1    | CI/CD, git ops, deployment coordination            | `devops_agent`      | HIGH        |
| `monitor_agent`     | BaseAgent   | 1    | Health surveillance, log tailing, alerting         | `monitor_agent`     | LOW         |
| `self_healer_agent` | BaseAgent   | 1    | Automated fault remediation, process restarts      | `self_healer_agent` | HIGH        |
| `code_review_agent` | BaseAgent   | 2    | Diff review, invariant enforcement, drift checking | `code_review_agent` | MEDIUM      |
| `security_agent`    | BaseAgent   | 2    | Passive secret scanning, CVE flagging              | `security_agent`    | MEDIUM      |
| `data_agent`        | BaseAgent   | 2    | ETL governance, schema drift, SQLite queries       | `data_agent`        | MEDIUM      |
| `comms_agent`       | BaseAgent   | 3    | Outbound webhooks, incidents, stakeholder alerts   | `comms_agent`       | MEDIUM      |
| `cs_agent`          | BaseAgent   | 3    | Customer support, query handling, knowledge access | `cs_agent`          | LOW         |
| `it_agent`          | BaseAgent   | 3    | Infrastructure monitoring, diagnostics             | `it_agent`          | HIGH        |
| `knowledge_agent`   | BaseAgent   | 3    | Semantic Q&A over local vectorized corpus          | `knowledge_agent`   | MEDIUM      |

---

## 3. Tool Definitions

### Native Tools (12)

| Tool             | Modification Type    | Description                                        |
|------------------|----------------------|----------------------------------------------------|
| `safe_shell`     | STATE_MODIFY         | Execute whitelisted shell commands                 |
| `file_reader`    | READ_ONLY            | Read file contents safely                          |
| `doc_updater`    | ARCHITECTURAL_MODIFY | Update governance documentation                    |
| `system_info`    | READ_ONLY            | Retrieve system information                        |
| `webhook_send`   | STATE_MODIFY         | HTTP POST to external webhook endpoints            |
| `git_ops`        | READ_ONLY            | Whitelisted git subcommands (log/status/diff/…)   |
| `health_check`   | READ_ONLY            | HTTP reachability check for any URL                |
| `log_tail`       | READ_ONLY            | Tail N lines from a project log file               |
| `alert_dispatch` | STATE_MODIFY         | Write structured alert to shared events            |
| `secret_scanner` | READ_ONLY            | 8-pattern regex scan for secrets/credentials       |
| `db_query`       | READ_ONLY            | SELECT / PRAGMA queries against local SQLite DBs   |
| `process_restart`| STATE_MODIFY         | Restart whitelisted processes (backend/frontend/ollama) |

### MCP Gateway Tools (26) — via Docker MCP Bridge

All `mcp_*` tools are pre-declared statically (INV-3). Routed through `backend/mcp/__init__.py` MCPBridge singleton via `docker mcp tools call`. Gracefully degrade if Docker CLI is absent.

| Tool                              | Server     | Type         | Description                                    |
|-----------------------------------|------------|--------------|------------------------------------------------|
| `mcp_github_search_repositories`  | github     | READ_ONLY    | Search GitHub repositories                     |
| `mcp_github_get_file_contents`    | github     | READ_ONLY    | Get file contents from a GitHub repo           |
| `mcp_github_list_issues`          | github     | READ_ONLY    | List issues in a GitHub repo                   |
| `mcp_github_create_issue`         | github     | STATE_MODIFY | Create a new GitHub issue                      |
| `mcp_github_search_code`          | github     | READ_ONLY    | Search code across GitHub repos                |
| `mcp_github_list_pull_requests`   | github     | READ_ONLY    | List pull requests in a GitHub repo            |
| `mcp_github_get_pull_request`     | github     | READ_ONLY    | Get details of a specific pull request         |
| `mcp_filesystem_read_file`        | filesystem | READ_ONLY    | Read a file (scoped to project root)           |
| `mcp_filesystem_write_file`       | filesystem | STATE_MODIFY | Write a file (scoped to project root)          |
| `mcp_filesystem_list_directory`   | filesystem | READ_ONLY    | List directory contents                        |
| `mcp_filesystem_search_files`     | filesystem | READ_ONLY    | Find files matching a pattern                  |
| `mcp_filesystem_get_file_info`    | filesystem | READ_ONLY    | Get file metadata (size, mtime)                |
| `mcp_docker_list_containers`      | docker     | READ_ONLY    | List Docker containers                         |
| `mcp_docker_get_container_logs`   | docker     | READ_ONLY    | Get container logs (scoped to agentop/*)       |
| `mcp_docker_inspect_container`    | docker     | READ_ONLY    | Inspect container metadata                     |
| `mcp_docker_restart_container`    | docker     | STATE_MODIFY | Restart a container (scoped to agentop/*)      |
| `mcp_docker_list_images`          | docker     | READ_ONLY    | List local Docker images                       |
| `mcp_time_get_current_time`       | time       | READ_ONLY    | Get current time in a timezone                 |
| `mcp_time_convert_time`           | time       | READ_ONLY    | Convert time between timezones                 |
| `mcp_fetch_get`                   | fetch      | READ_ONLY    | HTTP GET a URL (private IPs blocked)           |
| `mcp_sqlite_read_query`           | sqlite     | READ_ONLY    | Execute a read-only SQL query                  |
| `mcp_sqlite_list_tables`          | sqlite     | READ_ONLY    | List tables in a SQLite database               |
| `mcp_sqlite_describe_table`       | sqlite     | READ_ONLY    | Describe a table schema                        |
| `mcp_slack_post_message`          | slack      | STATE_MODIFY | Post to a Slack channel (requires token)       |
| `mcp_slack_list_channels`         | slack      | READ_ONLY    | List Slack channels (requires token)           |
| `mcp_slack_get_channel_history`   | slack      | READ_ONLY    | Get Slack channel history (requires token)     |

---

## 4. Memory Structure

```
backend/memory/
    ├── soul_core/          # SoulAgent: identity, goals, trust_scores, sessions, reflection_log
    ├── devops_agent/
    ├── monitor_agent/
    ├── self_healer_agent/
    ├── code_review_agent/
    ├── security_agent/
    ├── data_agent/
    ├── comms_agent/
    ├── cs_agent/
    ├── it_agent/
    ├── knowledge_agent/
    │   └── store.json
    ├── knowledge/
    │   ├── vectors.json        # local vector DB index
    │   └── business_profiles.json
    └── shared/
        └── events.json         # append-only shared orchestrator events
```

- Each agent has a strictly isolated namespace.
- No agent may read/write another agent's namespace during normal operation.
- Shared events are append-only via the orchestrator.
- `soul_core` is the only agent permitted to read shared events for reflection.

---

## 5. API Endpoints

| Method | Path                        | Description                                    |
|--------|-----------------------------|------------------------------------------------|
| GET    | `/health`                   | Health check, LLM status, uptime               |
| GET    | `/status`                   | All agent states + drift report                |
| GET    | `/agents`                   | All 11 agent definitions                       |
| GET    | `/agents/{id}`              | Single agent definition + state                |
| POST   | `/chat`                     | Send message to any registered agent           |
| GET    | `/tools`                    | All 38 tool definitions (12 native + 26 MCP)   |
| GET    | `/mcp/status`               | MCP Gateway bridge availability and tool count |
| POST   | `/tools/{name}`             | Execute a tool by name                         |
| GET    | `/drift`                    | Current drift report                           |
| GET    | `/drift/events`             | All recorded drift events                      |
| GET    | `/logs`                     | Recent tool execution logs                     |
| GET    | `/logs/general`             | System logs (system.jsonl)                     |
| GET    | `/memory`                   | Memory namespaces overview                     |
| GET    | `/memory/agents`            | Per-agent memory usage in MB                   |
| GET    | `/memory/{namespace}`       | Raw data for a single namespace                |
| GET    | `/events`                   | Shared event log                               |
| POST   | `/knowledge/reindex`        | Rebuild vector knowledge index                 |
| POST   | `/soul/reflect`             | Trigger soul reflection (query param: trigger) |
| GET    | `/soul/goals`               | All soul goals + count                         |
| POST   | `/soul/goals`               | Create a new soul goal                         |
| POST   | `/intake/start`             | Begin social intake questionnaire              |
| POST   | `/intake/answer`            | Answer current intake question                 |
| GET    | `/intake/{business_id}`     | Intake session status                          |
| POST   | `/campaign/generate`        | Generate campaign from completed intake        |

---

## 6. Data Flow

```
User Request (VS Code Extension or Dashboard)
    │
    ▼
Chat Participant (@agentop) or Next.js Frontend
    │  HTTP POST /chat { agent_id, message }
    ▼
FastAPI Router → Drift Guard Middleware
    │
    ▼
LangGraph Orchestrator
    ├── Router Node: identifies target agent_id
    │       • soul_core → SoulAgent.process_message()
    │       • knowledge_agent → vector DB RAG path
    │       • all others → BaseAgent.process_message()
    │
    ├── Executor Node: calls agent
    │       • Agent injects memory context + system prompt
    │       • Tool calls checked against tool_permissions
    │       • Results logged via CentralLogger
    │
    └── Response streamed back to caller
```

---

## 7. MCP Gateway

**Location:** `mcp-gateway/`
**Bridge:** `backend/mcp/__init__.py` — `MCPBridge` singleton
**Wired in:** `backend/server.py` lifespan (`initialise()` on startup, `shutdown()` on teardown)

### MCP Servers configured in `mcp-gateway/registry.yaml`

| Server     | Status   | Config source                       | Scope restriction                        |
|------------|----------|-------------------------------------|------------------------------------------|
| github     | enabled  | `GITHUB_PERSONAL_ACCESS_TOKEN` env  | Public repos only                        |
| filesystem | enabled  | `mcp-gateway/config.yaml`           | Restricted to `/root/studio/testing/Agentop` |
| time       | enabled  | built-in                            | None                                     |
| fetch      | enabled  | `mcp-gateway/config.yaml`           | Private/internal IPs blocked             |
| docker     | enabled  | socket mount                        | Container prefixes: `agentop`, `mcp`     |
| sqlite     | enabled  | `mcp-gateway/config.yaml`           | Project DB files, read-only mount        |
| slack      | disabled | `SLACK_BOT_TOKEN` env (not set)     | Enable by setting token + `enabled: true`|

### Per-agent MCP tool assignments (see `mcp-gateway/profiles/README.md`)

| Agent               | MCP Servers granted                          |
|---------------------|----------------------------------------------|
| `soul_core`         | github(search/issues), filesystem, time      |
| `devops_agent`      | github(full), docker(read+restart), time     |
| `monitor_agent`     | fetch, docker(read), time                    |
| `self_healer_agent` | docker(read+restart)                         |
| `code_review_agent` | github(search/files/code), filesystem(read)  |
| `security_agent`    | github(search/code), filesystem(read+search) |
| `data_agent`        | sqlite(full), filesystem(read)               |
| `comms_agent`       | slack, fetch, time                           |
| `cs_agent`          | filesystem(read), time                       |
| `it_agent`          | filesystem(read), docker(read), time         |
| `knowledge_agent`   | filesystem(read+search), fetch               |

---

## 8. VS Code Extension — Agentop Orchestrator

**Location:** `vscode-extension/`
**Participant ID:** `agentop.orchestrator`
**Activation Events:** `onStartupFinished`

### Slash commands → agent mapping

| Command    | Backend Agent       | Description                               |
|------------|---------------------|-------------------------------------------|
| `/soul`    | `soul_core`         | Governance, goals, reflection, trust      |
| `/devops`  | `devops_agent`      | Git, deployments, pipeline status         |
| `/monitor` | `monitor_agent`     | Health, logs, metrics                     |
| `/security`| `security_agent`    | Secrets scan, CVE alerts                  |
| `/review`  | `code_review_agent` | Diff review, invariant check              |
| `/data`    | `data_agent`        | DB queries, schema drift                  |
| `/comms`   | `comms_agent`       | Webhooks, incident announcements          |
| `/it`      | `it_agent`          | Infrastructure, shell diagnostics         |
| `/cs`      | `cs_agent`          | Customer support, knowledge lookup        |
| *(default)*| `knowledge_agent`   | General semantic Q&A                      |

### Configuration

| Setting                | Default                   | Description                         |
|------------------------|---------------------------|-------------------------------------|
| `agentop.backendUrl`   | `http://localhost:8000`   | Agentop FastAPI backend URL         |
| `agentop.defaultAgent` | `knowledge_agent`         | Agent used when no slash command given |

---

## 9. Boundaries of Responsibility

| Layer              | Responsibility                                                        | Forbidden                                    |
|--------------------|-----------------------------------------------------------------------|----------------------------------------------|
| LLM Layer          | Inference only                                                        | No state, no direct tool access              |
| SoulAgent          | Govern, reflect, set goals, arbitrate trust                           | Cannot execute state-modify tools unilaterally |
| BaseAgents         | Prompt execution within tool permission whitelist                     | Cannot access other agents' namespaces       |
| Tool Layer         | Execute with logging, DriftGuard enforcement                          | Cannot self-register or escalate permissions |
| Drift Guard        | Intercept, validate, documentation enforcement                        | Cannot block read-only operations            |
| Dashboard          | Read-only visualization + chat + soul goal input                      | No direct backend state mutation             |
| VS Code Extension  | Route intent, stream response, register tools                         | No bypass of /chat endpoint                  |
| Memory Store       | Namespaced persistence                                                | No cross-agent read/write                    |
| Orchestrator       | State machine, routing, turn management, soul boot                    | Cannot expose internal graph state via API   |
| MCP Gateway        | Route mcp_* tool calls via docker CLI subprocess                      | Only pre-declared tools; no dynamic registration (INV-3) |

---

## 10. Invariants

See [DRIFT_GUARD.md](./DRIFT_GUARD.md) for the complete list of architectural invariants.

---

## 11. WebGen Pipeline

### V1 (Deprecated)

**Status:** Deprecated — LLM-generated HTML produces low-quality results.
**Location:** `backend/webgen/`
**CLI:** `webgen_cli.py`
**Approach:** LLM generates full HTML. Abandoned due to generic, unrefined output.
**Test Output:** `output/webgen/bellas-kitchen/`

### V2: Premium Design System (Active)

**Status:** Active — hand-crafted production-grade sites.
**Approach:** LLM writes copy only. Design system, components, and layouts are hand-crafted.
Built sites are static HTML/CSS/JS with no runtime framework dependency.

#### Design System Spec

| Token                  | Value                                    |
|------------------------|------------------------------------------|
| Display Font           | EB Garamond (serif — authority)          |
| Body Font              | Inter (sans-serif — readability)         |
| Background Dark        | `#0a1628` (deep navy)                    |
| Background Warm        | `#f8f6f1` (warm off-white)               |
| Accent                 | `#b8977e` (warm gold)                    |
| Section Spacing        | `clamp(6rem, 10vw, 12rem)`              |
| Motion Duration        | 0.2–0.35s                                |
| Motion Easing          | `cubic-bezier(0.16, 1, 0.3, 1)`        |
| Parallax Rate          | 0.15                                     |
| Hero Height            | 100vh (home), 60–75vh (interior)         |
| Image Treatment        | `saturate(0.7) contrast(1.05)`, vignette, film grain |
| Prohibited Motion      | Bounce, elastic, `>0.4s` transitions     |

#### SEO / AEO Schema Coverage

| Page          | JSON-LD Types                                        |
|---------------|------------------------------------------------------|
| Home          | ProfessionalService, WebSite (SearchAction), Speakable|
| About         | AboutPage + Organization                             |
| Services      | ItemList (6 Services), HowTo (4 steps)               |
| Who We Serve  | WebPage + Speakable                                  |
| Industries    | Speakable                                            |
| Contact       | ContactPage, FAQPage (6 questions)                   |

#### Generated Sites

| Client                              | Path                                                       | Port  |
|--------------------------------------|-----------------------------------------------------------|-------|
| Innovation Development Solutions     | `output/webgen/innovation-development-solutions/`          | 8344  |

#### File Structure (per site)

```
{site-slug}/
├── index.html           # Home page
├── about/index.html     # About
├── services/index.html  # Services
├── who-we-serve/index.html  # Who We Serve
├── industries/index.html    # Industries
├── contact/index.html   # Contact + FAQ
├── css/style.css        # Design system
├── js/main.js           # Motion / interaction layer
├── sitemap.xml          # SEO sitemap
└── robots.txt           # Crawler directives
```

---

## 12. Secrets Management

**Provider:** Doppler — `https://dashboard.doppler.com` (project: `agentop`, config: `dev`)
**Migrated:** 2026-04-08 — all 50 secrets from `.env` pushed to Doppler.

### Rules (enforced by INV-14, INV-21)
- `.env` is gitignored, local-only fallback. Never the source of truth.
- All processes should start via `doppler run --` to inject secrets as env vars — no file on disk.
- New secrets: `doppler secrets set KEY=value` from CLI, never added to `.env` only.
- Rotation (free plan, manual): `doppler secrets set OLD_KEY=new_value`, then revoke at the provider API dashboard.
- Rotation (automated): requires Team plan. Script at `scripts/migrate_secrets_to_doppler.py --rotate-sensitive`.
- Audit: `python scripts/sync_doppler.py audit` or `doppler secrets` to verify live state.

### Agents responsible
| Agent | Role |
|---|---|
| `security_agent` | Flags secrets found outside Doppler via `secret_scanner` tool |
| `devops_agent` | Ensures `doppler run --` is used in all deploy/run scripts |
| `soul_core` | Enforces INV-14/INV-21 invariants, blocks non-compliant tool calls |

---

## 13. Content Production Pipeline

**Location:** `backend/content/`
**CLI:** `content_cli.py`
**Agents:** idea_intake → script_writer → voice → caption → avatar_video → qa → publisher → analytics
**Memory:** `backend/memory/content_jobs/`, `content_audio/`, `content_video/`, `content_notes/`, `content_publish/`, `content_reports/`, `social_intake/`

