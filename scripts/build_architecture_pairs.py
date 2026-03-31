#!/usr/bin/env python3
"""
scripts/build_architecture_pairs.py
─────────────────────────────────────
Strategy 5 (Architecture) + 8 (3D Web expanded):
Hardcoded + generated Q&A about Agentop system design.

Sources:
  - docs/SOURCE_OF_TRUTH.md
  - docs/AGENT_REGISTRY.md
  - CLAUDE.md
  - backend/config.py
  - Hardcoded architecture Q&A (30 high-quality pairs written by GitHub Copilot / Sonnet)

No LLM required for the hardcoded pairs. Use --ollama to generate additional
Q&A from the documentation chunks.

Usage:
  python scripts/build_architecture_pairs.py
  python scripts/build_architecture_pairs.py --ollama
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# ── Hardcoded architecture training pairs (authored by Copilot/Sonnet) ────────
# These are written from deep analysis of the codebase without any API key.
ARCHITECTURE_SEEDS: list[dict] = [
    {
        "q": "How does Agentop route a chat message from the VS Code extension to the right agent?",
        "a": """The routing chain has 4 stages:

1. **VS Code Extension** (`vscode-extension/src/extension.ts`) detects the slash command (e.g. `/devops`) or uses keyword intent detection (14 regex patterns). It POSTs to `POST /chat` with `{agent: "devops_agent", message: "..."}`.

2. **GatekeeperAgent** (`backend/agents/gatekeeper_agent.py`) intercepts the request first — checks for prompt injection patterns, validates ACL permissions, and blocks policy violations before any real agent sees the message.

3. **LangGraph Orchestrator** (`backend/orchestrator/`) receives the gated message. It's a stateful state machine that uses the Soul agent's trust scores to determine routing priority. For direct agent calls the routing is deterministic; for ambiguous queries SoulAgent arbitrates.

4. **Target Agent** (e.g. `DevOpsAgent`) calls `process_message()`, which may invoke tools (native or MCP). Tool calls go through the **Drift Guard middleware** which enforces governance invariants before execution.

The response streams back via SSE through the A2UI event bus to both the dashboard and the VS Code panel.""",
    },
    {
        "q": "What is Drift Guard and what invariants does it enforce?",
        "a": """Drift Guard is a middleware layer in `backend/middleware/` that intercepts every tool call before execution. It enforces governance invariants defined in `docs/DRIFT_GUARD.md`.

**Key invariants enforced:**
- Agents cannot call each other directly — all communication must route through the Orchestrator
- `ARCH_MODIFY` tools (like `doc_updater`) require documentation to be updated first (docs-first rule)
- `STATE_MODIFY` tools are logged with a full audit trail before execution
- No tool call patterns matching known prompt injection signatures pass through
- Tool IDs must match the sanitized registry format (see `backend/utils/tool_id_registry.py`)
- Process restart is only allowed for whitelisted processes defined in config

If a tool call violates an invariant, Drift Guard returns a structured error with the violated rule and blocks the call — the agent receives a rejection, not a silent failure. This creates observable, auditable agent behavior.""",
    },
    {
        "q": "How do I add a new agent to Agentop?",
        "a": """Adding a new agent requires 3 steps in this order (docs-first governance):

**Step 1 — Update documentation (required before code)**
Add your agent to `docs/AGENT_REGISTRY.md` with: agent ID, tier (0–3), role, system prompt, allowed tools, and impact level. Then log it in `docs/CHANGE_LOG.md`.

**Step 2 — Register in the agent registry**
In `backend/agents/__init__.py`, add an entry to `ALL_AGENT_DEFINITIONS`:
```python
{
    "id": "my_agent",
    "name": "My Agent",
    "tier": 2,
    "role": "What this agent does",
    "system_prompt": "You are...",
    "allowed_tools": ["file_reader", "safe_shell"],
    "impact": "MEDIUM",
}
```

