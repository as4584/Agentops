# CHANGE LOG — Agentop Multi-Agent System

> All structural changes to the system must be recorded here.
> Entries are chronological. Newest entries at the bottom.
> Any modification to code, configuration, memory schema, or agent registry
> MUST have a corresponding entry before execution.

---

## Format

```
### [TIMESTAMP]
- **Agent:** <agent_id or system>
- **Files Modified:** <list of files>
- **Reason:** <description of change>
- **Risk Assessment:** LOW | MEDIUM | HIGH | CRITICAL
- **Impacted Subsystems:** <list>
- **Documentation Updated:** YES | NO
```

---

## Entries

### 2026-03-01T00:00:00Z
- **Agent:** system-init
- **Files Modified:** All files (initial scaffold)
- **Reason:** Initial system creation — full project scaffold including backend, frontend, docs, and governance layer.
- **Risk Assessment:** LOW
- **Impacted Subsystems:** All (new system)
- **Documentation Updated:** YES — SOURCE_OF_TRUTH.md, AGENT_REGISTRY.md, DRIFT_GUARD.md initialized.

### 2026-03-01T08:00:00Z
- **Agent:** architecture-governor
- **Files Modified:** backend/orchestrator/__init__.py, backend/server.py, frontend/src/app/page.tsx, docs/AGENT_REGISTRY.md
- **Reason:** Disabled IT/CS subagent dispatch and switched runtime to direct LLM mode.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** Orchestrator routing, agent endpoints, dashboard chat selector
- **Documentation Updated:** YES — AGENT_REGISTRY.md updated to reflect no active subagents.

### 2026-03-01T08:30:00Z
- **Agent:** architecture-governor
- **Files Modified:** backend/knowledge/__init__.py, backend/llm/__init__.py, backend/orchestrator/__init__.py, backend/server.py, frontend/src/app/page.tsx, docs/AGENT_REGISTRY.md, docs/SOURCE_OF_TRUTH.md
- **Reason:** Converted runtime to a single Knowledge Agent backed by a local vector DB and semantic retrieval.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** LLM client, orchestrator execution path, agent APIs, dashboard chat defaults, governance docs
- **Documentation Updated:** YES — AGENT_REGISTRY.md and SOURCE_OF_TRUTH.md revised for knowledge agent architecture.

### 2026-03-01T08:45:00Z
- **Agent:** architecture-governor
- **Files Modified:** backend/knowledge/__init__.py, backend/orchestrator/__init__.py, backend/server.py, frontend/src/lib/api.ts, frontend/src/app/page.tsx
- **Reason:** Added `/knowledge/reindex` endpoint and explicit per-agent memory reporting in megabytes.
- **Risk Assessment:** LOW
- **Impacted Subsystems:** Knowledge index operations, memory APIs, dashboard memory display
- **Documentation Updated:** YES — CHANGE_LOG.md updated.

### 2026-03-01T09:00:00Z
- **Agent:** architecture-governor
- **Files Modified:** backend/models/__init__.py, backend/orchestrator/__init__.py, backend/server.py, frontend/src/lib/api.ts
- **Reason:** Added `/campaign/generate` endpoint and campaign generation from completed intake answers + semantic business profile context.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** API models, orchestrator generation flow, server routing, frontend API client
- **Documentation Updated:** YES — CHANGE_LOG.md updated.

---

### 2026-03-01T12:00:00Z — Soul Architecture & Agent Expansion

#### 2026-03-01T12:00:00Z · Tool Layer Expansion
- **Agent:** architecture-governor
- **Files Modified:** `backend/tools/__init__.py`
- **Reason:** Added 8 new tools to the TOOL_REGISTRY to support the expanded agent fleet.
  - `webhook_send` (STATE_MODIFY) — HTTP POST to external endpoints
  - `git_ops` (READ_ONLY) — Whitelisted git subcommands: log, status, diff, show, branch, tag, remote
  - `health_check` (READ_ONLY) — HTTP reachability check for any URL
  - `log_tail` (READ_ONLY) — Tail N lines from log files within project
  - `alert_dispatch` (STATE_MODIFY) — Structured alert logger dispatched to shared events
  - `secret_scanner` (READ_ONLY) — 8-pattern regex scan for credentials/tokens in files
  - `db_query` (READ_ONLY) — SELECT / PRAGMA only queries against local SQLite DBs
  - `process_restart` (STATE_MODIFY) — Restart whitelisted processes: backend, frontend, ollama
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** Tool registry, tool execution dispatch table
- **Documentation Updated:** YES — AGENT_REGISTRY.md, CHANGE_LOG.md

