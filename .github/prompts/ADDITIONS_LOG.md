# Prompt Additions Log

Documentation of improvements made to Agentop's AI skill system beyond the initial `ui-ux-pro-max-skill` and `everything-claude-code` conversions.

---

## Batch 1 — Competitive System Prompt Analysis

**Date:** 2026-03-xx  
**Source material:** [github.com/x1xhlol/system-prompts-and-models-of-ai-tools](https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools)  
**Prompts analysed:** v0 (Vercel), Same.dev, Orchids.app, Replit, Cursor (full production system prompts)

### Methodology

Each competitor system prompt was read in full and mapped against Agentop's existing skill files. The question asked for every pattern found was:

> "Does Agentop already enforce this? If yes — skip. If no — does adding it produce a measurable improvement to output quality?"

Only patterns that passed both gates were incorporated.

---

### Additions to `website-builder.prompt.md`

#### 1. Hard Design Constraints block

**Source:** v0, Same.dev, and Orchids independently enforce identical rules — this convergence signals proven production necessity.

**What was added:**
- **Colour cap:** Max 5 colours total (1 primary, 2–3 neutrals, 1–2 accents). No purple/violet as prominent colour without explicit request.
- **Gradient rule:** Solid colours by default. If gradients: max 3 stops, analogous only.
- **Typography cap:** Max 2 font families (1 heading, 1 body).
- **No placeholder images:** All image slots must contain real or generated assets.
- **No emojis as icons:** Use Lucide, Heroicons, Phosphor, or SVGs.
- **Tailwind discipline:** No arbitrary values (`p-[16px]`). No `space-*` — use `gap-*`.
- **Aesthetic standard:** "Interesting but never ugly." Generic/bland output is a failure outcome, not a safe default.

**Why it matters:** Without explicit constraints, LLMs default to a predictable "AI aesthetic" — purple gradients, emoji bullets, arbitrary spacing values, 4 fonts. Each of these constraints was derived from real production enforcement by teams shipping sites at scale.

---

#### 2. Pre-Build Design Brief (Mandatory)

**Source:** v0's `GenerateDesignInspiration` gating pattern; Same.dev's plan-before-build requirement.

**What was added:**  
A mandatory design brief template that `SitePlannerAgent` must emit — and which gates `PageGeneratorAgent`. The brief captures: colour palette with hex values, typography with Google Fonts import, page structure with section order and purpose, mood/direction summary, and industry anti-patterns.

**Why it matters:** Generating code before a design decision is locked leads to cascading revisions. A 30-second brief prevents 3-minute reruns. It also makes the design reasoning auditable and client-presentable.

---

#### 3. Asset Generation Order

**Source:** Orchids.app pipeline architecture.

**What was added:**  
Rule that all image/media assets are generated in a **single batch after all code files are complete** — not inline during component writing. Reuse of existing `clients/<name>/assets/` is mandatory before triggering new generation.

**Why it matters:** Asset generation is slow and blocks code output. Batching at the end keeps the code pipeline fast and prevents partial-asset states.

---

#### 4. Navigation Integration Mandate

**Source:** Orchids.app — identified as a frequent source of broken deliverables.

**What was added:**  
Any time a new page or route is added, the navigation structure (navbar, sidebar, footer links, sitemap) must be updated **in the same task**.

**Why it matters:** A page unreachable from navigation is effectively a broken deliverable. This is a common oversight in multi-file generation tasks.

---

### Additions to `agentic-engineering.prompt.md`

#### 5. Scope Discipline

**Source:** Orchids.app `task_completion_principle`.

**What was added:**  
Explicit stop rule: the moment a request is fulfilled, stop. No additional tool calls, no unprompted improvements. Prefer the smallest viable change. Follow-up suggestions go in the final message as text, never as unilateral actions.

**Why it matters:** Over-completion is a common failure mode. Agents that "tidy up" after the task is done introduce untested changes, consume extra tokens, and erode user trust by doing work they didn't ask for.

---

#### 6. Plan-Gate Pattern

**Source:** v0's `EnterPlanMode`, Same.dev's explicit plan blocks before complex generation.

