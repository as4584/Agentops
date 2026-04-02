# Agentop — Local-First Multi-Agent Control Center

> **1,140 tests. 65% coverage. 12 agents. 38 tools. Zero cloud dependency.**

A production-grade, fully local multi-agent system for orchestrating AI agents over infrastructure, content creation, web generation, and customer support workflows. Built with FastAPI, LangGraph, Ollama, and Next.js. Runs entirely on your machine.

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

### Cumulative Stats

| Metric | Value |
|--------|-------|
| Tests | 1,140 passed, 5 skipped |
| Coverage | 65% (97% on ML module) |
| Agents | 12 core + 9 content + 6 webgen |
| Native tools | 13 (12 original + document_ocr) |
| MCP tools | 26 (via Docker bridge) |
| Files changed (dev cycle) | 331 files, +43,552 / -5,486 lines |
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
  ├── Agent Registry (12 core agents)
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
  ├── Tool Layer (13 native + 26 MCP)
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
| Tests | pytest | 1,140 pass, >= 58% coverage |
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
│   ├── skills/                    # Skill registry + 15 domain knowledge packs
│   ├── tests/                     # 1,140 tests
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
├── data/training/                 # lex-v2 training JSONL
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

See [docs/INSPIRATIONS.md](docs/INSPIRATIONS.md) for detailed breakdowns.

---

## License

MIT