#### 2026-03-01T12:30:00Z · SoulAgent Class + Agent Definitions Expansion
- **Agent:** architecture-governor
- **Files Modified:** `backend/agents/__init__.py`
- **Reason:** Created `SoulAgent` subclass with autobiographical memory lifecycle, and registered 8 new `AgentDefinition` constants plus the `ALL_AGENT_DEFINITIONS` registry.
  - `SoulAgent.boot()` — loads identity/goals/trust from memory, writes SOUL_BOOT event, returns session info
  - `SoulAgent.reflect(trigger)` — generates LLM self-assessment from recent shared events, appends to reflection_log
  - `SoulAgent.set_goal() / complete_goal() / update_trust()` — goal and inter-agent trust lifecycle
  - `SoulAgent.process_message()` — injects autobiographical context into every LLM call
  - New agents: `soul_core`, `devops_agent`, `monitor_agent`, `self_healer_agent`, `code_review_agent`, `security_agent`, `data_agent`, `comms_agent`
  - `create_agent()` factory: returns `SoulAgent` for `soul_core`, `BaseAgent` for all others
- **Risk Assessment:** HIGH
- **Impacted Subsystems:** Agent registry, orchestrator initialization, memory namespaces
- **Documentation Updated:** YES — AGENT_REGISTRY.md, CHANGE_LOG.md

#### 2026-03-01T13:00:00Z · Orchestrator Expansion
- **Agent:** architecture-governor
- **Files Modified:** `backend/orchestrator/__init__.py`
- **Reason:** Expanded LangGraph orchestrator to support all 10 agents, soul boot sequence, and fan-out routing.
  - `_initialize_agents()` loops `ALL_AGENT_DEFINITIONS` and instantiates each via `create_agent()`
  - `_all_agent_ids` property: union of `{knowledge_agent, direct_llm}` + all instantiated agents
  - `_router_node` updated to accept any registered agent_id
  - `_agent_executor_node` routes to `BaseAgent.process_message()` for non-knowledge agents
  - New public methods: `boot_soul()`, `soul_reflect(trigger)`, `soul_set_goal()`, `soul_get_goals()`
  - `get_agent_states()`, `get_all_agent_definitions()`, `get_agent_memory_usage()` updated to cover all 11 agents
- **Risk Assessment:** HIGH
- **Impacted Subsystems:** Orchestrator routing, agent lifecycle, LangGraph state machine
- **Documentation Updated:** YES — CHANGE_LOG.md

#### 2026-03-01T13:15:00Z · Server Endpoint Expansion
- **Agent:** architecture-governor
- **Files Modified:** `backend/server.py`
- **Reason:** Updated FastAPI server to boot Soul on startup and expose new soul + agent endpoints.
  - Lifespan: `boot_soul()` called immediately after orchestrator init
  - `GET /agents` → returns all 11 agent definitions via `get_all_agent_definitions()`
  - `GET /agents/{id}` → single agent lookup from the full dict (404 on miss)
  - `POST /soul/reflect?trigger=` → triggers soul reflection, returns `SoulReflection`
  - `GET /soul/goals` → returns all soul goals + count
  - `POST /soul/goals` → creates a new soul goal
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** API routing, soul lifecycle, frontend data contracts
- **Documentation Updated:** YES — CHANGE_LOG.md

#### 2026-03-01T13:30:00Z · Frontend Dashboard Rewrite
- **Agent:** architecture-governor
- **Files Modified:** `frontend/src/lib/api.ts`, `frontend/src/app/page.tsx`
- **Reason:** Rewrote the dashboard to reflect all backend changes: 11 agents, 12 tools, soul panel, tier groupings, memory overview.
  - `api.ts`: Added `SoulGoal`, `SoulReflection` interfaces; `soulReflect()`, `soulGoals()`, `soulAddGoal()` methods
  - `page.tsx`: Added Soul Panel (goals + add-goal form + reflection trigger); agents grouped by 4 tiers in `grid-3` with impact-level colour badges; Memory Overview table; `soul_core` card highlighted with accent border; stats row drift colour fix
- **Risk Assessment:** LOW
- **Impacted Subsystems:** Frontend UI, API client types
- **Documentation Updated:** YES — CHANGE_LOG.md

