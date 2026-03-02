# Hybrid Architecture — Agents, MCP Tools, and Cloud LLM Routing

> How Agentop's 17 agents, 38 tools, and hybrid LLM router work together.

**Last updated:** 2025-07-14  
**Version:** 1.0.0

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        AGENTOP CLUSTER                           │
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐    │
│  │ Soul Core│   │  DevOps  │   │ Monitor  │   │   Data   │    │
│  │ (governs)│   │ (deploy) │   │ (observe)│   │ (query)  │    │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘    │
│       │              │              │              │            │
│  ┌────┴──────────────┴──────────────┴──────────────┴────┐      │
│  │                   LLM ROUTER                          │      │
│  │         mode: local_only | hybrid | cloud_only        │      │
│  └───────┬─────────────────────────────┬─────────────────┘      │
│          │                             │                         │
│    ┌─────▼─────┐                ┌──────▼──────┐                 │
│    │  Ollama   │                │ OpenRouter  │                 │
│    │ (local)   │                │  (cloud)    │                 │
│    │ llama3.2  │                │ Kimi K2     │                 │
│    │ FREE      │                │ GPT-4o      │                 │
│    └───────────┘                │ Claude      │                 │
│                                 │ DeepSeek    │                 │
│                                 │ Gemini      │                 │
│  ┌──────────────────────────────┴─────────────┘                 │
│  │                                                               │
│  │  ┌───────────────────────────────────────────┐               │
│  │  │              TOOL LAYER                    │               │
│  │  │  12 Native Tools + 26 MCP Gateway Tools   │               │
│  │  └──────────────┬────────────────────────────┘               │
│  │                 │                                             │
│  │           ┌─────▼─────┐                                      │
│  │           │ MCP Bridge│──► Docker MCP Gateway                │
│  │           │ (docker)  │    ├─ GitHub                         │
│  │           └───────────┘    ├─ Filesystem                     │
│  │                            ├─ Docker                         │
│  │                            ├─ Time                           │
│  │                            ├─ Fetch                          │
│  │                            ├─ SQLite                         │
│  │                            └─ Slack                          │
│  └───────────────────────────────────────────────────────────── │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Agent → Model → Tool Matrix

### 2.1 Agent Model Routing

Each agent's LLM calls are routed through the `LLMRouter` based on task type:

| Agent | Primary Tasks | Hybrid Route | Reasoning |
|-------|--------------|--------------|-----------|
| **soul_core** | Reflection, goal reasoning | Cloud (kimi-k2) | Governing intelligence needs best reasoning |
| **devops_agent** | Deployment analysis, git review | Cloud (kimi-k2) | Infrastructure decisions need accuracy |
| **monitor_agent** | Log analysis, alert decisions | Local | Pattern matching, fast iteration |
| **self_healer_agent** | Remediation planning | Hybrid | Simple fixes local, complex cloud |
| **code_review_agent** | Diff analysis, invariant checking | Cloud (kimi-k2) | Architecture review needs deep understanding |
| **security_agent** | Secret scanning, CVE analysis | Local | Pattern matching, known patterns |
| **data_agent** | Schema analysis, query review | Local | Structured analysis, template-based |
| **comms_agent** | Message drafting, notifications | Local | Copy/formatting tasks |
| **it_agent** | Diagnostics, system analysis | Hybrid | Simple queries local, complex cloud |
| **prompt_engineer** | Prompt optimization, model routing | Cloud (kimi-k2) | Meta-reasoning requires best model |
| **token_optimizer** | Compression analysis, budgeting | Cloud (kimi-k2) | Requires understanding of model capabilities |
| **curriculum_advisor** | Course advice, outcome mapping | Local | Knowledge retrieval, structured responses |
| **vocabulary_coach** | Term identification, upgrades | Local | Dictionary lookup pattern |
| **career_intel** | Job analysis, skill mapping | Local | Structured matching |
| **accreditation_advisor** | Criteria mapping, gap analysis | Local | Template-based reporting |
| **pedagogy_agent** | Learning design, assessment | Local | Pattern application |
| **cs_agent** | User support, KB access | Local | FAQ-style responses |

### 2.2 Agent Tool Permissions

