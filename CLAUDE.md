# Agentop — CLAUDE.md

> Local-first multi-agent control center. Documentation-first governance model.
> Last updated: 2026-03-30

---

## Git Workflow & Branch Rules

| Branch | Purpose | Push Policy |
|--------|---------|-------------|
| `main` | Production — career-fair-ready | **NEVER push directly.** Merge only via PR from `dev` after CI is green. |
| `dev` | Active development | Push freely. All feature work happens here. |
| `feature/*` | Optional feature branches off `dev` | Merge into `dev` via PR or fast-forward. |

**Rules for ALL agents and contributors:**
1. **Do NOT push to `main` until CI is green on `dev`.** No exceptions.
2. Every push to `dev` must pass: `ruff check`, `ruff format --check`, `mypy`, `pytest` (≥58% coverage), frontend `npm run build`, and `tsc --noEmit`.
3. Commit messages follow conventional commits: `feat(scope):`, `fix(scope):`, `docs:`, `test:`, `chore:`.
4. Run `python -m pytest backend/tests/ deerflow/tests/ -x --tb=short -q` locally before pushing.
5. When in doubt, commit to `dev` and let CI validate. Never force-push `main`.

---

## What Is Agentop?

Agentop is a production-grade, **fully local** multi-agent system built for orchestrating AI agents over infrastructure, content creation, web generation, and customer support workflows — with zero cloud dependency. It runs entirely on your machine (WSL2 / Linux) with Ollama as the LLM backend.

**Core design principles:**
- Documentation precedes mutation (no silent architectural changes)
- Agents never call each other directly — all communication routes through the orchestrator
- Every agent has an isolated memory namespace
- 38 tools (12 native + 26 MCP via Docker bridge)
- Drift Guard middleware intercepts all tool calls and enforces governance invariants

---

## Architecture

```
VS Code Extension (@agentop chat participant)
         │ /soul /devops /monitor /security /review ...
         ▼
Next.js Dashboard (localhost:3007)
         │ REST polling (5s)
         ▼
FastAPI Backend (localhost:8000)
  ├── Drift Guard Middleware
  ├── LangGraph Orchestrator (stateful routing, fan-out)
  ├── Agent Registry (ALL_AGENT_DEFINITIONS)
  ├── Soul Agent (boot sequence, reflection, trust scoring)
  ├── Tool Layer (12 native tools)
  ├── MCP Gateway Bridge (26 tools via docker mcp CLI)
  ├── Knowledge Vector DB (cosine search, local embeddings)
  ├── Memory Store (namespaced JSON, data/agents/)
  └── Central Logger (backend/logs/system.jsonl)
         │
         ▼
Ollama (localhost:11434) — llama3.2 by default
```

---

## Folder Structure