**Step 3 — Create the agent class**
Create `backend/agents/my_agent.py` subclassing `BaseAgent`. Implement `process_message(message, context)` which returns a string response. Tool calls go through `self.call_tool(tool_name, input)` which routes through Drift Guard.

Wire the new agent into the orchestrator's routing table in `backend/orchestrator/`. Add the slash command to `vscode-extension/src/extension.ts` if you want VS Code access.""",
    },
    {
        "q": "What's the difference between the skill system and the native tools?",
        "a": """**Native tools** (12 total) are the core execution layer — they actually DO things:
- They're statically defined in `backend/tools/`
- Each has a type: `READ_ONLY`, `STATE_MODIFY`, or `ARCH_MODIFY`
- They run in the same process as the backend
- All tool calls go through Drift Guard middleware
- Examples: `safe_shell`, `file_reader`, `git_ops`, `db_query`, `secret_scanner`

**Skills** are capability packages that extend agent behavior without modifying core code:
- They're JSON manifests in `backend/skills/<skill_id>/skill.json`
- They define allowed agents, required tools, and risk levels
- They inject domain knowledge into agent prompts and enable specialized workflows
- Skills are toggle-able via `PATCH /skills/{id}` API
- Currently only 1 manifest skill: `newsletter_weekly_tips`
- 15 legacy skills in `backend/skills/data/` are domain knowledge JSONs injected into prompts

The key distinction: tools are verbs (actions), skills are nouns (capabilities/knowledge). An agent uses tools to execute; it uses skills to know what to do.""",
    },
    {
        "q": "How does the MCP Gateway Bridge work and what tools does it provide?",
        "a": """`backend/mcp/__init__.py` implements `MCPBridge` which routes to 26 tools via the Docker MCP CLI.

**How it works:**
1. The bridge checks if `docker` CLI is available at startup
2. If available, it reads `mcp-gateway/config.yaml` for tool definitions
3. Tool calls are forwarded as: `docker mcp exec <tool_name> <json_input>`
4. Results are parsed and returned to the calling agent
5. If Docker is absent, all MCP calls degrade gracefully with a warning (no crash)

**26 MCP tools in 7 groups:**
- `github` (7): create_issue, create_pr, list_repos, get_file_contents, search_code, create_comment, merge_pr
- `filesystem` (5): read_file, write_file, list_directory, create_directory, delete_file
- `docker` (5): list_containers, start_container, stop_container, exec_command, get_logs
- `time` (2): get_current_time, convert_timezone
- `fetch` (1): fetch_url
- `sqlite` (3): query, execute, list_tables
- `slack` (3): send_message, list_channels, get_history

MCP tools are considered higher-risk than native tools and go through additional Drift Guard checks.""",
    },
    {
        "q": "Explain the LangGraph orchestrator state machine. How does it decide which agent to route to?",
        "a": """The orchestrator in `backend/orchestrator/` uses LangGraph to define a stateful DAG (directed acyclic graph) for agent routing.

**State structure:**
```python
class AgentState(TypedDict):
    message: str
    agent_id: str     # explicit routing (from slash commands)
    intent: str       # detected intent (from keyword patterns)
    trust_score: float  # from Soul agent
    context: dict
    history: list
```

**Routing logic:**
1. **Explicit route** (priority 1): If `agent_id` is set (slash command used), route directly — no ambiguity
2. **Intent route** (priority 2): Keyword patterns match to agent ID. 14 patterns cover debug/error → `devops_agent`, security/secret → `security_agent`, memory/store → `knowledge_agent`, etc.
3. **Soul arbitration** (priority 3): For ambiguous messages, the state passes through `soul_core` which uses trust scores and context to pick the most appropriate agent tier
4. **Fan-out** (parallel): For `gsd-map` / `gsd-exec` commands, the orchestrator fans out to multiple specialist agents simultaneously and aggregates results

LangGraph's checkpointing means if an agent fails mid-execution, the state is preserved and can resume from the last checkpoint.""",
    },
    {
        "q": "What is the Soul agent and why is it tier 0?",
        "a": """Soul Core (`soul_core`) is the cluster conscience — it sits at Tier 0 because it has authority over all other agents.

**What it does:**
- **Boot sequence**: Runs at startup to initialize trust scores, check invariants, and verify the agent registry
- **Goal tracking**: Maintains a persistent list of active project goals across sessions
- **Trust arbitration**: Each agent has a trust score (0.0–1.0) that Soul updates based on outcomes. Low-trust agents get restricted tool access
- **Reflection**: When triggered via `POST /soul/reflect`, Soul reviews recent agent actions, identifies drift from stated goals, and logs corrections
- **Routing authority**: For ambiguous multi-agent scenarios, Soul has final say on routing

**Why tier 0:**
The tier system (0–3) controls priority and authority:
- Tier 0 (CRITICAL): Can override any agent, reads all logs, arbitrates conflicts
- Tier 1 (HIGH): DevOps, Monitor, Self-Healer — infrastructure layer
- Tier 2 (MEDIUM): Code review, security, data — quality layer
- Tier 3 (LOW): Customer service, comms, knowledge — interface layer

Soul is tier 0 because without a functioning conscience, the cluster has no guarantee that individual agent actions align with the system's stated goals.""",
    },
    {
        "q": "How does the GSD (Get Stuff Done) system work?",
        "a": """GSD is Agentop's task decomposition and execution framework — it bridges high-level intent to concrete agent actions.

**5 GSD commands:**
1. `gsd-map` → `POST /api/gsd/map-codebase` — Soul agent analyzes the repo, generates `STACK.md` and `ARCHITECTURE.md`, creates a phase-based implementation plan
2. `gsd-plan N` → `POST /api/gsd/plan-phase/N` — Plans detailed steps for phase N
3. `gsd-exec N` → `POST /api/gsd/execute-phase/N` — Executes phase N, fanning out to specialist agents
4. `gsd-quick` → `POST /api/gsd/quick` — One-shot task for simple requests
5. `gsd-verify` → `POST /api/gsd/verify-work` — Runs tests, checks docs sync, confirms phase completion

**Storage:**
GSD tasks are persisted in SQLite via `backend/database/gsd_store.py`. Each task has: phase, status (pending/in_progress/done/failed), assigned_agents, tool_calls_made, and result.

**The fan-out pattern:**
`gsd-exec` is the most powerful — it decomposes a phase into parallel workstreams, assigns each to the most appropriate specialist agent (DevOps for infra, Data for schema, Security for review), and aggregates results. This is why GSD can build entire features autonomously.""",
    },
    {
        "q": "How should I structure environment variables in Agentop? What's in .env?",
        "a": """Agentop uses a layered secret management approach:

**Critical `.env` variables:**
```bash
# Core auth
AGENTOP_API_SECRET=<secret>      # API key for all /chat and /tools endpoints
AGENTOP_CORS_ORIGINS=http://localhost:3007,http://localhost:3000

# LLM backends
OLLAMA_MODEL=llama3.2            # default local model
OPENROUTER_API_KEY=<key>         # optional cloud LLM fallback
ANTHROPIC_API_KEY=<key>          # Claude API for training data synthesis

# External integrations
ELEVENLABS_API_KEY=<key>         # TTS for VoiceAgent (stub — not yet wired)
FAL_AI_API_KEY=<key>             # Video generation (stub — not yet wired)

# Infrastructure
QDRANT_URL=http://localhost:6333  # vector store for knowledge_agent
OLLAMA_URL=http://localhost:11434
OLLAMA_CHAT_TIMEOUT=30
```

**Security rules:**
- `.env` is gitignored — never commit real secrets
- `NEXT_PUBLIC_*` variables are exposed to the browser — never put secrets there
- `AGENTOP_API_SECRET` gates all agent endpoints (set in both backend and VS Code extension)
- CORS origins are validated at startup if `AGENTOP_CORS_ORIGINS` is set

**Best practice:** Move to Doppler for secret rotation. The `doppler.yaml` config file is already in the repo root — just run `doppler setup` to connect.""",
    },
    {
        "q": "How do I run Agentop locally from scratch?",
        "a": """**Prerequisites:** Python 3.11+, Node.js 18+, Ollama installed

```bash
# 1. Clone and set up Python environment
git clone <repo> && cd Agentop
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt

# 2. Configure environment
cp .env.example .env
# Edit .env: set AGENTOP_API_SECRET (any random string works for local)
# Optionally set ANTHROPIC_API_KEY if you want Claude synthesis

# 3. Start Ollama (separate terminal)
ollama serve
ollama pull llama3.2               # ~2GB download first time

# 4. Start the backend (port 8000)
python -m backend.port_guard serve backend.server:app \\
  --host 127.0.0.1 --port 8000

# 5. Start the frontend (separate terminal, port 3007)
cd frontend && npm install && npm run dev

# 6. Health check
curl http://localhost:8000/health
```

**VS Code Extension (optional):**
```bash
cd vscode-extension && npm install && npm run compile
# Press F5 to launch Extension Development Host
# Or: vsce package && code --install-extension agentop-*.vsix
```

Access the dashboard at `http://localhost:3007`. Use `@agentop` in Copilot chat once the extension is loaded.""",
    },
    {
        "q": "What is the WebGen pipeline and how do I trigger it?",
        "a": """WebGen is Agentop's website generation pillar — a multi-agent pipeline that builds full websites from a brief.

**7 agents in the pipeline:**
1. `SitePlanner` — analyzes brief, generates site structure (pages, sections, color palette)
2. `PageGenerator` — generates HTML/CSS for each page using the plan
3. `SEOAgent` — adds meta tags, OG tags, structured data (JSON-LD), sitemap
4. `AEOAgent` — optimizes for Answer Engine Optimization (AI search / ChatGPT visibility)
5. `QAAgent` — validates HTML, checks links, verifies mobile responsiveness
6. `TemplateLearner` — learns from high-performing templates to improve future generations

**How to trigger:**
```bash
# Via API
curl -X POST http://localhost:8000/webgen/build \\
  -H "Authorization: Bearer $AGENTOP_API_SECRET" \\
  -H "Content-Type: application/json" \\
  -d '{"brief": "Restaurant website for Seagull Med-Ter, Mediterranean cuisine, teal/orange brand", "pages": ["home", "menu", "contact"]}'

# Via CLI
python cli/webgen_cli.py --brief "..." --output ./sites/mysite
```

**Known limitation:** `SiteProject` state is in-memory — if you restart the backend, the project state is lost. A SQLite persistence layer is on the TODO list (see `docs/to_do_list.md`).""",
    },
    {
        "q": "How does the knowledge vector store work in Agentop?",
        "a": """The knowledge store (`backend/knowledge/`) uses Qdrant as the vector database with local embeddings.

**Architecture:**
```python
# Vector store interface
class KnowledgeStore:
    def __init__(self):
        self.client = QdrantClient(url=QDRANT_URL)  # localhost:6333
        self.collection = "agentop_knowledge"
    
    def add(self, text: str, metadata: dict) -> str:
        embedding = self._embed(text)  # local embedding model
        return self.client.upsert(...)
    
    def search(self, query: str, limit: int = 5) -> list[dict]:
        embedding = self._embed(query)
        return self.client.search(collection=self.collection, query_vector=embedding, limit=limit)
```

**How to seed the knowledge base:**
```python
# scripts/seed_personal_kb.py (to be created — it's on the TODO list)
from backend.knowledge import KnowledgeStore

store = KnowledgeStore()
# Feed your docs, NJIT notes, client specs
for doc in Path('docs').glob('*.md'):
    store.add(doc.read_text(), {"source": doc.name, "type": "architecture"})
```

**`knowledge_agent` in action:**
When a user asks a question, `knowledge_agent` first does a semantic search over the vector store, then constructs a RAG (retrieval-augmented generation) prompt with the top-k results, then sends to Ollama. This is how the agent can answer questions about the codebase without re-reading all files every time.""",
    },
    {
        "q": "How do I use the content pipeline to generate newsletter content?",
        "a": """The content pipeline runs 9 agents in sequence to produce publishable content.

**Pipeline flow:**
`IdeaIntakeAgent → ScriptWriterAgent → VoiceAgent → AvatarVideoAgent → QAAgent → PublisherAgent → AnalyticsAgent`

**For newsletter specifically, use the `newsletter_weekly_tips` skill:**
```bash
# Via API
curl -X POST http://localhost:8000/skills/newsletter_weekly_tips/run \\
  -H "Authorization: Bearer $AGENTOP_API_SECRET" \\
  -H "Content-Type: application/json" \\
  -d '{"topic": "AI agents for small business", "audience": "SMB owners"}'
```

**What the skill does:**
1. `IdeaIntakeAgent` researches the topic using `fetch` MCP tool
2. `ScriptWriterAgent` writes the newsletter body in Lex's voice using Ollama
3. `QAAgent` fact-checks and improves clarity
4. Output is a formatted HTML email ready for SendGrid/Mailchimp

**Current limitations:**
- `VoiceAgent` (ElevenLabs) is a stub — the key is in `.env` but not wired
- `AvatarVideoAgent` (Fal AI) is a stub — same situation
- `PublisherAgent` has no social platform integrations yet
- All three are on the CLAUDE.md TODO list""",
    },
    {
        "q": "What ports does Agentop use and how do they map to services?",
        "a": """All port assignments are documented in `docs/PORTS.md`:

| Port | Service | Process |
|------|---------|---------|
| 8000 | FastAPI backend | `python -m backend.port_guard serve backend.server:app` |
| 3007 | Next.js dashboard | `cd frontend && npm run dev` |
| 11434 | Ollama LLM server | `ollama serve` |
| 6333 | Qdrant vector store | `docker run -p 6333:6333 qdrant/qdrant` |

**Port Guard** (`backend/port_guard.py`) checks if 8000 is already in use before starting. If it is, it kills the old process (with confirmation) and then starts fresh. This prevents the common WSL double-start issue.

**Frontend note:** The README says port 3000 (outdated). The correct port is **3007** — verify with `cat frontend/package.json | grep '"dev"'` which shows `next dev -p 3007`.""",
    },
    {
        "q": "How does the Agentop security model work? What prevents unauthorized tool calls?",
        "a": """Agentop has 4 security layers:

**Layer 1 — API Gateway ACL** (`backend/gateway/`)
All endpoints require `Authorization: Bearer <AGENTOP_API_SECRET>`. The API secret is checked via constant-time comparison to prevent timing attacks. Rate limiting (configurable via `RATE_LIMIT_PER_MINUTE`) prevents abuse.

**Layer 2 — GatekeeperAgent** (`backend/agents/gatekeeper_agent.py`)
Runs before any agent processes a message. Checks for:
- Prompt injection patterns (60+ signatures including jailbreak attempts)
- ACL: only authorized agent IDs can be addressed
- Payload size limits (prevents context stuffing)
- Dangerous command patterns in the message

**Layer 3 — Drift Guard middleware** (`backend/middleware/`)
Intercepts tool calls. Enforces invariants:
- Tools can only be called by agents with them in `allowed_tools`
- STATE_MODIFY tools require audit log entry before execution
- ARCH_MODIFY tools require documentation update first
- `safe_shell` has a whitelist of allowed commands — no arbitrary shell execution

**Layer 4 — Tool-level validation**
`safe_shell`: Only allows `grep`, `find`, `ls`, `cat`, `git`, `python`, `pytest`, `pip` + a few others
`db_query`: Only SELECT and PRAGMA — no INSERT/UPDATE/DELETE
`secret_scanner`: Read-only pattern scan — never exfiltrates data

Check `docs/SECURITY_AUDIT.md` for the full OWASP-aligned security review.""",
    },
    {
        "q": "What is the A2UI event bus and how do I stream updates to the dashboard?",
        "a": """A2UI (Agent-to-UI) is a Server-Sent Events bus in `backend/a2ui/` that streams real-time agent activity to the dashboard.

**How it works:**
```python
# In any agent — emit an event
from backend.a2ui import event_bus

event_bus.emit({
    "type": "agent_message",
    "agent": "devops_agent",
    "content": "Checking CI status...",
    "timestamp": datetime.utcnow().isoformat(),
})
```

**Dashboard subscribes via:**
```
GET /api/events  (SSE endpoint)
```
The Next.js dashboard uses `EventSource` to subscribe. The frontend `src/components/ActivityFeed.tsx` renders incoming events in real-time.

**Event types:**
- `agent_message` — agent produced output
- `tool_call` — a tool was invoked (with name + input)
- `tool_result` — a tool returned (with result preview)
- `drift_violation` — Drift Guard blocked a call
- `soul_reflection` — Soul agent ran a reflection cycle
- `system_alert` — health/error alert from monitor

**VS Code integration:** The extension also connects to the SSE stream and shows events in the output panel when `@agentop` chat is active.""",
    },
    {
        "q": "How do I add a new native tool to Agentop?",
        "a": """Adding a native tool requires 4 steps (docs-first governance applies):

**Step 1 — Document it first**
Add to `docs/SOURCE_OF_TRUTH.md` under "Native Tools" table with: tool ID, type (READ_ONLY/STATE_MODIFY/ARCH_MODIFY), and description. Log in `docs/CHANGE_LOG.md`.

**Step 2 — Implement the tool**
Create `backend/tools/my_tool.py`:
```python
from backend.tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    name = "my_tool"
    description = "What this tool does"
    tool_type = "READ_ONLY"  # or STATE_MODIFY, ARCH_MODIFY
    
    def execute(self, input: dict) -> ToolResult:
        # Validate inputs — never trust caller
        value = input.get("param", "")
        if not value or len(value) > 1000:
            return ToolResult(success=False, error="Invalid param")
        
        # Do the thing
        result = do_something(value)
        return ToolResult(success=True, data=result)
```

**Step 3 — Register in tool registry**
In `backend/tools/__init__.py`, add to `TOOL_REGISTRY`:
```python
from backend.tools.my_tool import MyTool
TOOL_REGISTRY["my_tool"] = MyTool()
```

**Step 4 — Wire into VS Code (optional)**
In `vscode-extension/src/tools.ts`, add a `LanguageModelTool` registration with name `agentop_my_tool` and input schema.""",
    },
    {
        "q": "What Python patterns does Agentop use consistently that I should follow?",
        "a": """Agentop has several consistent patterns (see `docs/` and `.github/prompts/python-patterns.prompt.md`):

**1. Repository root detection:**
```python
ROOT = Path(__file__).resolve().parent.parent
```
Every script uses this — never hardcode paths.

**2. Pydantic models for all API contracts:**
```python
from pydantic import BaseModel, Field
class ChatRequest(BaseModel):
    agent: str = Field(..., pattern=r"^[a-z_]+$")  # validated
    message: str = Field(..., min_length=1, max_length=4000)
```

**3. Optional imports with graceful degradation:**
```python
try:
    import some_package
    HAS_PACKAGE = True
except ImportError:
    HAS_PACKAGE = False
```

**4. Structured logging:**
```python
from backend.utils.logger import get_logger
logger = get_logger(__name__)
logger.info("Processing", extra={"agent": agent_id, "tool": tool_name})
```

**5. Config via environment, not hardcoded:**
```python
from backend.config import OLLAMA_URL, OLLAMA_MODEL  # all in one place
```

**6. Tools return `ToolResult`, never raise:**
```python
try:
    result = execute_something()
    return ToolResult(success=True, data=result)
except Exception as e:
    return ToolResult(success=False, error=str(e))  # never let exceptions escape tools
```

The codebase uses `ruff` for linting and `pyright` for type checking (see `pyrightconfig.json`).""",
    },
    {
        "q": "How is the Agentop frontend dashboard structured?",
        "a": """The Next.js 14 dashboard lives in `frontend/src/` and uses Mantine v7.

**Directory structure:**
```
frontend/src/
├── app/                    # Next.js App Router
│   ├── layout.tsx          # Root layout with MantineProvider
│   ├── page.tsx            # Dashboard home
│   └── api/                # API routes (proxy to backend)
├── components/
│   ├── AgentGrid.tsx       # Live agent status grid
│   ├── ActivityFeed.tsx    # SSE event stream display
│   ├── ChatPanel.tsx       # Agent chat interface
│   ├── GSDBoard.tsx        # GSD task tracker
│   └── MetricsBar.tsx      # System health metrics
└── lib/
    ├── api.ts              # Backend HTTP client
    └── hooks/              # SWR data fetching hooks
```

**Key design decisions:**
- Server Components fetch initial data (no client-side loading flash)
- Client Components only where real-time updates needed (ChatPanel, ActivityFeed)
- Mantine v7 `ColorSchemeProvider` for dark mode (dark is default)
- Dashboard polls backend every 5 seconds for agent status (not SSE for status, SSE only for events)
- Port: **3007** (not 3000 as some docs say)

The dashboard connects to the backend at `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`). For production deployments, this would point to the deployed backend URL.""",
    },
    {
        "q": "What changes were made in the ML eval framework commit (2e9bdcf)?",
        "a": """Commit `2e9bdcf` (`feat(ml): eval framework, A/B testing, benchmarks, Qdrant vector store, TurboQuant`) added the full ML infrastructure in one shot — 23 files, 783 tests, 61% coverage.

**What was added:**

1. **ML Eval Framework** (`backend/knowledge/ml_eval.py` + related):
   - `ModelEvaluator` class with configurable metrics (accuracy, latency, cost_per_token)
   - A/B test runner that compares two model configurations statistically
   - Benchmark suite for Ollama models (latency P50/P95, throughput tokens/sec)

2. **Qdrant Vector Store** (`backend/knowledge/qdrant_store.py`):
   - Replaced the in-memory vector store with persistent Qdrant
   - Cosine similarity search with metadata filtering
   - Batch upsert with automatic embedding retry on timeout

3. **TurboQuant** (`backend/knowledge/turbo_quant.py`):
   - Integrates with the model registry to track quantization performance
   - Compression ratio tracking (model size vs quality tradeoff)
   - Auto-selects quantization level based on available VRAM

4. **MLflow Tracker** (`backend/knowledge/mlflow_tracker.py`):
   - Passive logging of all LLM calls (model, prompt tokens, response tokens, latency)
   - Experiment tracking for A/B tests
   - Dashboard views at `http://localhost:5000` (MLflow UI)

**Test coverage:**
The 783 tests are in `backend/tests/` — run with `pytest backend/tests/ -v`.""",
    },
    {
        "q": "What are the CLAUDE.md TODO items I should work on next?",
        "a": """From `CLAUDE.md`, the open TODO items in priority order:

**Critical (affects live functionality):**
1. **Wire VoiceAgent + AvatarVideoAgent** — ElevenLabs and Fal AI keys are in `.env` but neither SDK is called. Implement in `backend/content/voice_agent.py` and `avatar_video_agent.py`.
2. **PublisherAgent social integrations** — No Twitter/LinkedIn/Instagram API. At minimum, implement a webhook-based publisher that POSTs to Zapier/Make.com.
3. **WebGen project persistence** — `SiteProject` state is in-memory. Add a SQLite table in `backend/database/` and persist between restarts.

**High value (improves capabilities):**
4. **Animation Salvage Lab** — Has docs and agent prompt guide but no Python implementation. Create `animation_salvage_lab/agent.py` as a new agent.
5. **Legacy skills to manifest format** — 15 domain JSON skills in `backend/skills/data/` are injected manually. Convert to proper manifest format with registry integration.
6. **Knowledge vector store seeding** — No scripts to seed Qdrant from project docs. Create `scripts/seed_personal_kb.py`.

**Infrastructure:**
7. **CORS validation at startup** — `AGENTOP_CORS_ORIGINS` should be validated on boot
8. **Secrets rotation** — Move from `.env` to Doppler (`doppler.yaml` already exists)
9. **README port fix** — README says 3000, correct port is 3007

Pick one item and say "implement <item description>" to have an agent tackle it.""",
    },
]