| Agent | Native Tools | MCP Tools | Total |
|-------|-------------|-----------|-------|
| **soul_core** | file_reader, system_info, doc_updater, alert_dispatch | github(2), filesystem(2), time(1) | 9 |
| **devops_agent** | git_ops, safe_shell, file_reader, health_check, doc_updater, folder_analyzer | github(4), docker(3), time(1) | 14 |
| **monitor_agent** | health_check, log_tail, system_info, alert_dispatch, file_reader | fetch(1), docker(3), time(1) | 10 |
| **self_healer_agent** | process_restart, health_check, log_tail, alert_dispatch, system_info | docker(4) | 9 |
| **code_review_agent** | git_ops, file_reader, doc_updater, alert_dispatch, folder_analyzer | github(3), filesystem(2) | 10 |
| **security_agent** | secret_scanner, file_reader, health_check, alert_dispatch, system_info, folder_analyzer | github(2), filesystem(2) | 10 |
| **data_agent** | db_query, file_reader, system_info, doc_updater, alert_dispatch, folder_analyzer | sqlite(3), filesystem(1) | 10 |
| **comms_agent** | webhook_send, file_reader, alert_dispatch, doc_updater | slack(3), fetch(1), time(1) | 9 |
| **it_agent** | safe_shell, file_reader, system_info, doc_updater, folder_analyzer | filesystem(2), docker(2), time(1) | 10 |
| **prompt_engineer** | file_reader, system_info | filesystem(1), time(1) | 4 |
| **token_optimizer** | file_reader, system_info | filesystem(1), time(1) | 4 |

---

## 3. Hybrid LLM Flow

### 3.1 Request Lifecycle

```
Agent.process_message(user_input)
  │
  ├─► Build prompt  (system_prompt + tools_context + skills + user_input)
  │
  ├─► LLMRouter.generate(prompt, system, task=agent_task_type)
  │     │
  │     ├─► _route(task)  →  (destination, model_name)
  │     │     │
  │     │     ├─ mode=local_only?     → ("local", "llama3.2")
  │     │     ├─ mode=cloud_only?     → ("cloud", "kimi-k2")
  │     │     ├─ budget exhausted?    → ("local", "llama3.2")  [safety valve]
  │     │     └─ TASK_ROUTES[task]    → route.model
  │     │
  │     ├─► if local:  LocalLLM.generate()  → Ollama HTTP
  │     └─► if cloud:  CloudLLMClient.generate()  → OpenRouter HTTPS
  │
  ├─► Parse response for tool calls  [TOOL:tool_name(param=value)]
  │
  ├─► execute_tool(tool_name, agent_id, permissions, **kwargs)
  │     │
  │     ├─ Permission check (tool_name in agent.tool_permissions?)
  │     ├─ DriftGuard middleware check
  │     ├─ if mcp_* tool:  MCPBridge.call_tool()  → docker mcp CLI
  │     └─ if native tool:  direct function call
  │
  ├─► Format tool result → inject back into conversation
  │
  └─► Return final response
```

### 3.2 Token Efficiency Patterns

#### Pattern 1: Design System Caching
```
First call (cloud):
  System: "You are a premium web design architect..."
  User: "Create a design system for {client_brief}"
  → Kimi K2 generates design_system.json (~3000 tokens)

Subsequent calls (local):
  System: "Apply this design system: {design_system_json}"
  User: "Write the hero section copy for the about page"
  → llama3.2 generates copy with design system as context
```

#### Pattern 2: Schema-Constrained Output
```python
# Forces structured output, reducing wasted tokens
result = await router.chat_json(
    prompt="Generate SEO metadata for home page",
    schema={
        "title": "string (max 60 chars)",
        "description": "string (max 155 chars)",
        "keywords": ["string"],
        "og_image_alt": "string",
    },
    task="seo_metadata",  # routes to local (free)
)
```

#### Pattern 3: Batch Operations
```python
# Generate all page copies in one cloud call instead of 6
result = await router.chat_json(
    prompt="Generate copy for all 6 pages of this site",
    system=f"Design system: {design_system}\nBrief: {brief}",
    schema={
        "pages": {
            "home": {"hero_headline": "", "hero_subtext": "", "cta": ""},
            "about": {"hero_headline": "", "story": ""},
            # ...
        }
    },
    task="design_system",  # routes to cloud (quality matters)
)
```

---

## 4. MCP Gateway Architecture

### 4.1 Tool Routing

```
Agent calls [TOOL:mcp_github_list_issues(owner=as4584,repo=damianwebsite)]
  │
  ├─► backend/tools execute_tool()
  │     ├─ Recognizes mcp_* prefix
  │     └─ Delegates to MCPBridge.call_tool()
  │
  ├─► MCPBridge.call_tool("mcp_github_list_issues", {...})
  │     ├─ Looks up MCP_TOOL_MAP: ("github", "list_issues")
  │     └─ Executes: docker mcp tools call github_list_issues '{"owner":"as4584","repo":"damianwebsite"}'
  │
  ├─► Docker MCP Gateway
  │     ├─ Routes to GitHub MCP Server container
  │     ├─ MCP server authenticates with GitHub token
  │     └─ Returns result JSON
  │
  └─► Result flows back to agent for interpretation
```

### 4.2 MCP Server Registry