```
Agentop/
├── .agentctx/
│   └── lex.md                    # Dev environment context (Lex's machine, WSL, servers)
├── .env.example                  # Environment variable template
├── .github/
│   ├── prompts/                  # VS Code prompt files (engineering disciplines)
│   └── workflows/                # CI: Playwright, Lighthouse (desktop + mobile)
├── README.md                     # Quick start guide
├── app.py                        # FastAPI app entrypoint (port 8000)
├── backend/
│   ├── a2ui/                     # Agent-to-UI event bus (SSE streaming)
│   ├── agents/                   # Core orchestration agents
│   │   ├── gatekeeper_agent.py   # Security + policy enforcement
│   │   └── gsd_agent.py          # Get Stuff Done — task decomposition
│   ├── browser/                  # Browser automation session + tooling
│   ├── config.py                 # All config constants (paths, ports, limits)
│   ├── content/                  # Content creation pipeline (full pillar)
│   ├── database/                 # Customer store, GSD store (SQLite)
│   ├── gateway/                  # API gateway: ACL, audit, auth, rate limiting, secrets
│   ├── knowledge/                # LLM model registry, vector DB interface
│   ├── llm/                      # Ollama client, model profiles, unified registry
│   ├── mcp/                      # MCP gateway bridge (docker mcp CLI)
│   ├── memory/                   # MemoryStore class (namespaced JSON persistence)
│   ├── middleware/                # Drift Guard middleware
│   ├── models/                   # Pydantic models (agent, tool, drift, task)
│   ├── orchestrator/             # LangGraph state machine (routing, fan-out)
│   ├── routes/                   # FastAPI route handlers
│   │   ├── skills.py             # Skill registry CRUD endpoints
│   │   ├── agent_control.py      # Agent start/stop/status
│   │   ├── content_pipeline.py   # Content creation endpoints
│   │   ├── gateway.py            # Main chat gateway
│   │   ├── gsd.py                # GSD task management
│   │   ├── memory_management.py  # Memory CRUD
│   │   ├── webgen_builder.py     # Website generation API
│   │   └── ...                   # (11 total route files)
│   ├── skills/                   # Skill system
│   │   ├── registry.py           # SkillRegistry — load, toggle, validate skills
│   │   ├── loader.py             # Loads JSON or manifest-format skills
│   │   ├── newsletter_weekly_tips/ # Only registered skill (JSON format)
│   │   └── data/                 # Legacy skill data
│   ├── tools/                    # 12 native tool implementations
│   ├── utils/                    # Logger, tool ID registry, helpers
│   ├── webgen/                   # Website generation pillar
│   │   └── agents/               # AEO, base, page generator, QA, SEO, site planner, template learner
│   └── websocket/                # WebSocket handlers
├── docs/                         # Governance documents
│   ├── SOURCE_OF_TRUTH.md        # Canonical architecture + agent/tool definitions
│   ├── AGENT_REGISTRY.md         # Full agent registry with system prompts
│   ├── CHANGE_LOG.md             # Chronological structural change log
│   └── DRIFT_GUARD.md            # Invariants and prohibited patterns
├── frontend/                     # Next.js dashboard (localhost:3007)
├── animation_salvage_lab/        # Hailuo AI video animation agent + docs
├── pixel-agents/                 # Experimental pixel-level agent work
├── sandbox/                      # Reference implementations
│   ├── everything-claude-code/   # Claude Code skill library (30+ skills)
│   └── ui-ux-pro-max-skill/      # UI/UX skill implementation
├── SigmaSimulator/               # Sigma simulation project
└── scripts/                      # Port check, dev scripts
```

---

## Agent Registry

All agents are defined in `backend/agents/__init__.py → ALL_AGENT_DEFINITIONS`.

| Agent | Tier | Role | Impact |
|---|---|---|---|
| `soul_core` | 0 | Cluster conscience, goal tracking, trust arbitration | CRITICAL |
| `devops_agent` | 1 | CI/CD, git ops, deployment coordination | HIGH |
| `monitor_agent` | 1 | Health surveillance, log tailing, alerting | LOW |
| `self_healer_agent` | 1 | Fault remediation, process restarts | HIGH |
| `code_review_agent` | 2 | Diff review, invariant enforcement, drift checking | MEDIUM |
| `security_agent` | 2 | Passive secret scanning, CVE flagging | MEDIUM |
| `data_agent` | 2 | ETL governance, schema drift, SQLite queries | MEDIUM |
| `comms_agent` | 3 | Outbound webhooks, incidents, stakeholder alerts | MEDIUM |
| `cs_agent` | 3 | Customer support, query handling, knowledge base | LOW |
| `it_agent` | 3 | Infrastructure monitoring, diagnostics | HIGH |
| `knowledge_agent` | 3 | Semantic Q&A over local vectorized corpus | MEDIUM |

**Content pipeline agents** (in `backend/content/`): `script_writer`, `voice_agent`, `avatar_video_agent`, `qa_agent`, `publisher_agent`, `analytics_agent`, `idea_intake_agent`, `caption_agent`, `trend_researcher`

**Webgen pipeline agents** (in `backend/webgen/agents/`): `AEOAgent`, `SEOAgent`, `SitePlanner`, `PageGenerator`, `QAAgent`, `TemplateLearner`

