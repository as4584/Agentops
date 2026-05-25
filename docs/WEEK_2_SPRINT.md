# Week 2 Sprint — Make the MVP Real Software

> Status: **APPROVED — sprint active**
> Author: product-lead agent
> Created: 2026-05-25
> Approved: 2026-05-25 by operator
> Branch: `dev`
> Predecessor: [docs/MVP_SCOPE.md](MVP_SCOPE.md) Week 1 close (commit `2e29cce`)

---

## 0. Why this sprint exists

Week 1 narrowed the *story*. Week 2 ships the *spine*. After this sprint, an
operator can install Agentop on a fresh machine, ingest their own runbooks,
ask a question from **either** the browser **or** Discord, and approve a
remediation action — with a clean audit trail.

The Discord bot stays. It is upgraded to a tier-1 surface alongside the web
dashboard.

---

## 1. Goal (one sentence)

> An operator can ingest their docs, ask the knowledge agent a grounded question
> from the browser **or** Discord, see a proposed `process_restart` action,
> approve it with one click/command, and watch the result land in a queryable
> audit log — all running locally on small Ollama models with no cloud.

If we can demo that flow end-to-end at the end of the sprint, Week 2 ships.
If we can't, we don't move to Week 3.

---

## 2. Scope amendment to MVP_SCOPE.md

Discord bot is moved from "out of scope" → **in MVP v1.0**, alongside the web
dashboard. Both are first-class operator surfaces. This requires:

- Update [MVP_SCOPE.md §3](MVP_SCOPE.md) Workflow to add "via browser **or
  Discord**".
- Update [MVP_SCOPE.md §5](MVP_SCOPE.md) Production Surface to include
  `backend/discord_bot.py`.
- Update [SOURCE_OF_TRUTH.md §0](SOURCE_OF_TRUTH.md) to add Discord as a
  supported surface.

This amendment is the first ticket and must land before any other work.

---

## 3. Pillars

| Pillar | What it proves | Tickets |
|---|---|---|
| **A. Spine** — ingestion + approval loop + audit | The product does the job | A1–A4 |
| **B. Discord Hardening** — reliability on small models | We meant it when we said Discord is tier-1 | B1–B5 |
| **C. Demo Surface** — install + dashboard slim + recorded demo | A buyer can see it | C1–C4 |

Total: 13 tickets. Each has a single acceptance criterion. No ticket is "done"
until the criterion passes in a green test run.

---

## 4. Pillar A — The Spine

### A0. Scope amendment commit
- **Files:** `docs/MVP_SCOPE.md`, `docs/SOURCE_OF_TRUTH.md`,
  `docs/CHANGE_LOG.md`
- **Change:** Add Discord as a first-class surface; document the approval loop
  in §3 Workflow.
- **Done when:** Three docs updated, committed, pushed to `dev`.

### A1. Ingestion CLI
- **New file:** `cli/ingest_cli.py` (or extend existing `cli/`)
- **Command:** `agentop ingest <path> [--collection knowledge_agent] [--reindex]`
- **Behavior:** Walks `path`, chunks text files (md, txt, rst, pdf via existing
  OCR), embeds via `nomic-embed-text`, upserts into the named Qdrant collection.
  Idempotent — re-running with same content is a no-op (hash-based dedup).
  Updates BM25 index in `data/bm25_index.pkl`.
- **Done when:** `agentop ingest docs/` runs cleanly, then a `POST /chat` to
  `knowledge_agent` asking "what is the MVP scope?" returns a grounded answer
  citing `docs/MVP_SCOPE.md`. Verified by a new test
  `backend/tests/test_ingest_cli_e2e.py`.

### A2. Proposed-action data model + endpoints
- **New file:** `backend/models/actions.py` — `ProposedAction`, `ActionStatus`
  enum (`PENDING`, `APPROVED`, `REJECTED`, `EXECUTED`, `FAILED`),
  `ActionAuditRow`.