**What was added:**  
For tasks touching 3+ files, a new agent, or a schema change: present a structured plan (files affected, new behaviour, acceptance condition, model tier) and wait for user confirmation before executing.

**Why it matters:** Multi-file generation in the wrong direction produces harder-to-revert changes than single-file generation. A plan gate transforms a potential 3-minute revert into a 30-second correction.

---

#### 7. Preservation Principle

**Source:** Orchids.app — explicitly stated as a core invariant.

**What was added:**  
When implementing a change, maintain all previously working features and behaviour unless the request explicitly removes them. Callers must be identified before modifying a function. Breaking a working feature as a side effect of an unrelated change is never acceptable.

**Why it matters:** Regression is the most common quality failure in AI-assisted development. Making this principle explicit and structural (not just aspirational) closes the gap.

---

#### 8. Sub-Agent Specialization Pattern

**Source:** Orchids.app multi-agent architecture; Same.dev domain ownership model.

**What was added:**  
Specialist agents own both the schema and the API routes for their domain. The main orchestrator calls specialist agents and receives outputs — it never writes directly into a specialist's domain. Clear code example showing correct vs incorrect orchestration.

**Why it matters:** Without domain ownership enforcement, specialist agents become vestigial and the orchestrator accumulates all complexity. This pattern keeps the graph clean and makes per-agent evals feasible.

---

### Additions to `verification-loop.prompt.md`

#### 9. Loop Escape Rule

**Source:** Same.dev and Orchids both independently enforce a maximum attempt count on stuck errors.

**What was added:**  
Hard limit of **3 attempts** on the same error in the same file. On the third failure: stop, produce a structured `STUCK LOOP REPORT` (file, exact error, attempts, what was tried, root cause hypothesis, what is needed to unblock), and escalate to the user.

**Why it matters:** Looping on the same error with superficially different edits is the single most wasteful pattern in AI-assisted coding sessions. Token cost scales linearly with attempts; output quality degrades each time the context fills with failed fixes.

---

#### 10. API Contract Verification

**Source:** Orchids.app — "test every route immediately after creation."

**What was added:**  
After creating a new API route, immediately test it with 3 parallel cases: happy path (valid input → 2xx), invalid input (malformed body → 4xx), and auth boundary (unauthenticated → 401/403). Concrete `curl | jq` example included. Explicitly scoped as distinct from TDD (which is pre-creation) — this is post-creation contract confirmation.

**Why it matters:** Routes that are created but not immediately exercised silently accumulate contract drift. By the time downstream code tries to call them, the mismatch is buried in context and hard to trace.

---

## Redundancies — What Was Evaluated and Deliberately Not Added

| Competitor pattern | Reason skipped |
|---|---|
| v0: bcrypt password hashing, Supabase RLS, parameterized queries, input validation | Already covered in full by `security-review.prompt.md` |
| v0 / Orchids: Vitest unit tests, Playwright E2E | Already covered by `tdd-workflow.prompt.md` and `e2e-testing.prompt.md` |
| Same.dev: parallel tool calls, task decomposition loop | Already core to `agentic-engineering.prompt.md` |
| v0 / Orchids: ARIA roles, alt text, semantic HTML, colour contrast | Already in `website-builder.prompt.md` UX guidelines section |
| Cursor: broad→narrow search, no unnecessary file reads | Already covered by `deep-research.prompt.md` and `context-budget.prompt.md` |
| Claude.ai consumer UI system prompt | Not applicable — governs Claude.ai chat product behaviour, not agent engineering |

---

## File Change Summary

| File | Additions | Net sections added |
|---|---|---|
| `website-builder.prompt.md` | Hard Design Constraints, Pre-Build Design Brief, Asset Generation Order, Navigation Integration Mandate | +4 |
| `agentic-engineering.prompt.md` | Scope Discipline, Plan-Gate Pattern, Preservation Principle, Sub-Agent Specialization | +4 |
| `verification-loop.prompt.md` | Loop Escape Rule, API Contract Verification | +2 |
| `ADDITIONS_LOG.md` | This file | +1 (new file) |

**Total additions: 10 new sections across 3 files.**
