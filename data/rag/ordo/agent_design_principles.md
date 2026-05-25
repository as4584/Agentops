# Agent Design Principles — Agentop Implementation

> Canonical reference for agent architecture, boundaries, and orchestration patterns.
> All agents must conform to these principles.

## Principle 1: Orchestrator-Mediated Communication

Agents NEVER call each other directly. All inter-agent communication routes through
the LangGraph orchestrator. This ensures:
- Audit trail for every message
- Rate limiting and ACL enforcement
- Fan-out coordination for multi-agent tasks
- Dead-letter handling for failed deliveries

**Violation detection:** Drift Guard middleware intercepts direct agent-to-agent calls
and raises an invariant violation.

## Principle 2: Isolated Memory Namespaces

Each agent has a dedicated memory namespace under `data/agents/{agent_id}/`.
Agents cannot read or write other agents' memory.

**Exception:** `soul_core` has read access to all agent namespaces for trust scoring
and reflection. This is the only cross-namespace access permitted.

## Principle 3: Tiered Routing

The routing system uses three tiers for resilience:

1. **C Fast Router** (< 1ms) — compiled pattern matching, handles obvious cases
2. **lex-v2 LLM Router** (3B model) — handles ambiguous and boundary cases
3. **Python Keyword Fallback** — last resort when LLM is unavailable

Tier escalation happens automatically. If Tier 1 returns `unknown`, Tier 2 runs.
If Tier 2 fails (model down, timeout), Tier 3 catches.

## Principle 4: Tool Safety Classification

Every tool has a safety classification:

| Classification | Description | Approval Required |
|---------------|-------------|-------------------|
| READ_ONLY | No side effects | None |
| STATE_MODIFY | Changes system state | Agent must log action |
| ARCH_MODIFY | Changes architecture/governance docs | Soul Core approval |

Tools are registered in `backend/tools/` with their classification.
Drift Guard enforces that ARCH_MODIFY tools trigger documentation-before-mutation.

## Principle 5: Graceful Degradation

Every external dependency must degrade gracefully:
- **Ollama down:** Return "LLM unavailable" instead of crashing
- **Qdrant down:** Fall back to BM25-only retrieval
- **MCP Docker absent:** Skip MCP tools, log warning
- **GLM-OCR sidecar down:** Return "OCR unavailable" for document extraction

Agents must check dependency health before calling external services.

## Principle 6: Documentation-Before-Mutation

Any change that affects:
- Agent definitions (adding, removing, modifying agents)
- Tool registrations (new tools, changed classifications)
- Governance rules (invariants, thresholds, policies)
- Architecture (new services, changed routing)

MUST update the corresponding documentation FIRST. Code changes come AFTER
documentation is committed. This is enforced by Drift Guard INV-04.

## Agent Boundary Reference

### Tier 0 — Core
| Agent | Boundary | NOT responsible for |
|-------|----------|-------------------|
| `soul_core` | Reflection, trust, purpose, goal arbitration | NOT for factual Q&A, NOT for code review |

### Tier 1 — Operations
| Agent | Boundary | NOT responsible for |
|-------|----------|-------------------|
| `devops_agent` | CI/CD, git, deployment, builds | NOT for monitoring, NOT for security scanning |
| `monitor_agent` | Health checks, logs, metrics, alerts | NOT for infrastructure changes, NOT for remediation |
| `self_healer_agent` | Process crashes, restarts, fault remediation | NOT for monitoring, NOT for deployment |

### Tier 2 — Quality
| Agent | Boundary | NOT responsible for |
|-------|----------|-------------------|
| `code_review_agent` | Code diffs, PR review, pattern enforcement | NOT for vulnerability scanning |
| `security_agent` | Secret scanning, CVE flagging, vulnerability | NOT for code quality |
| `data_agent` | ETL, schema, SQLite queries, data validation | NOT for application logic |

### Tier 3 — Support
| Agent | Boundary | NOT responsible for |
|-------|----------|-------------------|
| `comms_agent` | Webhooks, incident notifications, alerts | NOT for customer-facing support |
| `cs_agent` | Customer support, FAQ, knowledge base | NOT for internal operations |
| `it_agent` | Infrastructure diagnostics, network, DNS | NOT for monitoring metrics |
| `knowledge_agent` | Document search, semantic Q&A | NOT for philosophical reflection (→ soul_core) |
| `ocr_agent` | PDF/image text extraction | NOT for document analysis |

## Skill System

Skills extend agent capabilities without modifying core code:
- **Manifest skills** (`backend/skills/{id}/skill.json`): structured packages with metadata
- **Legacy skills** (`backend/skills/data/*.json`): domain knowledge packs injected into prompts
- Skills are bound to allowed agents via `allowed_agents` field
- Skills can be toggled at runtime via PATCH `/skills/{id}`

## WebGen Pipeline

The website generation pipeline demonstrates multi-agent orchestration:
1. `SitePlanner` — creates site structure from client brief
2. `PageGenerator` — generates HTML/CSS for each page
3. `SEOAgent` — optimizes meta tags, sitemap, robots.txt
4. `AEOAgent` — adds structured data, FAQ schema
5. `QAAgent` — validates output quality

Each agent uses the shared `OllamaClient` for LLM inference.
Projects persist to `backend/memory/webgen_projects/{id}.json`.

## Content Pipeline

The content creation pipeline orchestrates:
1. `IdeaIntakeAgent` → `ScriptWriterAgent` → `VoiceAgent` → `AvatarVideoAgent`
2. → `QAAgent` → `PublisherAgent` → `AnalyticsAgent`

**Current status:** ScriptWriter is functional; Voice and Avatar agents are stubs.