#### 2026-03-01T14:00:00Z · VS Code Extension — Agentop Orchestrator
- **Agent:** architecture-governor
- **Files Modified:** `vscode-extension/` (new directory)
- **Reason:** Created a VS Code extension that exposes Agentop's agent fleet as a `@agentop` Chat Participant inside VS Code Copilot Chat. The extension acts as the orchestration layer: it receives user intent, identifies the appropriate backend agent via a slash command or intent heuristic, forwards the request to the FastAPI backend, and streams the response back into the chat panel.
  - Chat participant ID: `agentop.orchestrator`
  - Slash commands: `/soul`, `/devops`, `/monitor`, `/security`, `/review`, `/data`, `/comms`, `/it`, `/cs`
  - Each command maps to a backend agent_id
  - Backend HTTP base: `http://localhost:8000` (configurable via `agentop.backendUrl` setting)
  - Responses streamed via `ChatResponseStream.markdown()`
  - Registered `LanguageModelTool` entries for all 12 backend tools
- **Risk Assessment:** LOW (additive only — no backend changes)
- **Impacted Subsystems:** Developer tooling, VS Code chat interface
- **Documentation Updated:** YES — SOURCE_OF_TRUTH.md, CHANGE_LOG.md


---

### 2026-03-01T15:00:00Z — MCP Gateway Integration — Docker MCP tool delegation

- **Agent:** architecture-governor
- **Files Modified:**
  - `backend/config.py` — added `MCP_GATEWAY_ENABLED`, `MCP_GATEWAY_URL`, `MCP_TOOL_TIMEOUT`, `MCP_CONFIG_DIR`
  - `backend/mcp/__init__.py` — NEW: `MCPBridge` singleton (CLI-based docker mcp gateway) + `MCP_TOOL_MAP` (26 tools)
  - `backend/tools/__init__.py` — added 26 MCP `ToolDefinition` entries to `TOOL_REGISTRY`; `mcp_*` routing in `execute_tool`
  - `backend/agents/__init__.py` — extended `tool_permissions` for all 10 agents with per-agent MCP tool assignments
  - `backend/server.py` — wired `mcp_bridge.initialise()` / `mcp_bridge.shutdown()` into lifespan
  - `mcp-gateway/docker-mcp.yaml` — NEW: Docker Hub MCP catalog config
  - `mcp-gateway/registry.yaml` — NEW: 7 MCP servers (github, filesystem, time, fetch, docker, sqlite, slack)
  - `mcp-gateway/config.yaml` — NEW: per-server runtime config (paths, tokens, mounts)
  - `mcp-gateway/profiles/README.md` — NEW: per-agent MCP profile documentation
- **Reason:** Extended all 10 agents with Docker MCP Gateway tools. Each agent has a restricted set of MCP tools appropriate to its role. `MCPBridge` routes via `docker mcp tools call` subprocess. All 26 MCP tools pre-declared statically in `TOOL_REGISTRY` (INV-3 compliant). MCP servers: GitHub (7 tools), Filesystem (5), Docker (5), Time (2), Fetch (1), SQLite (3), Slack (3 — disabled until `SLACK_BOT_TOKEN` set). `MCPBridge` degrades gracefully if Docker CLI absent.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** All agents (tool_permissions), Tools layer, Server lifespan, MCP Gateway config
- **Documentation Updated:** YES

---

### 2026-03-01T18:30:00Z — Documentation sync + POST /tools/{name} endpoint

- **Agent:** architecture-governor
- **Files Modified:**
  - `backend/server.py` — added `POST /tools/{tool_name}` endpoint; added `execute_tool` import
  - `docs/SOURCE_OF_TRUTH.md` — v2.1.1: MCP gateway section, 38-tool count, duplicate v1 block removed, `/mcp/status` endpoint row added
  - `docs/AGENT_REGISTRY.md` — added MCP tool permissions to all 11 agent entries
  - `docs/CHANGE_LOG.md` — fixed MCP entry date, normalised format
- **Reason:** POST /tools/{name} was documented but unimplemented. AGENT_REGISTRY tool permissions were stale (pre-MCP). SOURCE_OF_TRUTH had leftover duplicate v1.x content block.
- **Risk Assessment:** LOW
- **Impacted Subsystems:** API surface (new endpoint), Developer docs
- **Documentation Updated:** YES

---

### 2026-03-01T20:00:00Z — Content Pipeline V1 + WebGen V1