---

## Native Tools (12)

| Tool | Type | Description |
|---|---|---|
| `safe_shell` | STATE_MODIFY | Execute whitelisted shell commands |
| `file_reader` | READ_ONLY | Read file contents safely |
| `doc_updater` | ARCH_MODIFY | Update governance documentation |
| `system_info` | READ_ONLY | Retrieve system information |
| `webhook_send` | STATE_MODIFY | HTTP POST to external endpoints |
| `git_ops` | READ_ONLY | Whitelisted git subcommands |
| `health_check` | READ_ONLY | HTTP reachability check |
| `log_tail` | READ_ONLY | Tail N lines from a log file |
| `alert_dispatch` | STATE_MODIFY | Write structured alert to shared events |
| `secret_scanner` | READ_ONLY | 8-pattern regex scan for secrets |
| `db_query` | READ_ONLY | SELECT/PRAGMA against local SQLite |
| `process_restart` | STATE_MODIFY | Restart whitelisted processes |

## MCP Tools (26) — via Docker MCP Bridge

Routed through `backend/mcp/__init__.py` MCPBridge. Degrades gracefully if Docker CLI absent.

Groups: `github` (7) · `filesystem` (5) · `docker` (5) · `time` (2) · `fetch` (1) · `sqlite` (3) · `slack` (3)

---

## Skill System

Skills are JSON-manifest packages that extend agent capabilities without modifying core code.

**Skill discovery:** `backend/skills/registry.py → SkillRegistry.reload()` scans `backend/skills/` for subdirectories with `skill.json` or manifest format.

**API endpoints:** `GET /skills` · `GET /skills/{id}` · `PATCH /skills/{id}` (toggle enabled)

**Registered skills:**
| Skill ID | Name | Allowed Agents | Description |
|---|---|---|---|
| `newsletter_weekly_tips` | Newsletter Weekly Tips | GSDAgent, ContentAgent | Generates Damian's weekly email newsletter via local Ollama |

**Adding a new skill (manifest format):** Create `backend/skills/<skill_id>/skill.json` with fields: `id`, `name`, `version`, `description`, `allowed_agents`, `required_tools`, `risk_level`, `enabled`.

**Legacy skills** (`backend/skills/data/` — 15 JSON domain knowledge packs injected into agent prompts):

| Skill File | Domain |
|---|---|
| `agent_design_patterns.json` | Agent architecture patterns |
| `applied_enterprise_ai.json` | Enterprise AI implementation |
| `business_analysis.json` | Business analysis frameworks |
| `business_operations.json` | Operations knowledge |
| `community_ai_training.json` | Community/training AI |
| `data_knowledge_systems.json` | Data systems design |
| `frontend_architecture.json` | Frontend architecture |
| `fullstack_engineering.json` | Full-stack engineering |
| `hexagonal_architecture.json` | Hexagonal/ports-and-adapters |
| `infrastructure_resilience.json` | Infrastructure resilience |
| `release_engineering.json` | Release/CI-CD engineering |
| `state_machine_design.json` | State machine patterns |
| `systems_analysis_design.json` | Systems analysis |
| `token_optimization.json` | LLM token cost optimization |
| `web_development_inquiry.json` | Web development patterns |

---

## GitHub Prompts (VS Code Prompt Files)

Located in `.github/prompts/` — invoke via `@workspace` or `#file:` in VS Code Copilot chat:

| File | Purpose |
|---|---|
| `agentic-engineering.prompt.md` | Task decomposition, eval-first loop, model tier routing |
| `context-budget.prompt.md` | Token budget discipline for long-running tasks |
| `cost-aware-llm-pipeline.prompt.md` | Model tier selection, cost optimization |
| `deep-research.prompt.md` | Multi-source research methodology |
| `e2e-testing.prompt.md` | End-to-end test patterns with Playwright |
| `python-patterns.prompt.md` | Python coding standards for Agentop |
| `security-review.prompt.md` | Security audit checklist |
| `tdd-workflow.prompt.md` | Test-driven development loop |
| `verification-loop.prompt.md` | Self-verification pattern for agent outputs |
| `website-builder.prompt.md` | WebGen pipeline guidance |