- **New file:** `backend/routes/actions.py` with four endpoints:
  - `POST /actions/proposed` — agent creates a proposal
  - `GET  /actions/pending` — operator lists pending
  - `POST /actions/{id}/approve` — operator approves (idempotent)
  - `POST /actions/{id}/reject` — operator rejects with reason
- **Storage:** SQLite table `actions` in `data/agentop.db` (new file). Use
  existing `backend/database/` patterns.
- **Done when:** New test `backend/tests/test_actions_loop.py` covers full
  state machine: agent proposes → list pending → approve → executor runs
  `process_restart` (mocked) → status `EXECUTED` → audit row written.

### A3. Audit log
- **New file:** `backend/database/audit_store.py` — append-only `audit_log`
  table: `(id, ts, operator, agent_id, action_type, payload_json, result_json,
  ip, source)` where `source` ∈ `{"web", "discord", "cli"}`.
- **Hook points:** Every approval flows through `audit_store.write(...)`. Every
  `POST /chat` writes a row too.
- **Endpoint:** `GET /audit?limit=100&since=<ts>&operator=<id>` — paginated read.
- **Done when:** Test verifies an approved action's full timeline is queryable
  from a single audit query, and that `source="discord"` is correctly attributed
  when the proposal originated from Discord.

### A4. `knowledge_agent` returns proposals, not just text
- **File:** `backend/agents/knowledge_agent.py` (or wherever
  `knowledge_agent` lives — locate via `gitnexus_context`)
- **Change:** When the agent's plan includes a remediation step (e.g., "restart
  nginx"), it now returns `tool_calls=[ProposedAction(...)]` in the
  `ChatResponse` instead of describing the action in prose. The action stays
  `PENDING` until approved.
- **Done when:** Test verifies that asking "nginx is down, restart it" produces
  a `ChatResponse` with one pending `ProposedAction` whose `action_type ==
  "process_restart"`, and the action is queryable via `GET /actions/pending`.

---

## 5. Pillar B — Discord Hardening (small-model reliability)

> Premise: we run small local Ollama models (`qwen3:4b`, `lex-v2:latest`,
> `nomic-embed-text`). Small models hallucinate, drift, echo prompts, and
> mis-route. Discord makes these failures visible to humans in real time. Every
> ticket below makes one of those failures impossible or graceful.

### B1. Structured output enforcement
- **Files:** `backend/discord_bot.py` (the `_handle_chat` method), new
  `backend/llm/structured_response.py`