- **Agent:** architecture-governor
- **Files Modified:**
  - `backend/content/` — NEW: Full content production pipeline (base_agent, idea_intake_agent, script_writer_agent, voice_agent, caption_agent, avatar_video_agent, qa_agent, publisher_agent, analytics_agent, pipeline, video_job, job_store)
  - `backend/webgen/` — NEW: WebGen V1 pipeline (models, pipeline, site_store, template_store, agents/)
  - `content_cli.py` — NEW: CLI for content pipeline
  - `webgen_cli.py` — NEW: CLI for webgen pipeline
  - `lib/localllm/` — NEW: Local LLM client library (OllamaClient wrapper)
  - `output/webgen/bellas-kitchen/` — test output (Bella's Kitchen restaurant site)
- **Reason:** Added two LLM-driven production pipelines: (1) Content pipeline for automated video/audio production with 8 orchestrated agents. (2) WebGen V1 pipeline for generating websites via LLM HTML generation. V1 output quality was insufficient for production use — LLM-generated HTML produces generic, low-quality results.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** LLM layer, memory store (content_jobs, content_audio, content_video, content_notes, content_publish, content_reports, social_intake, webgen_projects, webgen_templates)
- **Documentation Updated:** YES

---

### 2026-03-01T22:00:00Z — WebGen V2: Premium Cinematic Client Site (Innovation Development Solutions)

- **Agent:** architecture-governor
- **Files Modified:**
  - `output/webgen/innovation-development-solutions/` — NEW: Complete premium client website (10 files)
    - `css/style.css` — Premium design system (~700 lines): CSS custom properties, EB Garamond + Inter typography, deep navy (#0a1628) + warm gold (#b8977e) authority palette, cinematic hero with desaturation/vignette/film-grain, scroll reveal system, split/full-bleed layouts, editorial image treatments
    - `js/main.js` — Motion/interaction layer (~130 lines): IntersectionObserver scroll reveal, nav scroll state, hero parallax (0.15 rate), FAQ accordion, mobile nav, active link detection
    - `index.html` — Home page: Full-viewport cinematic hero, 4-stat hero bar, split intro, 3 service cards, full-bleed break, dark stats section, who-we-serve teaser, CTA. JSON-LD: ProfessionalService, WebSite (SearchAction), WebPage (Speakable)
    - `about/index.html` — About page: 75vh hero, "Why we exist" split narrative, 2×2 operating principles grid, full-bleed quote. JSON-LD: AboutPage + Organization
    - `services/index.html` — Services page: 6 service cards, full-bleed methodology break, 4 process steps. JSON-LD: ItemList (6 Services), HowTo (4 steps)
    - `who-we-serve/index.html` — Who We Serve page: 6 industry cards (dark bg), 5 entity structure groups. JSON-LD: WebPage + Speakable
    - `industries/index.html` — Industries page: 6 sector cards, 3 case studies (dark bg). JSON-LD: Speakable
    - `contact/index.html` — Contact page: Form, contact info, 6 FAQs. JSON-LD: ContactPage, FAQPage (6 questions)
    - `sitemap.xml` — 6 page entries with priority weights
    - `robots.txt` — Allows all crawlers including GPTBot, ChatGPT-User, Googlebot, Bingbot
- **Reason:** V1 WebGen produced unacceptable quality. V2 approach: hand-crafted, production-grade HTML/CSS/JS using a cinematic design system inspired by bainbridge.com aesthetic. All client content preserved from original site (innovationdevelopmentsolutions.com). Design spec: cinematic hero layers, editorial photography (desaturated, vignetted, film grain), elegant motion (fade-up only, 0.2-0.35s, no bounce/elastic), full-bleed/split layouts, EB Garamond serif headlines for authority, deep navy palette with warm gold accents. Full SEO (JSON-LD on every page, OG/Twitter meta, canonicals, semantic HTML) and AEO (Speakable schema, FAQ schema, HowTo schema, Service schemas). Site serves on port 8344.
- **Risk Assessment:** LOW (additive output — no backend/pipeline modifications)
- **Impacted Subsystems:** WebGen output directory, project documentation
- **Documentation Updated:** YES

---

### 2026-03-02T13:30:00Z — Bella's Kitchen documented as anti-pattern + IDS V2 deployed to Vercel

- **Agent:** architecture-governor
- **Files Modified:**
  - `docs/DRIFT_GUARD.md` — Added Section 9 (Anti-Patterns): Bella's Kitchen documented as ANTI-1 disaster with failure analysis table, lessons learned, and new INV-11 (WebGen must use hand-crafted design system). 6 mandatory rules for future WebGen output.
  - `https://github.com/as4584/damianwebsite` (external) — Replaced entire repo contents with IDS V2 static site. Added `vercel.json` (static hosting config with clean URLs, security headers, asset caching), `.gitignore`, `README.md` with site-swap instructions.
- **Reason:** (1) Bella's Kitchen V1 output must never be reproduced — formalized as architectural anti-pattern with enforceable invariant. (2) Innovation Development Solutions V2 premium site deployed to Vercel-connected GitHub repo for live customer demos. Repo reconfigured from Next.js to static hosting for easy site swapping.
- **Risk Assessment:** LOW
- **Impacted Subsystems:** Governance docs (DRIFT_GUARD), external deployment (Vercel)
- **Documentation Updated:** YES

---

### 2026-03-02T13:40:00Z — Vercel deploy failure fix + ANTI-2 documentation

- **Agent:** architecture-governor
- **Files Modified:**
  - `vercel.json` (in `https://github.com/as4584/damianwebsite`) — Added `"framework": null`, `"buildCommand": ""`, `"installCommand": ""`, `"outputDirectory": "."` to override Vercel project-level Next.js settings
  - `docs/DRIFT_GUARD.md` — Added ANTI-2 (Vercel Framework Mismatch) to Section 9. Added INV-12 to invariants table. Documented root cause: Vercel project settings persist framework preset even when repo contents change; omitted fields fall back to project settings, not to null.
- **Reason:** First IDS V2 deploy to Vercel failed with `Build Failed: Command "npm run vercel-build" exited with 1`. Repo previously hosted Next.js; Vercel retained `Framework Preset: Next.js` at project level. vercel.json omitted explicit framework override, so Vercel tried to build with Next.js commands against a static HTML site with no package.json.
- **Risk Assessment:** LOW
- **Impacted Subsystems:** External deployment (Vercel), governance docs
- **Documentation Updated:** YES

### 2025-07-14T00:00:00Z — Hybrid Cloud/Local LLM Architecture

- **Agent:** architecture-governor
- **Files Created:**
  - `lib/localllm/cloud_client.py` — CloudLLMClient: OpenRouter-backed cloud LLM client with interface-compatible API (generate, chat, chat_json, sync wrappers, cost tracking). Model registry: Kimi K2, GPT-4o, Claude Sonnet, DeepSeek V3, Gemini Flash.
  - `lib/localllm/router.py` — LLMRouter: hybrid local/cloud routing with task-based routing table (TASK_ROUTES), budget guardrails, cost tracking (RouterStats), three modes (local_only, hybrid, cloud_only).
  - `docs/COSTS_OF_ARCHITECTURE.md` — Full cost analysis: per-site breakdown, volume projections, model comparison, break-even analysis, token efficiency strategies.
  - `docs/HYBRID_ARCHITECTURE.md` — Architecture docs: agent→model→tool matrix, MCP gateway integration, request lifecycle, configuration, governance rules.
- **Files Modified:**
  - `backend/llm/__init__.py` — Added HybridClient class: drop-in replacement for OllamaClient that routes through LLMRouter, lazy-init cloud client, graceful fallback to local-only.
  - `backend/config.py` — Added OPENROUTER_API_KEY, LLM_ROUTER_MODE, LLM_MONTHLY_BUDGET configuration.
  - `.env` — Added LLM_ROUTER_MODE=hybrid, LLM_MONTHLY_BUDGET=50.0 (API key pre-secured).
  - `docs/DRIFT_GUARD.md` — Added INV-13 (cloud calls via router), INV-14 (API key security), INV-15 (budget enforcement), INV-16 (embeddings local-only).
- **Reason:** Enable hybrid cloud/local LLM routing for quality-critical tasks (design systems, architecture) via Kimi K2 while keeping cost-efficient tasks (copy, SEO) on local Ollama. Kimi K2 is 10x cheaper than GPT-4o at competitive quality.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** LLM layer, agent inference, WebGen pipeline, configuration, governance
- **Documentation Updated:** YES
- **Tests:** CloudLLMClient health + generate + JSON ✓, LLMRouter hybrid routing ✓, cost tracking ✓

### 2025-07-14T12:00:00Z — Dashboard v2: Tabbed Navigation, Token Tracking, Projects Browser

- **Agent:** architecture-governor
- **Files Modified:**
  - `backend/server.py` — Added 5 new REST endpoints:
    - `GET /llm/stats` — Token usage, cost log, budget status, routing breakdown from RouterStats
    - `GET /llm/capacity` — Model capacity info (VRAM, context window, speed/quality tiers) from MODELS registry + Ollama availability check
    - `GET /llm/estimate` — Completion time predictions per available model for a given token count
    - `GET /projects` — Lists all output projects (webgen outputs, content jobs, webgen projects) with human-readable names extracted from HTML `<title>` tags or JSON metadata
    - `GET /projects/{project_id}/files` — File listing for a specific project with size, extension, path
  - `frontend/src/lib/api.ts` — Added TypeScript interfaces: `LLMStats`, `ModelCapacity`, `LLMCapacity`, `LLMEstimate`, `ProjectEntry`, `ProjectsResponse`, `ProjectFilesResponse`. Added API methods: `llmStats()`, `llmCapacity()`, `llmEstimate()`, `projects()`, `projectFiles()`.
  - `frontend/src/app/page.tsx` — Complete rewrite to tabbed dashboard with 6 tabs:
    - **Overview** — Soul panel (goals + reflection), LLM usage at-a-glance cards, live SSE activity stream
    - **Agents** — Full agent grid grouped by tier (0–3) with clickable detail view showing namespace, allowed actions, tool permissions, system prompt, and "Chat with agent" button
    - **Chat** — Agent sidebar (all agents with status) + enhanced chat panel with elapsed time counter, token count display, local-only privacy notice
    - **Projects** — Filterable project grid (by type: Website/Content/WebGen Project) with detail view showing file list, size, dates, status
    - **Token Usage** — Input/output token breakdown, budget progress bar with color thresholds, routing breakdown (local vs cloud), time estimates per model (tok/s → estimated completion time), cost log table, model capacity grid with VRAM/context/speed/quality info
    - **System** — Drift monitor, tool registry, memory overview table, folder analysis (browse + agent analysis), task activity with stats, tool execution logs
  - `frontend/src/app/globals.css` — Added CSS classes: `.tab-nav`, `.tab-btn`, `.tab-active`, `.tab-icon`, `.tab-count`, `.grid-chat` (260px sidebar + 1fr main), `.clickable`, `.tab-filter`, `.tab-filter-active`, `.thinking-dots` (animated loading dots)
- **Reason:** User requested comprehensive dashboard update to: (1) view all agents with full details, (2) use local LLM chat with token tracking, (3) see token usage, budget, and completion time estimates, (4) browse all project outputs with proper human-readable names, (5) maintain drift governance visibility.
- **Risk Assessment:** LOW — Dashboard is read-only (INV-8 compliant). New API endpoints are all GET/read-only. No state mutation beyond existing /chat, /soul/reflect, /soul/goals.
- **Impacted Subsystems:** Frontend dashboard, API server (5 new read-only endpoints), API client types
- **Documentation Updated:** YES — CHANGE_LOG.md updated.

---

### 2026-03-03T00:00:00Z — Repository cleanup + Sandbox + TDD/Lighthouse gate foundations

- **Agent:** architecture-governor
- **Files Modified:**
  - Repository structure: created `reports/`, `playground/`, `sandbox/`, `archive/ibds/`; moved IBDS assets into archive
  - Removed root junk/one-shot files and leaked Lighthouse temp directories
  - `sandbox/session_manager.py` — new ephemeral session manager for `/tmp/ai-sandbox/session-*`
  - `backend/routes/sandbox.py`, `backend/server.py` — sandbox APIs and route registration
  - `backend/agents/gatekeeper_agent.py`, `backend/orchestrator/__init__.py` — Gatekeeper scaffold integration
  - `frontend/package.json` — LHCI + Playwright scripts/deps
  - `reports/lhci/lighthouserc.mobile.js`, `reports/lhci/lighthouserc.desktop.js`
  - `frontend/playwright.config.ts`, `frontend/tests/*.spec.ts`
  - `.github/workflows/lhci-mobile.yml`, `.github/workflows/lhci-desktop.yml`, `.github/workflows/playwright.yml`
  - `scripts/hooks/pre-commit`, `.gitignore`
  - `docs/AGENT_REGISTRY.md`, `docs/SANDBOX_LOG.md`, `docs/TDD_GUIDE.md`, `docs/GATEKEEPER.md`
- **Reason:** Establish a clean production-oriented architecture that isolates experiments, enforces TDD, gates low-reasoning model output, and makes Lighthouse (mobile+desktop) and UI testing blocking quality controls.
- **Risk Assessment:** MEDIUM
- **Impacted Subsystems:** Repo layout, backend API surface, orchestration governance, frontend QA pipeline, CI workflows
- **Documentation Updated:** YES
