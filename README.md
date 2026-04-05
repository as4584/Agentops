# Agentop — Local-First Multi-Agent Control Center

> **1,165+ tests. 63% coverage. 21 agents. 54 tools. 4 languages. Zero cloud dependency.**

A production-grade, fully local multi-agent system for orchestrating AI agents over infrastructure, content creation, web generation, and customer support workflows. Built with FastAPI, LangGraph, Ollama, and Next.js — with performance-critical paths in C, Go, and Rust. Runs entirely on your machine.

[![CI Gate](https://github.com/as4584/Agentops/actions/workflows/ci.yml/badge.svg?branch=dev)](https://github.com/as4584/Agentops/actions/workflows/ci.yml)
[![ML Pipeline](https://github.com/as4584/Agentops/actions/workflows/ml-pipeline.yml/badge.svg)](https://github.com/as4584/Agentops/actions/workflows/ml-pipeline.yml)

---

## Engineering Journey

This section documents the incremental engineering work that brought Agentop from prototype to production-grade. Every change was test-driven, CI-validated, and merged only when green.

### Phase 1 — CI Foundation & Code Quality

**Problem:** No automated quality gates. Broken code could reach `main` undetected.

**What we built:**
- **GitHub Actions CI pipeline** (`ci.yml`) — ruff lint, ruff format, mypy strict mode, pytest with coverage, pip-audit CVE scanning, frontend ESLint + TypeScript + Next.js build, detect-secrets scan
- **ML-specific pipeline** (`ml-pipeline.yml`) — isolated ML test suite with 97% coverage on the ML module
- **Local CI mirror** (`scripts/ci-local.sh`) — reproduces the exact GitHub Actions environment locally so you never push blind. Supports `python`, `frontend`, `quick` modes
- **Pre-push hooks** — runs the full CI gate before any push reaches GitHub
- **Gatekeeper agent wired to real tooling** — `pytest` and `ruff` execute for real instead of trust-based checks

**Result:** 20 consecutive CI runs. Zero false greens. From 0 tests to 1,140 tests at 65% coverage.

### Phase 2 — Polyglot Router (lex-v2)

**Problem:** Routing user messages to the correct agent was slow and unreliable with keyword matching alone.

**What we built:**
- **3-tier routing pipeline:** C pre-filter (< 1ms) → lex-v2 LLM router (3B model via Ollama) → Python keyword fallback
- **C fast router** — compiled shared library (`backend/orchestrator/lex_router_fast.c`) handles unambiguous patterns and red-line blocking at native speed
- **lex-v2 model** — custom 3B router trained on synthetic routing data (60% hard/ambiguous, 20% red-line, 20% easy). Classifies user intent to one of 12 agents with confidence scoring
- **Training data pipeline** (`scripts/generate_training_data.py`, `scripts/synthesize_training_data.py`) — generates JSONL routing examples, trajectory examples, and DPO preference pairs
- **Fine-tuning scripts** (`scripts/finetune_lex.py`, `scripts/train_lex.sh`) — LoRA fine-tuning on routing classification with eval loops

**Result:** Sub-millisecond routing for common patterns, LLM-quality routing for ambiguous cases, hard blocks for dangerous requests.

### Phase 3 — GLM-OCR Document Intelligence

**Problem:** `file_reader` blocked all PDFs and images. `KnowledgeVectorStore` could only index `.md`, `.py`, `.txt` files. Agents couldn't process the most useful document types (spec sheets, research papers, client PDFs).

**What we built:**
- **OCR extraction module** (`backend/ocr/__init__.py`) — async httpx client to GLM-OCR Flask sidecar (0.9B model, smaller than llama3.2, runs on CPU)
- **`document_ocr` tool** — registered as a READ_ONLY native tool in the tool registry. Agents call it explicitly for document understanding
- **`ocr_agent`** — dedicated agent (Tier 2) for document extraction, table parsing, and handwriting recognition. Routes through the standard orchestrator with full keyword and LLM routing support
- **file_reader OCR routing** — PDFs, PNGs, JPGs, TIFFs, WEBPs, DOCXs automatically route through GLM-OCR before hitting the binary block
- **KnowledgeVectorStore expansion** — `.pdf` added to allowed suffixes, OCR extraction integrated into `_collect_documents()`

**Result:** Agents can now read any document type. The knowledge store indexes PDFs. Token waste eliminated — GLM-OCR outputs clean structured Markdown instead of raw document noise.

### Phase 4 — ML Training & Experiment Tracking

**Problem:** No infrastructure for training the lex-v2 router or tracking experiments.

**What we built:**
- **MLflow tracker with JSON fallback** (`backend/ml/`) — logs runs, metrics, and artifacts. Falls back to local JSON when MLflow isn't installed
- **Vector store abstraction** (`backend/ml/vector_store.py`) — Qdrant-backed with numpy fallback for embeddings search
- **Training data synthesizer** — generates routing examples, trajectories, and DPO preference pairs targeting known weak boundaries (knowledge↔soul, monitor↔it, review↔security)
- **Run ID collision fix** — MLflow fallback used `time_ms` for run IDs, causing overwrites when runs completed within the same millisecond. Fixed with monotonic counter (`itertools.count()`)

**Result:** 208 ML tests at 97% coverage. Reproducible experiment tracking. Training pipeline ready for continuous lex-v2 improvement.

### Phase 5 — Automated Dependency Governance

**Problem:** CI failed silently due to stale pip versions with known CVEs. No automated way to detect outdated or vulnerable dependencies.

**What we built:**
- **Dependency checker agent** (`backend/agents/dep_checker.py`) — wraps `pip-audit` (CVE scanning), `pip list --outdated`, and `pyproject.toml` ↔ `requirements.txt` consistency checks
- **Cron automation** — registered in `AgentopScheduler` as `dep_check_daily` at `0 6 * * *` (daily 06:00 UTC)
- **Manual trigger** — `POST /scheduler/dep-check` endpoint
- **CI fix** — `pip install --upgrade pip` before `pip-audit` to prevent pip's own CVEs from blocking the pipeline

**Result:** Zero CVEs across 229 installed packages. Automated daily dependency health reports logged to `shared_events.jsonl`.

### Phase 6 — Security Hardening

**Problem:** API had no authentication, rate limiting, or secret rotation strategy.

**What we built:**
- **API Gateway** (`backend/gateway/`) — ACL enforcement, audit logging, API key auth, rate limiting, secret management
- **Security middleware** (`backend/security_middleware.py`) — request validation and injection detection
- **Secret scanner tool** — 8-pattern regex scan for leaked credentials
- **Doppler migration** — secrets strategy moved from `.env` to Doppler with migration scripts (`scripts/migrate_secrets_to_doppler.py`)
- **9 CVE patches** — resolved all known vulnerabilities in the dependency tree

### Phase 7 — Content & WebGen Pipelines

**Problem:** No automated content creation or website generation capabilities.

**What we built:**
- **Content pipeline** — 9 agents: `IdeaIntake → ScriptWriter → Voice → AvatarVideo → QA → Publisher → Analytics` with caption and trend research agents
- **WebGen pipeline** — 6 agents: `SitePlanner → PageGenerator → SEO → AEO → QA → deploy` with template learning
- **Persistent project store** for webgen with `setup_deps.sh` for dependency management
- **CLI tools** (`cli/content_cli.py`, `cli/webgen_cli.py`) for headless operation

### Phase 8 — Agent Factory & Self-Training Loop

**Problem:** Training data for lex-v2 was manually curated. No automated pipeline.

**What we built:**
- **AgentFactory** (`backend/ml/agent_factory.py`) — collects routing decisions, generates synthetic training data, exports JSONL for fine-tuning
- **DecisionCollector** — hooks into orchestrator to log every routing choice with confidence and reasoning
- **TrainingGenerator** — converts collected decisions into routing examples, trajectory data, and DPO preference pairs
- **85+ JSONL training files** across `data/training/` and `data/dpo/` covering weak boundaries: knowledge↔soul, monitor↔it, review↔security
- **Opus session extraction** — every coding session with Claude generates high-quality training data automatically

**Result:** Self-improving routing loop. Each session makes lex-v2 better at the boundaries where it struggles most.

### Phase 8b — ML Learning Lab

**Problem:** ML infrastructure was spread across 12 modules with no unified entry point. No golden eval set. No way to see overall health at a glance.

**What we built:**
- **LearningLab class** (`backend/ml/learning_lab.py`) — single entry point for training data summary, health reports, golden eval set management, and boundary coverage analysis
- **Golden eval set** — JSONL-based canonical test set (`data/training/golden_eval_set.jsonl`) for regression testing the router across known hard boundaries
- **5 Learning Lab API endpoints** — `GET /api/ml/training/lab/health`, `/lab/summary`, `/lab/golden-tasks`, `/lab/boundaries`, `POST /lab/golden-tasks`
- **Boundary coverage analysis** — automatically scans all training data and reports coverage per agent-pair boundary (knowledge↔soul, monitor↔it, etc.)

**Result:** One-call health check for the entire ML pipeline. Golden eval set ensures lex-v2 never regresses on solved boundaries.

### Phase 9 — Network & Infrastructure Expansion

**Problem:** The system could manage agents but not the network they run on.

**What we built:**
- **IT Agent upgrade** — network expert with SSH node registry, VLAN topology, DNS diagnostics, ER605 firewall ACL rules
- **Network routes** — 7 endpoints for node CRUD, health checks, remote dispatch, fleet topology
- **K8s integration** — Kind cluster with metrics-server, browser-worker pod orchestration, `k8s_metrics` tool
- **ER605 firewall rules** — 5 LAN ACLs for VLAN isolation, DNS pinning, IoT quarantine
- **Agent handoff memory** — inter-agent context passing with TTL-based auto-expiry and consume-once semantics

**Result:** Agents can manage real infrastructure. Network fleet visible. K8s metrics flowing.

### Phase 10 — Browser Security & Skill System

**Problem:** Browser agents surfing the web needed hardening. Skill system had only 1 manifest skill.

**What we built:**
- **Browser security audit** — 5 controls validated (SSRF, secret redaction, session isolation, timeouts, headless)
- **Redirect-chain SSRF protection** — re-validates final URL after browser redirects to prevent SSRF via redirect
- **22 manifest skills** including OpenScreen Demo (ffmpeg-based UI recording), Website Cloner (5-phase pipeline), and domain knowledge packs
- **Knowledge agent ghost fix** — referenced in 70+ files but never registered. Now defined as 21st agent with RAG-focused system prompt
- **Tech news cron jobs** — 3 automated jobs: morning digest (HN, TechCrunch, GitHub Trending), evening security scan, weekly roundup
- **Ollama model pruning** — 9 models → 4, freed ~13.5GB disk

**Result:** 22 skills, 21 agents, hardened browser, automated tech news pipeline, leaner model footprint.

### Phase 11 — External Repo Integration & Repo Cleanup

**Problem:** Sandbox repos (UI/UX Pro Max, OpenClaw/GoClaw, Claude Code skills) were sitting unused. Root directory was cluttered with scratch files. No documentation of the OpenClaw bridge architecture.

**What we built:**
- **UI/UX Design skill** (`backend/skills/ui_ux_design/`) — references the UI/UX Pro Max toolkit: 67 design styles, 161 reasoning rules, 13 framework stacks, BM25 search across 8 domain databases
- **OpenClaw Gateway skill** (`backend/skills/openclaw_gateway/`) — documents how Agentop built on top of OpenClaw/GoClaw: Node.js multi-channel gateway (port 18789) bridging Discord, Telegram, and Slack into the orchestrator via `openclaw_bridge.py`, with 12 red-line firewall patterns and lex-v2 routing at 94.9% accuracy
- **ML Learning Lab skill** (`backend/skills/ml_learning_lab/`) — documents the unified ML experimentation system: 12 components, 54 API endpoints, 3 guided workflows
- **OpenScreen Demo skill** — ffmpeg + browser automation for recording polished demos of the dashboard (MP4/GIF with annotations) for career fairs and portfolio
- **Root directory cleanup** — moved 5 misplaced files (`test_k8s_*.py` → `sandbox/experimental/`, `decode.py`, `read.md`, `output.txt` → `sandbox/scratch/`), added sandbox README, updated `.gitignore` for runtime artifacts

**Result:** 22 manifest skills (up from 17), sandbox repos properly referenced, root directory clean and professional.

### Cumulative Stats

| Metric | Value |
|--------|-------|
| Tests | 1,165+ passed, 5 skipped |
| Coverage | 63% overall (97% on ML module) |
| Agents | 21 core + 9 content + 6 webgen |
| Native tools | 13 (12 original + document_ocr) |
| MCP tools | 26 (via Docker bridge) |
| Browser tools | 8 |
| Skills | 22 manifest + 17 legacy domain packs |
| HTTP endpoints | 195+ across 27 route files |
| Languages | 4 (Python, C, Go, Rust) |
| Cron jobs | 10+ automated |
| Training data files | 186 JSONL (5,624 examples) |
| External integrations | OpenClaw gateway, UI/UX Pro Max, 119 Claude Code skills |
| Files changed (dev cycle) | 520+ files, +56,000+ lines |
| CI pipelines | 2 (CI Gate + ML Pipeline) |
| CVEs | 0 |

---

## Architecture

```
VS Code Extension (@agentop chat participant)
         │ /soul /devops /monitor /security /review /ocr ...
         ▼
Next.js Dashboard (localhost:3007)
         │ REST polling (5s)
         ▼
FastAPI Backend (localhost:8000)
  ├── API Gateway (ACL, audit, auth, rate limiting)
  ├── Security Middleware (injection detection)
  ├── Drift Guard Middleware (governance enforcement)
  ├── LangGraph Orchestrator (stateful routing, fan-out)
  │    ├── C Fast Router (< 1ms, compiled .so)
  │    ├── lex-v2 LLM Router (3B model via Ollama)
  │    └── Python Keyword Fallback
  ├── Agent Registry (21 core agents)
  │    ├── soul_core      — Reflection, trust, goal arbitration
  │    ├── devops_agent    — CI/CD, git, deployment
  │    ├── monitor_agent   — Health, logs, metrics
  │    ├── self_healer     — Fault remediation, restarts
  │    ├── code_review     — Diff review, drift checking
  │    ├── security_agent  — Secret scanning, CVE flagging
  │    ├── data_agent      — ETL, schema, SQLite queries
  │    ├── comms_agent     — Webhooks, incident alerts
  │    ├── cs_agent        — Customer support, FAQ
  │    ├── it_agent        — Infrastructure diagnostics
  │    ├── knowledge_agent — Semantic Q&A over vectors
  │    └── ocr_agent       — Document extraction (GLM-OCR)
  ├── Tool Layer (13 native + 26 MCP + 8 browser)
  ├── GLM-OCR Sidecar (localhost:5002, 0.9B model)
  ├── ML Experiment Tracker (MLflow / JSON fallback)
  ├── Knowledge Vector DB (cosine search, local embeddings)
  ├── Memory Store (namespaced JSON, data/agents/)
  ├── Dependency Checker (daily cron, CVE + outdated scan)
  └── Central Logger (backend/logs/system.jsonl)
         │
         ▼
Ollama (localhost:11434) — llama3.2 + lex-v2
```

---

## Quick Start

### Prerequisites

| Requirement | Version | Purpose |
|-------------|---------|---------|
| Python | >= 3.11 | Backend runtime |
| Node.js | >= 18 | Frontend runtime |
| Ollama | Latest | Local LLM server |
| GCC | Any | C fast router (optional, degrades gracefully) |

### 1. Install & Start Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2
ollama serve
```

### 2. Start the Backend

```bash
cp .env.example .env              # Fill in: AGENTOP_API_SECRET, OLLAMA_MODEL
pip install -r requirements.txt

./scripts/port-check.sh            # Check for port collisions
python -m backend.port_guard serve backend.server:app --host 127.0.0.1 --port 8000
```

### 3. Start the Frontend

```bash
cd frontend && npm install && npm run dev
```

### 4. (Optional) Start GLM-OCR Sidecar

```bash
pip install "glmocr[selfhosted,server]"
python -m glmocr.server           # Port 5002, no API key needed
```

### 5. Open the Dashboard

Navigate to **http://localhost:3007**

---

## CI & Quality Gates

### GitHub Actions (automated on every push to `dev`)

| Check | Tool | Threshold |
|-------|------|-----------|
| Lint | ruff check | 0 errors |
| Format | ruff format --check | 0 diffs |
| Types | mypy --strict | 0 errors |
| Tests | pytest | 1,165+ pass, >= 58% coverage |
| CVEs | pip-audit | 0 vulnerabilities |
| Secrets | detect-secrets | 0 leaked secrets |
| Frontend lint | ESLint | 0 errors |
| Frontend types | tsc --noEmit | 0 errors |
| Frontend build | next build | Exit 0 |

### Local CI (run before pushing)

```bash
./scripts/ci-local.sh              # Full CI mirror (python + frontend + secrets)
./scripts/ci-local.sh python       # Python checks only
./scripts/ci-local.sh quick        # Skip CVE audits (fastest)
```

### Git Workflow

| Branch | Purpose | Push Policy |
|--------|---------|-------------|
| `main` | Production | **NEVER push directly.** Merge only via PR from `dev` after CI is green. |
| `dev` | Active development | Push freely. All feature work happens here. |
| `feature/*` | Optional feature branches | Merge into `dev` via PR or fast-forward. |

Commit messages follow conventional commits: `feat(scope):`, `fix(scope):`, `docs:`, `test:`, `chore:`.

---

## Governance Model

> **Documentation precedes mutation.** No silent architectural changes.

### Governance Documents

| Document | Purpose |
|----------|---------|
| [docs/SOURCE_OF_TRUTH.md](docs/SOURCE_OF_TRUTH.md) | Canonical architecture, agent/tool definitions |
| [docs/CHANGE_LOG.md](docs/CHANGE_LOG.md) | Chronological structural change log |
| [docs/AGENT_REGISTRY.md](docs/AGENT_REGISTRY.md) | Full agent registry with system prompts |
| [docs/DRIFT_GUARD.md](docs/DRIFT_GUARD.md) | Invariants and prohibited patterns |

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

### Drift Detection

The DriftGuard middleware intercepts every tool call. `ARCHITECTURAL_MODIFY` tools require a corresponding documentation update. Invariant violations halt the system (RED status) until resolved.

| Status | Meaning |
|--------|---------|
| 🟢 GREEN | Documentation matches code |
| 🟡 YELLOW | Pending doc update, operations continue |
| 🔴 RED | Invariant violation, execution halted |

---

## Agent Registry

### Core Agents (12)

| Agent | Tier | Role |
|-------|------|------|
| `soul_core` | 0 | Cluster conscience, goal tracking, trust arbitration |
| `devops_agent` | 1 | CI/CD, git ops, deployment coordination |
| `monitor_agent` | 1 | Health surveillance, log tailing, alerting |
| `self_healer_agent` | 1 | Fault remediation, process restarts |
| `code_review_agent` | 2 | Diff review, invariant enforcement |
| `security_agent` | 2 | Secret scanning, CVE flagging |
| `data_agent` | 2 | ETL governance, schema drift, SQLite |
| `ocr_agent` | 2 | Document extraction, table parsing (GLM-OCR) |
| `comms_agent` | 3 | Webhooks, incidents, stakeholder alerts |
| `cs_agent` | 3 | Customer support, FAQ, knowledge base |
| `it_agent` | 3 | Infrastructure diagnostics, network |
| `knowledge_agent` | 3 | Semantic Q&A over vectorized corpus |

### Pipeline Agents

- **Content** (9): idea_intake → script_writer → voice → avatar_video → qa → publisher → analytics + caption, trend_researcher
- **WebGen** (6): site_planner → page_generator → seo → aeo → qa → deploy + template_learner

---

## Tools

### Native (13)

| Tool | Type | Description |
|------|------|-------------|
| `safe_shell` | STATE_MODIFY | Execute whitelisted shell commands |
| `file_reader` | READ_ONLY | Read files, auto-routes PDFs/images through OCR |
| `document_ocr` | READ_ONLY | Extract structured text from documents via GLM-OCR |
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

### MCP (26) — via Docker Bridge

Groups: `github` (7) · `filesystem` (5) · `docker` (5) · `time` (2) · `fetch` (1) · `sqlite` (3) · `slack` (3)

---

## Project Structure

```
Agentop/
├── app.py                         # FastAPI entrypoint (port 8000)
├── backend/
│   ├── agents/                    # Agent definitions + dep_checker
│   ├── gateway/                   # ACL, audit, auth, rate limiting
│   ├── knowledge/                 # Vector DB (cosine search, embeddings)
│   ├── llm/                       # Ollama client, model profiles
│   ├── mcp/                       # MCP gateway bridge (docker mcp CLI)
│   ├── memory/                    # MemoryStore (namespaced JSON)
│   ├── middleware/                # DriftGuard governance middleware
│   ├── ml/                        # MLflow tracker, vector store, training
│   ├── models/                    # Pydantic models
│   ├── ocr/                       # GLM-OCR client (async httpx)
│   ├── orchestrator/              # LangGraph state machine + lex router
│   │   ├── __init__.py            # LangGraph orchestrator
│   │   ├── lex_router.py          # 3-tier routing (C → LLM → keyword)
│   │   └── lex_router_fast.c      # C fast router (compiled .so)
│   ├── routes/                    # FastAPI route handlers (11 files)
│   ├── skills/                    # Skill registry (22 manifest + 17 domain packs)
│   ├── tests/                     # 1,165+ tests
│   ├── tools/                     # 13 native tool implementations
│   └── content/ webgen/ browser/  # Pipeline agents
├── deerflow/                      # DeerFlow integration layer
├── frontend/                      # Next.js dashboard (port 3007)
├── scripts/
│   ├── ci-local.sh                # Local CI mirror
│   ├── generate_training_data.py  # Routing data generator
│   ├── synthesize_training_data.py # DPO preference pairs
│   ├── finetune_lex.py            # LoRA fine-tuning
│   └── setup_deps.sh              # Dependency setup
├── data/training/                 # lex-v2 training JSONL (186 files, 5,624 examples)
├── sandbox/
│   ├── everything-claude-code/    # 119 Claude Code skill packages
│   ├── ui-ux-pro-max-skill/       # UI/UX design intelligence toolkit
│   ├── experimental/              # One-off test scripts
│   └── scratch/                   # Temp files and debug artifacts
├── docs/                          # Governance documents
└── pyproject.toml                 # Python project config + dev deps
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `llama3.2` | Default LLM model |
| `OLLAMA_TIMEOUT` | `120` | LLM request timeout (seconds) |
| `GLMOCR_URL` | `http://localhost:5002` | GLM-OCR sidecar URL |
| `GLMOCR_ENABLED` | `true` | Enable OCR document extraction |
| `AGENTOP_API_SECRET` | — | API authentication secret |
| `BACKEND_PORT` | `8000` | Backend port |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Health check |
| GET | `/health/deps` | Dependency health status |
| GET | `/status` | Full system status |
| POST | `/chat` | Send message to agent |
| GET | `/agents` | List all agents |
| GET | `/agents/{id}` | Agent details |
| GET | `/tools` | List all tools |
| GET | `/drift` | Drift report |
| GET | `/skills` | Skill registry |
| PATCH | `/skills/{id}` | Toggle skill |
| POST | `/scheduler/dep-check` | Trigger dependency audit |
| POST | `/content/pipeline/start` | Start content pipeline |
| POST | `/webgen/build` | Start website generation |
| GET | `/memory` | Memory namespaces |
| GET | `/events` | Shared events |

---

## Port Troubleshooting

```bash
python -m backend.port_guard status    # View port usage
python -m backend.port_guard kill 8000 # Kill conflicting process
./scripts/port-check.sh                # Preflight check
```

---

## Design Principles

1. **Local-first** — No cloud, no paid APIs, no external dependencies at runtime
2. **Documentation-first** — Documentation precedes code mutation
3. **Agent isolation** — Strict namespace and tool boundaries
4. **Observable** — Every action logged, every state visible
5. **Drift-resistant** — Architectural invariants enforced automatically
6. **Test-driven** — Write test first, then implement, CI blocks bad code
7. **Typed** — Full Python type hints (`mypy --strict`), TypeScript frontend

---

## Acknowledgments & Inspirations

| Project | What We Learned | Link |
|---------|-----------------|------|
| **DeerFlow** (ByteDance) | Middleware chains, skill loading, sub-agent delegation | [github.com/bytedance/deer-flow](https://github.com/bytedance/deer-flow) |
| **LangGraph** (LangChain) | Stateful graph orchestration, checkpointing, conditional routing | [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| **LangChain** | LLM abstractions, tool system patterns, chain composition | [github.com/langchain-ai/langchain](https://github.com/langchain-ai/langchain) |
| **GLM-OCR** (THUDM) | Document extraction, multi-modal pre-processing | [github.com/THUDM/GLM-OCR](https://github.com/THUDM/GLM-OCR) |
| **OpenClaw / GoClaw** | Multi-channel gateway pattern — bridging Discord, Telegram, Slack into a unified agent orchestrator. We built `openclaw_bridge.py` with a 12-pattern firewall and rate limiting on top of this architecture | Skill: `backend/skills/openclaw_gateway/` |
| **UI/UX Pro Max** | Design intelligence toolkit — 67 styles, 161 reasoning rules, 13 framework stacks, BM25 search across domain databases | Skill: `backend/skills/ui_ux_design/` |
| **OpenScreen** | Screen recording concept adapted for agent demo creation — ffmpeg x11grab + browser automation for MP4/GIF demos with annotations | Skill: `backend/skills/openscreen_demo/` |
| **Claude Code Skills** (119) | Agentic engineering, eval harness, market research, and 116 more skill packages in `sandbox/everything-claude-code/` — referenced by Agentop's skill system | `sandbox/everything-claude-code/skills/` |

See [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md) for detailed breakdowns.

---

## The Journey — From AI Receptionist to Multi-Agent Control Center

> This section tells the full story. Every phase built on the last. Every problem led to the next solution.

### Table of Contents

1. [Chapter 1: The AI Receptionist](#chapter-1-the-ai-receptionist-origin)
2. [Chapter 2: From Chatbot to Agent](#chapter-2-from-chatbot-to-agent)
3. [Chapter 3: Multi-Agent Architecture](#chapter-3-multi-agent-architecture)
4. [Chapter 4: The Routing Problem](#chapter-4-the-routing-problem)
5. [Chapter 5: Governance & Drift Guard](#chapter-5-governance--drift-guard)
6. [Chapter 6: The Speed Problem](#chapter-6-the-speed-problem--4-languages)
7. [Chapter 7: Self-Improvement Loop](#chapter-7-self-improvement-loop)
8. [Chapter 8: Content & WebGen Pipelines](#chapter-8-content--webgen-pipelines)
9. [Chapter 9: Security Hardening](#chapter-9-security-hardening)
10. [Chapter 10: Where It Stands Now](#chapter-10-where-it-stands-now)

---

### Chapter 1: The AI Receptionist (Origin)

It started as a simple idea: an AI receptionist that could answer questions about a business. A single LLM, a single prompt, a single purpose. But the questions kept getting harder. Users asked about infrastructure. About deployments. About security. One prompt couldn't handle it all.

**Key insight**: A single agent with one prompt breaks down the moment scope exceeds a single domain. You need specialists.

---

### Chapter 2: From Chatbot to Agent

The receptionist evolved: instead of just answering, it could *do things*. Read files. Run shell commands. Check system health. But with tools came danger — an unconstrained agent with `safe_shell` is a liability. The first tool whitelist was born, and with it the first tool safety rules.

**Key insight**: Tools without boundaries are weapons. Every tool needs a whitelist, a blacklist, and an audit log.

---

### Chapter 3: Multi-Agent Architecture

One agent became many. Each specialist got its own system prompt, its own tools, its own memory namespace. The orchestrator was born — a LangGraph state machine that routes messages to the right agent and prevents them from talking to each other directly.

| Evolution Step | What Changed |
|---------------|-------------|
| 1 agent, 1 prompt | Single LLM call |
| 1 agent, tools | File reader, shell, health check |
| N agents, orchestrator | soul_core, devops, monitor, security, ... |
| N agents, governance | INV-1 through INV-10, DriftGuard middleware |

**Key insight**: Agents must NOT call each other directly (INV-2). All communication goes through the orchestrator. This prevents cascading failures and makes every decision auditable.

---

### Chapter 4: The Routing Problem

With 11+ agents, the hardest problem became: *which agent should handle this message?* Keyword matching was fast but dumb. LLM inference was smart but slow. The answer was a 3-tier pipeline:

```
C pre-filter (0.01ms) → lex-v2 LLM (50-200ms) → Python fallback (0.2ms)
```

The `lex-v2` model is a custom 3B router fine-tuned on synthetic routing data. 60% hard/ambiguous cases, 20% red-line blocks, 20% easy. The C pre-filter catches the obvious ones and skips the LLM entirely for ~60-70% of requests.

**Known weak boundaries** (where routing is hardest):
- `knowledge_agent` ↔ `soul_core` — "what is our purpose" = soul, "what does SOURCE_OF_TRUTH say about our purpose" = knowledge
- `monitor_agent` ↔ `it_agent` — "why is the server slow" = monitor, "configure the server's network" = IT
- `code_review_agent` ↔ `security_agent` — "review this diff" = review, "scan this diff for secrets" = security

**Key insight**: Routing is the bottleneck of any multi-agent system. Fast routing enables everything else.

---

### Chapter 5: Governance & Drift Guard

As the system grew, changes started happening without documentation. An agent's tool list would change. A new route would appear. The architecture drifted from the docs. DriftGuard was built to prevent this.

**The 10 invariants:**
- Documentation must precede mutation (INV-5)
- Agents can't modify their own registry (INV-6)
- Memory namespaces can't overlap (INV-4)
- Shared memory is append-only (INV-9)

DriftGuard intercepts every tool call and checks if the proposed action would violate an invariant. Violations halt the system (RED status) until resolved.

**Key insight**: In a multi-agent system, governance isn't a nice-to-have — it's the only thing preventing chaos. Without invariants, agents will eventually corrupt each other.

---

### Chapter 6: The Speed Problem — 4 Languages

Python is great for orchestration. Terrible for hot loops. Three bottlenecks demanded different languages:

| Bottleneck | Language | Speedup |
|-----------|----------|---------|
| Message routing (keyword match) | **C** (`fast_route.c`) | 200x over Python |
| Router benchmarking | **Go** (`router_test.go`) | Goroutine-native harness |
| Embedding compression | **Rust** (`turbo_quant`) | 8x memory reduction |
| Everything else | **Python** | Ecosystem + speed of development |

The C pre-filter compiles to a shared library (`gcc -O3 -shared -fPIC`) and is called via ctypes. The Rust quantizer exposes PyO3 bindings. Go is used for benchmark validation. Python runs the show.

**Key insight**: Use the right language for the right job. Python orchestrates. C filters. Rust compresses. Go benchmarks. The interfaces are clean (ctypes, PyO3, subprocess).

See [docs/LANGUAGE_BENCHMARKS.md](docs/LANGUAGE_BENCHMARKS.md) for full benchmark data.

---

### Chapter 7: Self-Improvement Loop

The system trains itself. Every routing decision is collected as training data. Every conversation with Opus (Claude) generates routing examples, trajectory examples, and DPO preference pairs. These feed back into lex-v2 fine-tuning.

**The loop:**
```
User message → lex-v2 routes → Agent processes → Decision logged
  → TrainingGenerator extracts examples → DPO pairs generated
  → lex-v2 fine-tuned on new data → Better routing next time
```

**Training data types:**
- **Routing examples** — `{user_message, expected_agent, reasoning, confidence, difficulty}`
- **Trajectory examples** — `{task, plan, actions, tools_used, validations, result}`
- **DPO preference pairs** — `{good_response, bad_response, why_good_is_better}`

**Key insight**: The system that collects its own training data can improve faster than one that depends on external annotation. But the quality bar must be high — bad training data makes routing worse, not better.

---

### Chapter 8: Content & WebGen Pipelines

The agent system wasn't just for infrastructure anymore. Two production pipelines were built:

**Content Pipeline** (9 agents):
```
IdeaIntake → ScriptWriter → Voice (4 TTS backends) → AvatarVideo → QA → Publisher → Analytics
```

**WebGen Pipeline** (6 agents):
```
SitePlanner → PageGenerator → SEO → AEO → QA → Deploy
```

Plus a **Website Cloner** skill that reverse-engineers live websites into clean Next.js projects through 5 phases: Reconnaissance → Foundation Build → Component Spec → Page Assembly → Visual QA Diff.

**Key insight**: Multi-agent pipelines aren't just for DevOps. The same orchestration pattern works for content creation, web generation, and any sequential workflow where each step requires different expertise.

---

### Chapter 9: Security Hardening

A system that runs shell commands and browses the web needs real security:

- **SSRF protection** — 13-prefix blocklist + redirect-chain validation on browser navigation
- **API Gateway** — AES-256-GCM secrets, circuit breakers, per-key rate limits, ACL enforcement
- **Secret redaction** — Passwords, tokens, and keys are redacted in all browser logs
- **Session isolation** — Each agent gets its own Playwright browser context (separate cookies, storage)
- **Red-line blocking** — Destructive operations (rm -rf, DROP TABLE, chmod 777) blocked at the C pre-filter level before reaching any agent
- **Browser security audit** — Documented in [docs/BROWSER_SECURITY_AUDIT.md](docs/BROWSER_SECURITY_AUDIT.md)

**Key insight**: Security can't be bolted on. It must be woven into every layer — from the C pre-filter's red-line patterns to the browser's SSRF blocklist to the gateway's per-key encryption.

---

### Chapter 10: Where It Stands Now

| Metric | Count |
|--------|-------|
| Core agents | 21 (11 core + 10 specialized) |
| Pipeline agents | 15 (9 content + 6 webgen) |
| Native tools | 13 |
| MCP tools | 26 (via Docker bridge) |
| Browser tools | 8 |
| HTTP endpoints | 195+ across 27 route files |
| Skills | 22 manifest + 17 legacy domain packs |
| Tests | 1,165+ passing |
| Coverage | 63% (97% on ML module) |
| Languages | 4 (Python, C, Go, Rust) |
| Databases | 4 (SQLite ×3 + JSON stores) |
| Cron jobs | 10+ automated (dep check, social media, tech news) |
| CVEs | 0 |
| Training data files | 186 JSONL (5,624 examples) |
| External integrations | OpenClaw, UI/UX Pro Max, OpenScreen, 119 Claude Code skills |
| Governance invariants | 10 (enforced by DriftGuard middleware) |

**What's connected:**
- VS Code extension (`@agentop` chat participant)
- Discord bot (slash commands → agent routing)
- OpenClaw gateway (Discord/Telegram/Slack → agent routing via openclaw_bridge.py)
- K8s cluster (Kind, metrics-server, browser-worker pods)
- Network fleet (SSH node registry, health checks, remote dispatch)
- Scheduled automation (dependency audits, social media polling, tech news digests)
- OpenScreen recording pipeline (ffmpeg-based demo capture → MP4/GIF)
- ML Learning Lab (unified experiment runner, golden eval set, boundary coverage)

**What's next:**
- [ ] VoiceAgent + AvatarVideoAgent — wire real TTS/video providers
- [ ] PublisherAgent — social platform API integrations
- [ ] Knowledge vector store seeding from project docs
- [ ] Agent handoff memory → full multi-agent chains
- [ ] Proxy/VPN layer for anonymous agent web browsing
- [ ] lex-v3 — larger training corpus, boundary-specific hard negatives
- [ ] OpenClaw — finish Discord integration, implement Telegram/Slack bridges
- [ ] Record demo videos with OpenScreen for portfolio and career fairs

---

## Glossary

| Term | Definition |
|------|-----------|
| **Agent** | An isolated LLM-backed specialist with its own system prompt, tool permissions, and memory namespace |
| **Orchestrator** | LangGraph state machine that routes messages to agents and manages fan-out/fan-in |
| **lex-v2** | Custom 3B parameter router model that classifies user intent to the correct agent |
| **DriftGuard** | Governance middleware that enforces 10 architectural invariants on every tool call |
| **Invariant (INV-N)** | A governance rule that cannot be violated without halting the system |
| **Tool** | A function an agent can call — file_reader, safe_shell, etc. — with safety constraints |
| **MCP** | Model Context Protocol — standard for tool integration; 26 tools via Docker bridge |
| **Namespace** | Isolated memory partition — each agent gets one, cross-access is prohibited (INV-4) |
| **Skill** | A JSON-manifest package that extends agent capabilities without modifying core code |
| **Handoff** | Temporary inter-agent context with TTL-based auto-expiry for multi-agent chains |
| **Red line** | A destructive or dangerous operation pattern that is blocked before reaching any agent |
| **DPO** | Direct Preference Optimization — training method using good/bad response pairs |
| **SSRF** | Server-Side Request Forgery — blocked by URL validation + private network prefix list |
| **Tier** | Agent priority level: Tier 0 (soul) > Tier 1 (critical infra) > Tier 2 (analysis) > Tier 3 (support) |
| **Fan-out** | Orchestrator pattern: send work to multiple agents in parallel, collect results |
| **Pipeline** | Sequential chain of agents where each step's output feeds the next (content, webgen) |
| **TurboQuant** | Rust-based embedding quantizer — 8x compression for knowledge vector store |
| **fast_route** | C shared library for sub-millisecond keyword routing and red-line blocking |
| **Soul** | The soul_core agent — persistent governing intelligence with autobiographical memory |
| **OpenClaw** | Multi-channel gateway bridging Discord/Telegram/Slack into Agentop's orchestrator |
| **OpenScreen** | Screen recording skill using ffmpeg x11grab + browser automation for demo videos |
| **Learning Lab** | Unified ML experimentation entry point — health reports, golden eval set, boundary coverage |
| **Golden Eval Set** | Canonical test cases for regression-testing the lex-v2 router on hard boundaries |
| **Boundary Coverage** | Metric counting training examples per agent-pair boundary (e.g., knowledge↔soul) |

---

## Recording Demos with OpenScreen

> Use the `openscreen_demo` skill to record polished demos of Agentop for career fairs, portfolios, and social media.

### Quick Start

```bash
# Ensure both servers are running
curl -s localhost:8000/health && curl -s localhost:3007 > /dev/null && echo "Ready"

# Record 30-second dashboard demo (requires ffmpeg + Xvfb for headless)
ffmpeg -f x11grab -video_size 1920x1080 -i :0 -t 30 -c:v libx264 -preset fast output/demos/dashboard.mp4

# Convert to GIF for README/social media
ffmpeg -i output/demos/dashboard.mp4 \
  -vf "fps=10,scale=800:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  output/demos/dashboard.gif

# Add annotation overlay
ffmpeg -i output/demos/dashboard.mp4 \
  -vf "drawtext=text='Agentop Control Center':x=20:y=20:fontsize=24:fontcolor=white:box=1:boxcolor=black@0.6" \
  output/demos/dashboard_annotated.mp4
```

### Demo Scenarios

| Scenario | What to Record | Duration |
|----------|---------------|----------|
| **Agent Floor** | Navigate dashboard, show all agents in visual states | 15-30s |
| **Live Chat** | Send a message, watch lex-v2 route → agent respond | 20-30s |
| **Pipeline Run** | Trigger content or webgen pipeline, show progress | 30-60s |
| **ML Learning Lab** | Hit `/api/ml/training/lab/health`, show training stats | 15s |
| **Drift Detection** | Trigger a DriftGuard warning, show RED→GREEN recovery | 20s |

### Output Structure

```
output/demos/
├── dashboard.mp4          # Full resolution recording
├── dashboard.gif          # Optimized GIF for README
├── dashboard_annotated.mp4 # With text overlay
└── thumbnails/            # First-frame PNGs
```

For full methodology, see [backend/skills/openscreen_demo/SKILL.md](backend/skills/openscreen_demo/SKILL.md).

---

## License

MIT