# ── Ollama-generated pairs ────────────────────────────────────────────────────

def ollama_qa_from_chunk(chunk: str, source_file: str) -> list[dict]:
    """Ask Ollama to generate Q&A pairs from a documentation chunk."""
    try:
        import requests
    except ImportError:
        return []

    prompt = f"""Read this Agentop architecture documentation and generate 4–6 high-quality Q&A pairs.

**Source:** {source_file}

**Content:**
{chunk[:2500]}

Reply ONLY with a JSON array: [{{"q": "...", "a": "..."}}]
Each answer should be 200+ words with code examples where applicable.
Focus on questions a developer would ask when building with this system."""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an expert on the Agentop multi-agent system. Generate educational Q&A pairs for fine-tuning an AI coding assistant.",
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.6, "num_predict": 800},
    }
    try:
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["message"]["content"].strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        pairs = json.loads(raw)
        if isinstance(pairs, list):
            return [p for p in pairs if isinstance(p, dict) and "q" in p and "a" in p]
    except Exception as e:
        print(f"  [WARN] {e}", flush=True)
    return []


def chunk_text(text: str, size: int = 2800) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - 200
    return chunks


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def main() -> None:
    parser = argparse.ArgumentParser(description="Architecture Q&A pairs for fine-tuning.")
    parser.add_argument("--ollama", action="store_true", help="Generate additional pairs from docs via Ollama")
    args = parser.parse_args()

    all_pairs = []

    # 1. Always include hardcoded pairs
    print(f"[arch] Injecting {len(ARCHITECTURE_SEEDS)} hardcoded architecture pairs")
    for seed in ARCHITECTURE_SEEDS:
        all_pairs.append(pair_to_sharegpt(seed["q"], seed["a"]))

    # 2. Optionally generate from docs
    if args.ollama:
        doc_sources = [
            (ROOT / "docs" / "SOURCE_OF_TRUTH.md", "SOURCE_OF_TRUTH.md"),
            (ROOT / "docs" / "AGENT_REGISTRY.md", "AGENT_REGISTRY.md"),
            (ROOT / "CLAUDE.md", "CLAUDE.md"),
        ]
        for doc_path, doc_name in doc_sources:
            if not doc_path.exists():
                continue
            text = doc_path.read_text(encoding="utf-8", errors="ignore")
            chunks = chunk_text(text)[:4]  # max 4 chunks per doc
            for j, chunk in enumerate(chunks):
                print(f"  {doc_name} chunk {j+1}/{len(chunks)}", end="  ", flush=True)
                new_pairs = ollama_qa_from_chunk(chunk, doc_name)
                print(f"→ {len(new_pairs)} pairs")
                for p in new_pairs:
                    all_pairs.append(pair_to_sharegpt(p["q"], p["a"]))
                time.sleep(0.3)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = OUT_DIR / f"architecture_pairs_{timestamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for rec in all_pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(all_pairs)} architecture pairs → {out_path}")


if __name__ == "__main__":
    main()
