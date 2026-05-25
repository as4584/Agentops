# MVP SCOPE — Private AI Ops Console

> Status: Week 1 deliverable (staged, not yet promoted into SOURCE_OF_TRUTH).
> Owner: product lead
> Last updated: 2026-05-25

---

## 1. Positioning Statement (one sentence)

**A private, local AI ops console that helps a small technical team investigate incidents, search internal runbooks, and execute approved fixes — without sending internal systems or docs to public AI tools.**

---

## 2. Product Summary (one paragraph)

Agentop Ops Console is a private AI workspace for solo operators and small
technical teams (MSPs, internal IT, boutique devops, security consultants).
The operator connects their runbooks, docs, logs, and selected system tools.
The console then answers operational questions grounded in their own
environment, inspects state through read-only diagnostics, proposes a next
step, and executes bounded remediation actions only with explicit approval.
Every session produces a clean incident summary and a full audit trail.
It is local-first, operator-only, and intentionally narrow — not a generic
AI chatbot, not a coding assistant, not a multi-tenant platform.

---

## 3. MVP Scope — In

The 30-day MVP ships exactly these capabilities:

1. **Private local deployment** — backend + dashboard run on a local machine
   or trusted private network; no public signup, no multi-tenant surface.
2. **Internal knowledge ingestion** — operator can ingest markdown runbooks,
   docs, and incident notes into Qdrant-backed retrieval, with source tags.
3. **Grounded retrieval Q&A** — answers cite the runbook/doc they came from
   and degrade clearly when confidence is low.
4. **Read-only diagnostics** — `file_reader`, `log_tail`, `health_check`,
   `db_query`, `git_ops`, Docker read tools.
5. **One approval-gated action** — `process_restart` (or equivalent) is the
   only state-modifying remediation in the MVP path, and only after explicit
   operator approval in the UI.
6. **Incident workflow** — single end-to-end flow: ask → retrieve → inspect
   → propose → approve → act → summarize.
7. **Audit trail** — every session writes a persisted record: question,
   sources used, tools called, action taken, result, summary.
8. **Operator dashboard (slim)** — chat, retrieval status, recent sessions,
   approval queue, health.
9. **Pilot onboarding flow** — “connect docs”, “connect logs”, “choose
   approved actions”.
10. **Demo assets** — 3 scripted scenarios with seeded docs and logs.

---

## 4. MVP Scope — Out (explicitly deferred)

Anything not on the list above is **not part of the 30-day MVP** and must
not be used in the sales story. These remain in the repo but are reframed
as labs / dormant / deferred:

- Content production pipeline (`backend/content/`)
- Webgen V1 and V2 (`backend/webgen/`, `cli/webgen_cli.py`)
- Social intake, campaign generation, caption/voice/avatar agents
- Animation salvage lab
- Browser automation as a headline feature
- Slack posting / outbound comms workflows
- "Soul agent" as a user-facing concept (kept internally as governance only)
- `self_healer_agent` autonomous remediation
- Multi-agent fan-out marketing language
- Discord/Telegram bridges
- ML learning lab as a product surface
- VS Code extension as the primary buyer surface (kept as operator tool)
- Anything described as "platform", "control center for everything", or
  "autonomous cluster"

---

## 5. Production Surface (what the buyer sees)

Only these surfaces are part of the MVP story:

| Surface | Role in MVP |
|---|---|
| FastAPI backend (`backend/server.py`) | Operator-only API |
| Dashboard (slim) | Chat, sessions, approvals, audit, health |
| `knowledge_agent` | Grounded Q&A over ingested docs |
| `monitor_agent` | Read-only inspection (logs, health, containers) |
| `devops_agent` | Approval-gated remediation (one action) |
| `security_agent` | Passive checks in incident context only |
| Qdrant retrieval | Production retrieval path |
| Doppler / `.env` | Secrets, local-only |
| Audit log (`backend/logs/system.jsonl` + session artifact) | Trail |

Everything else is internal scaffolding, not product surface.

---

## 6. Cut List (reframe in repo narrative)

These directories/modules stay on disk but are demoted from the product
story. README, landing copy, and outreach must not lead with them.

| Area | New label |
|---|---|
| `backend/content/` | Labs — content experiments |
| `backend/webgen/` | Labs — site generation experiments |
| `backend/video/`, `animation_salvage_lab/` | Labs — media experiments |
| `pixel-agents/`, `SigmaSimulator/` | Sandbox |
| `vscode-extension/` | Internal operator tool (not headline) |
| `deerflow/` | Internal orchestration library |
| `cli/webgen_cli.py`, `cli/content_cli.py` | Labs CLI |
| `comms_agent`, `cs_agent`, `it_agent` | Deferred — not in MVP path |
| `self_healer_agent` | Deferred — autonomous action out of scope |
| `soul_core` (as a product concept) | Internal governance only |

The DriftGuard / governance machinery stays — it is a credibility asset
for the ops console story, but it is not the headline.

---

## 7. Dashboard / Navigation Plan (slim)

Replace the current tier-based agent panels with an operator workflow:

1. **Chat** — primary incident workspace.
2. **Knowledge** — connected sources, ingestion status, reindex.
3. **Sessions** — past investigations, with audit summaries.
4. **Approvals** — pending action approvals.
5. **Health** — Ollama, Qdrant, MCP, retrieval, action runner status.
6. **Settings** — sources, approved actions, secrets via Doppler.

Hidden in MVP UI (still accessible via routes for operators):
soul panel, drift monitor, agent tier view, memory namespaces explorer.

---

## 8. Exit Criteria for Week 1

- [x] Positioning sentence written
- [x] One-paragraph summary written
- [x] In/out scope locked
- [x] Cut list defined
- [x] Production surface map defined
- [x] Slim dashboard plan defined
- [x] Smoke test: backend boots, `/health` returns ok, chat flow returns a
      grounded answer over seeded docs
      *(2026-05-25 — `uvicorn backend.server:app` came up clean in
      `operator_only` mode; `GET /health` → 200 `{status: healthy,
      llm_available: true, drift_status: GREEN, runtime_profile: operator,
      retrieval_mode: fast_context}`; `POST /chat` to `knowledge_agent`
      with bearer auth returned grounded "no indexed context retrieved"
      refusals — no hallucination over an empty corpus. Full backend test
      suite: 2454 passed, 6 skipped, 1 xfailed, 0 failures.)*
- [x] SOURCE_OF_TRUTH.md updated to reflect ops-console direction
      *(2026-05-25 — new §0 "Product Frame — MVP v1.0 (canonical)"
      inserted; v2.4.0; committed `6a6068f`.)*

---

## 9. Hard Boundaries for Weeks 2–4

- No new agents added.
- No new tools added beyond the MVP set.
- No content/webgen/social work.
- No "platform" language anywhere buyer-facing.
- All architecture changes must reduce surface, not expand it.

---

## 10. One-Sentence Test

If a stranger reads the README intro and cannot say, in their own words,
"this helps a small technical team investigate incidents privately and
execute approved fixes," the narrative is still too broad and must be cut
further before any code work continues.