- **Change:** Replace the brittle `[DISCORD CONTEXT]` text prefix with a
  Pydantic response schema enforced via Ollama's
  [structured output mode](https://ollama.com/blog/structured-outputs).
  Response model: `{ "answer": str, "citations": list[str],
  "proposed_action": Optional[ProposedAction] }`. If the model returns
  malformed JSON, retry once with stricter system prompt, then fall back to a
  plain-text response with an `⚠️ unstructured` badge.
- **Done when:** Test
  `backend/tests/test_discord_structured_output.py` mocks a malformed-then-fixed
  Ollama response and verifies the bot replies cleanly. Manual smoke test: ask
  10 questions in a real Discord channel; every reply parses as JSON or carries
  the warning badge — no echoed prompts, no hallucinated agent names.

### B2. Retry + circuit breaker on backend calls
- **File:** `backend/discord_bot.py`
- **Change:** Wrap `httpx.post` to `/chat` and other backend calls in a 3-try
  exponential-backoff retry (50ms, 200ms, 800ms) for `ConnectError` and 5xx.
  Add a simple circuit breaker: if 5 consecutive failures within 30s, the bot
  posts ONE "🔧 Backend down — operator notified" message and silences
  per-message error replies for 60s. Resumes on first successful call.
- **Done when:** Test
  `backend/tests/test_discord_retry_breaker.py` simulates flapping backend
  and verifies retry count + breaker open/close transitions.

### B3. Conversation memory (persistent, per-channel)
- **File:** `backend/discord_bot.py`, new `backend/discord/conversation_store.py`
- **Change:** `_conversation_agents` becomes a SQLite-backed store keyed by
  `(channel_id, thread_id)`. Survives bot restart. Stores last N=5 turns per
  channel and prepends to subsequent `/chat` calls so small models have actual
  context.
- **Done when:** Test verifies that after restart, a follow-up message in the
  same channel correctly references the previous answer's topic.

### B4. Graceful Ollama cold-start handling
- **File:** `backend/discord_bot.py`, `backend/llm/__init__.py`
- **Change:** First request to a fresh Ollama model takes 10–30s to warm. The
  bot's current 120s timeout is fine, but the user sees no progress. Add: when
  `/chat` takes >5s, post a `⏳ warming up...` reply that gets edited with the
  final answer (or deleted if response is fast).
- **Done when:** Manual test: kill Ollama, restart it, ask the bot a question
  — operator sees the warming indicator, then the answer arrives without a
  timeout error.

### B5. Approval commands in Discord
- **File:** `backend/discord_bot.py`
- **New commands:**
  - `!pending` — list pending actions in current channel
  - `!approve <id>` — approve an action (calls `POST /actions/{id}/approve`)
  - `!reject <id> <reason>` — reject
- **Done when:** Test
  `backend/tests/test_discord_approval_commands.py` exercises full flow via
  mocked Discord client and verifies audit row is written with
  `source="discord"` and `operator=<discord-user-id>`.

---

## 6. Pillar C — Demo Surface

### C1. `docker compose up` brings everything up
- **Files:** `docker-compose.yml` (audit), `Dockerfile` (audit), new
  `docker-compose.mvp.yml` if cleaner.
- **Change:** Single `docker compose -f docker-compose.mvp.yml up` brings up
  backend (FastAPI), Qdrant, Ollama (with `nomic-embed-text` and `qwen3:4b`
  pre-pulled via init container), frontend, and optionally the Discord bot
  (via env var). Healthchecks on each service.
- **Done when:** On a fresh machine with only Docker installed, the command
  brings the stack up, `curl localhost:8000/health` returns 200, and the
  frontend loads at `localhost:3007`. Documented in
  [README.md](../README.md) "Install in 5 minutes".

### C2. Dashboard narrowed to 6 MVP tabs
- **Files:** `frontend/src/app/**` — locate via subagent
- **Change:** Implement the 6-tab layout from [MVP_SCOPE.md 7](MVP_SCOPE.md):
  Ask / Investigate / Actions / Logs / Health / Settings. Wire Ask + Actions +
  Logs tabs to real backend endpoints from Pillar A. Hide v1.1 surface behind
  `?legacy=1` query flag. Do NOT delete the v1.1 pages — gate them.
- **Done when:** Loading `localhost:3007` shows only the 6 tabs. The Ask tab
  successfully chats with `knowledge_agent`. The Actions tab shows pending
  proposals and Approve/Reject buttons work end-to-end. Adding `?legacy=1`
  shows the old surface.

### C3. Operator login + per-operator attribution
- **Files:** `backend/auth.py`, `backend/routes/auth.py` (new),
  `frontend/src/app/login/page.tsx` (new)
- **Change:** Replace single `AGENTOP_API_SECRET` bearer with operator
  accounts: `operators` SQLite table (username, bcrypt password, role).
  Cookie-based session. All actions + audit rows carry the operator ID. Bearer
  token still accepted for CLI/Discord-bot system calls (separate `system_token`
  scope).
- **Done when:** New tests cover login, session expiry, and that an
  unauthenticated request to `/chat` returns 401 while a logged-in session
  works. Audit log shows the operator's username, not just a token.

### C4. The 90-second demo
- **Files:** `docs/DEMO_SCRIPT.md` (new), `output/demos/week2.mp4` (new)
- **Change:** Recorded screencast:
  - 0:00–0:15 — Fresh machine. `docker compose up`. Backend + Discord bot live.
  - 0:15–0:35 — `agentop ingest ~/runbooks/`. Index built.
  - 0:35–1:05 — Ask in Discord: "nginx returning 502, what do you see?" → bot
    runs `log_tail` + `health_check` → proposes `process_restart nginx`.
  - 1:05–1:25 — `!approve <id>` → action runs → "✅ nginx restored, 200 OK".
  - 1:25–1:30 — Open browser → Logs tab → audit row visible.
- **Done when:** Video exists in `output/demos/week2.mp4` and the script is
  followed exactly without any edits or re-takes.

---

## 7. Out of scope for Week 2 (explicit)

- No content/webgen/video/social-media work.
- No new agents beyond the four MVP agents.
- No new tools beyond the existing MVP set + `process_restart` (already in).
- No Telegram or Slack bridge (Discord only this sprint).
- No multi-tenant support; single-operator-per-deploy still holds.
- No production secrets management beyond `.env` + Doppler (existing setup).
- No SaaS, no cloud, no managed service.

---

## 8. Risk register

| Risk | Likelihood | Mitigation |
|---|---|---|
| Small-model JSON output unreliable even with structured mode | MEDIUM | B1 has explicit fallback path; treat as a real engineering problem, not a "hope it works" |
| Ollama cold-start on demo machine breaks C4 video | MEDIUM | C1 init container pre-pulls models; pre-warm before recording |
| Discord rate limits during demo | LOW | bot already has per-user rate limit; add per-channel global cap in B2 |
| Existing 1,471-line `discord_bot.py` resists refactor | MEDIUM | All Pillar B changes are additive — add new modules, modify only the call sites. No mass rewrite. |
| Approval loop is more complex than estimated | HIGH | Cut C3 (operator login) to Week 3 if A2+A3+A4 slips. C3 is the only ticket that can be deferred without breaking the demo. |

---

## 9. Acceptance for Week 2 close

All of the following must be true:

1. **Test suite:** `pytest backend/tests/ --no-cov` reports 0 unexpected failures.
2. **Ingestion:** `agentop ingest docs/` then `POST /chat` to `knowledge_agent`
   returns a grounded answer with at least one citation from `docs/`.
3. **Approval loop:** A proposed action can be approved from the dashboard
   AND from Discord, both end up in the audit log with correct `source`.
4. **Discord reliability:** 10 consecutive messages to the bot all parse as
   structured output or carry the explicit unstructured badge. No echoed
   prompts. No hallucinated agent names.
5. **Install:** `docker compose -f docker-compose.mvp.yml up` on a fresh VM
   gets to a working backend within 90 seconds.
6. **Demo video:** `output/demos/week2.mp4` exists and matches the C4 script.
7. **Branch:** All changes merged to `dev`, pushed to `origin/dev`, CI green.
   `main` untouched.

---

## 10. Order of operations (no time estimates)

1. **A0** — Scope amendment lands first. Sets the contract.
2. **A1** — Ingestion CLI. Unlocks every "does it actually work?" test.
3. **A2 + A3** — Proposed-action model + endpoints + audit (paired, same PR).
4. **A4** — Knowledge agent emits proposals.
5. **B1** — Discord structured output (most reliability bang per ticket).
6. **B2 + B4** — Discord retry/breaker + cold-start UX.
7. **B5** — Discord approval commands (depends on A2).
8. **B3** — Discord conversation memory (nice-to-have if time tight).
9. **C2** — Dashboard slim + wire Ask/Actions/Logs.
10. **C1** — Docker compose (do last; ensures everything containerizes).
11. **C3** — Operator login (cuttable to Week 3 if needed).
12. **C4** — Record demo.

---

## 11. Approval

- [x] Operator approves this sprint plan as-is — 2026-05-25
- [ ] Operator approves with edits (note edits below)

Once approved, this document becomes immutable for the sprint. Any scope
change goes through a `docs/CHANGE_LOG.md` entry citing this file.