---

## Workflow Connections

```
User / VS Code Extension
  → POST /chat (gateway.py)
  → GatekeeperAgent (prompt injection check, ACL)
  → LangGraph Orchestrator (intent routing via Soul)
  → Target Agent (process_message → tool calls)
  → Memory write (agent namespace)
  → SSE stream → A2UI bus → Dashboard / VS Code panel
```

**Content pipeline:** `IdeaIntakeAgent → ScriptWriterAgent → VoiceAgent → AvatarVideoAgent → QAAgent → PublisherAgent → AnalyticsAgent`

**WebGen pipeline:** `SitePlanner → PageGenerator → SEOAgent → AEOAgent → QAAgent → (deploy)`

**GSD tasks:** `GSDAgent → task_tracker (SQLite) → fan-out to specialist agents → result aggregation`

---

## How Other Projects Reference Agentop Skills

1. **HTTP API** — POST to `http://localhost:8000/chat` with `{"agent": "gsd", "message": "..."}` from any project
2. **Skill invocation** — POST to `http://localhost:8000/skills/{skill_id}/run`
3. **Content pipeline** — POST to `http://localhost:8000/content/pipeline/start`
4. **WebGen** — POST to `http://localhost:8000/webgen/build`
5. **VS Code** — use `@agentop /soul`, `@agentop /devops`, etc. in any workspace

The `.agentctx/lex.md` file stores persistent dev environment context (server IPs, deploy process, machine setup) that agents read on boot.

---

## Environment Setup

```bash
cp .env.example .env
# Fill in: AGENTOP_API_SECRET, OPENROUTER_API_KEY (optional), OLLAMA_MODEL

# Start Ollama
ollama serve && ollama pull llama3.2

# Backend (from Agentop root)
pip install -r requirements.txt
python -m backend.port_guard serve backend.server:app --host 127.0.0.1 --port 8000

# Frontend
cd frontend && npm install && npm run dev
```

---

## TODO / Gaps

- [ ] **Only 1 manifest skill** (`newsletter_weekly_tips`) — 15 legacy JSON domain skills exist in `backend/skills/data/` but no manifest-format skills beyond newsletter. Wire the legacy skills into the registry or convert to manifest format
- [ ] **WebGen pipeline** is implemented but not wired to a persistent project store — `SiteProject` state is in-memory only
- [ ] **VoiceAgent and AvatarVideoAgent are stubs** — no real TTS (ElevenLabs key exists in `.env`) or video provider (Fal AI key exists) wired in yet
- [ ] **PublisherAgent** — no social platform API integrations implemented
- [ ] **Animation Salvage Lab** (`animation_salvage_lab/`) has docs and a Hailuo agent prompt guide but no Python agent implementation yet
- [ ] **SigmaSimulator** (`SigmaSimulator/`) has `default.project.json` but no implementation — unclear purpose
- [ ] **Pixel Agents** (`pixel-agents/`) appears to be experimental — no integration with main backend
- [ ] **MCP Gateway** requires Docker CLI — no fallback tests documented; graceful degradation path needs integration test
- [ ] **Knowledge Vector Store** — no scripts to seed the vector DB from project docs; embeddings pipeline is defined but setup is manual
- [ ] **CORS** — `app.py` CORS origins are env-var-controlled (`AGENTOP_CORS_ORIGINS`) but not validated at startup
- [ ] **Secrets** — `.env` is gitignored but `.env` itself exists in the repo root with real values — rotate and move to Doppler
- [ ] **Dashboard** runs on port 3007 but README says 3000 — fix README
- [ ] **Everything-Claude-Code sandbox** (`sandbox/everything-claude-code/`) has 30+ skills — none are imported into the Agentop skill registry yet