| Server | Tools | Auth | Container |
|--------|-------|------|-----------|
| **GitHub** | search_repositories, get_file_contents, list_issues, create_issue, search_code, list_pull_requests, get_pull_request | GITHUB_TOKEN | modelcontextprotocol/github |
| **Filesystem** | read_file, write_file, list_directory, search_files, get_file_info | None (host mount) | modelcontextprotocol/filesystem |
| **Docker** | list_containers, get_container_logs, inspect_container, restart_container, list_images | Docker socket | modelcontextprotocol/docker |
| **Time** | get_current_time, convert_time | None | modelcontextprotocol/time |
| **Fetch** | fetch (HTTP GET) | None | modelcontextprotocol/fetch |
| **SQLite** | read_query, list_tables, describe_table | None (file path) | modelcontextprotocol/sqlite |
| **Slack** | post_message, list_channels, get_channel_history | SLACK_TOKEN | modelcontextprotocol/slack |

---

## 5. Integration Points

### 5.1 Backend LLM Layer (`backend/llm/__init__.py`)

The `HybridClient` wraps both `OllamaClient` and `CloudLLMClient`, presenting the same interface agents already use:

```python
# Agents don't need to change — HybridClient is a drop-in replacement
from backend.llm import HybridClient

client = HybridClient(mode="hybrid")

# Same generate() interface as OllamaClient
response = await client.generate(
    prompt="Design a navigation component",
    system="You are a web architect",
    task="design_system",  # NEW: task hint for routing
)
```

### 5.2 WebGen Pipeline Integration

```python
class WebGenPipeline:
    def __init__(self, llm=None):
        # Before: self.llm = llm or OllamaClient()
        # After:
        self.llm = llm or HybridClient(mode="hybrid")

    async def plan(self, project):
        # Architecture planning → routes to Kimi K2 (cloud)
        structure = await self.llm.generate(
            prompt=f"Plan site structure for: {project.brief}",
            task="site_architecture",
        )

    async def generate_copy(self, page):
        # Copy writing → routes to llama3.2 (local, free)
        copy = await self.llm.generate(
            prompt=f"Write copy for {page.name}",
            task="copy_writing",
        )
```

### 5.3 Agent Factory Integration

```python
# backend/agents/__init__.py
def create_agent(agent_id: str, llm_client=None) -> BaseAgent:
    if llm_client is None:
        from backend.llm import HybridClient
        llm_client = HybridClient(mode="hybrid")

    definition = ALL_AGENT_DEFINITIONS[agent_id]
    if agent_id == "soul_core":
        return SoulAgent(definition=definition, llm_client=llm_client)
    return BaseAgent(definition=definition, llm_client=llm_client)
```

---

## 6. Configuration

### Environment Variables

```bash
# .env (chmod 600, never committed)

# OpenRouter (cloud LLM gateway)
OPENROUTER_API_KEY=sk-or-v1-...

# Ollama (local LLM)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_TIMEOUT=120

# Router mode: local_only | hybrid | cloud_only
LLM_ROUTER_MODE=hybrid
LLM_MONTHLY_BUDGET=50.0
```

### Runtime Configuration (`backend/config.py`)

```python
# Cloud LLM Configuration
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
LLM_ROUTER_MODE: str = os.getenv("LLM_ROUTER_MODE", "hybrid")
LLM_MONTHLY_BUDGET: float = float(os.getenv("LLM_MONTHLY_BUDGET", "50.0"))
```

---

## 7. Governance Rules

| Invariant | Rule | Enforcement |
|-----------|------|-------------|
| **INV-13** | All cloud LLM calls MUST route through `LLMRouter` | Code review agent checks for direct httpx calls to OpenRouter |
| **INV-14** | API keys MUST live in `.env` with 600 perms | Security agent scans for hardcoded keys |
| **INV-15** | Monthly cost MUST NOT exceed budget without soul_core approval | Router auto-falls back to local at budget limit |
| **INV-16** | Embeddings MUST use local models only | CloudLLMClient.embed() raises NotImplementedError |

---

## 8. Monitoring & Alerts

The Monitor Agent tracks LLM costs via the Router's stats:

| Threshold | Action |
|-----------|--------|
| $10 spent | Log info event |
| $50 spent | Alert to soul_core |
| $100 spent | Auto-switch to local_only mode |
| Budget exceeded | Hard block on cloud calls |

Stats are accessible via:
```python
router = LLMRouter(mode="hybrid")
stats = router.get_stats()
# → { total_requests, local_requests, cloud_requests, estimated_cost_usd, ... }

log = router.get_cost_log(n=10)
# → [ { timestamp, destination, model, task, cost_usd, ... }, ... ]
```

---

*This document is maintained by the Agentop governance framework. See [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md) for the canonical architecture reference and [COSTS_OF_ARCHITECTURE.md](COSTS_OF_ARCHITECTURE.md) for detailed pricing.*
