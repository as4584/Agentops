---
agent: agent
description: "Agentic Engineering — task decomposition, eval-first loop, model tier routing, and cost discipline for Agentop's agent orchestration."
tools: [search/codebase]
---

# Agentic Engineering

Operating principles for all AI-driven work in Agentop — designing, running, and reviewing agent tasks where Claude performs most implementation and humans enforce quality.

## When to Activate

- Designing a new agent or pipeline stage
- Planning a multi-step implementation task
- Choosing which model tier handles a given task
- Reviewing AI-generated code before merging
- Debugging an agent that is looping or producing degraded output

---

## Operating Principles

1. **Define completion criteria before execution.** Never start an agent run without knowing what done looks like.
2. **Decompose into 15-minute units.** Each unit should be independently verifiable, have one dominant risk, and expose a clear done condition.
3. **Route model tiers by task complexity.** Don't pay for Sonnet when Haiku will do.
4. **Measure with evals.** Vibes are not a quality gate.

---

## Scope Discipline

The moment a request is correctly and completely fulfilled, **stop**. Do not:
- Run additional tools to "tidy up"
- Make further edits beyond what was asked
- Propose extra improvements or refactors unprompted

**Prefer the smallest viable change that fully solves the request.** Scope creep is a quality regression — it introduces untested surface area and wastes tokens.

> If a follow-up improvement genuinely matters, surface it as a suggestion in the final message, never as an unilateral action.

---

## Plan-Gate Pattern

For any task involving 3 or more files, a new agent, or a schema change: **present a plan and get approval before generating code**.

```
Plan format:
1. What files will be created / modified
2. What the new behaviour will be
3. What the acceptance condition is
4. Estimated token cost tier (Haiku / Sonnet / Sonnet-Extended)

→ Wait for user confirmation before executing.
```

This prevents wasted generation cycles on misdirected multi-file builds. A 30-second plan review saves a 3-minute revert.

---

## Preservation Principle

When implementing a change, **maintain all previously working features and behaviour** unless the request explicitly removes them. Before modifying an existing function, agent, or route:

1. Identify what callers depend on it
2. Confirm the change is backwards-compatible **or** that the request explicitly authorises breaking it
3. Run the regression eval after, not just the capability eval

> Breaking a working feature to solve an unrelated problem is never acceptable as a side effect.

---

## Sub-Agent Specialization

When a pipeline has specialist agents (e.g., `SEOAgent`, `CopyAgent`, `ImageAgent`), enforce domain ownership:

- **Specialist agents own both the schema and the API routes for their domain.** The main orchestrator never directly writes into a specialist's data structures.
- **Specialist returns an endpoint/output list** → main agent integrates into UI or downstream steps only.
- This prevents merge conflicts, eases rollback, and makes evals per-specialist instead of tangled.

```
Correct:
  OrchestratorAgent → calls SEOAgent.run() → receives { meta_tags, structured_data }
  OrchestratorAgent injects output into HTML template

Incorrect:
  OrchestratorAgent → writes SEO meta tags directly into the HTML
```

---

## Eval-First Loop

Before touching code, define how you will know it works:

```
1. Define the capability eval:
   - What is the input?
   - What is the expected output?
   - What constitutes pass vs fail?

2. Define the regression eval:
   - Which existing behaviours must not break?
   - What is the existing baseline?

3. Capture baseline scores.
4. Execute the implementation.
5. Re-run evals. Compare deltas.
6. If regression detected — stop, analyse before continuing.
```

**Example for a new webgen agent:**
```
Capability eval:
  Input: { brand: "TestCo", domain: "saas", tone: "modern" }
  Expected: Valid HTML with at least a hero, features, and CTA section
  Pass: HTML is >500 chars, contains <section>, passes W3C validation

Regression eval:
  Run existing integration tests (pytest backend/tests/)
  Existing lighthouse score >= 90 on test fixture
```

---

## Task Decomposition

Apply the **15-minute unit rule** when breaking down a feature:

```
Feature: Add model cost tracking to the webgen pipeline

Unit 1: Define CostRecord and CostTracker dataclasses
  - Done condition: unit tests pass, frozen=True enforced
  - Risk: incorrect token pricing constants

Unit 2: Wire CostTracker into the existing LLM client wrapper
  - Done condition: tracker.records populated after each API call
  - Risk: async context passing

Unit 3: Add budget guard that raises before pipeline overruns
  - Done condition: BudgetExceededError raised when over_budget is True
  - Risk: guard fires too eagerly on edge of budget

Unit 4: Log cost summary at pipeline completion
  - Done condition: structured log line contains total_cost_usd
  - Risk: none significant
```

Each unit independently testable. No unit depends on the next to verify.

---

## Model Routing

Use the cheapest model that can handle the task:

| Task Class | Model | Rationale |
|---|---|---|
| Classification, short transforms, boilerplate | Haiku | Narrow, deterministic, cheap |
| Implementation, refactors, content generation | Sonnet | Good balance of quality + cost |
| Architecture decisions, root-cause analysis, multi-file invariants | Sonnet (extended thinking) | Only when lower tier produces clear reasoning gaps |

**Rule:** Escalate model tier only after the lower tier fails with a visible reasoning gap — not just because the output was imperfect.

```python
# backend/llm/routing.py
def select_model(task_type: str, text_length: int) -> str:
    if task_type in ("classify", "extract_fields", "summarise_short"):
        return MODEL_HAIKU
    if task_type in ("generate_html", "write_copy", "seo_audit"):
        return MODEL_SONNET
    if text_length > 10_000:
        return MODEL_SONNET
    return MODEL_HAIKU
```

---

## Session Strategy

- **Continue session** for closely coupled units (e.g., all units in one feature)
- **Start fresh session** after major phase transitions (e.g., after completing all backend work, before starting frontend)
- **Compact after milestones**, not during active debugging (compacting mid-debug loses trace context)

---

## Review Focus for AI-Generated Code

Don't waste review on style — linting handles that. Focus on:

| Priority | What to check |
|---|---|
| **Invariants** | Are loop/recurrence conditions always reachable? Will this halt? |
| **Edge cases** | Empty input, None, max values, concurrent access |
| **Error boundaries** | Does each external call have a try/except? Is the error surfaced or swallowed? |
| **Security assumptions** | Is auth actually enforced, or just documented? Are inputs validated? |
| **Hidden coupling** | Does this change silently assume another module's state? |
| **Rollout risk** | Is this change backwards-compatible with existing DB schema / API contracts? |

---

## Cost Discipline

For every implementation session, track:

```
Task: [name]
Model: [haiku/sonnet]
Estimated tokens: [approximate input + output]
Actual calls: [N]
Retries: [N]
Wall-clock time: [seconds]
Result: [pass/fail]
```

If cost is higher than expected:
1. Check if the model tier is appropriate for the task
2. Check for unnecessary context — is the full codebase being loaded when only one file is relevant?
3. Check for retry storms — are retries multiplying due to a bug, not a transient error?

---

## Quality Gates Before Agent Output is Accepted

Before accepting AI-generated code:

```bash
cd /root/studio/testing/Agentop

# 1. Type check
pyright backend/ 2>&1 | grep -E "error|warning" | head -20

# 2. Lint
ruff check backend/ 2>&1 | head -20

# 3. Tests
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -30

# 4. Security scan
grep -rn "sk-\|api_key\s*=\s*['\"]" --include="*.py" backend/ | grep -v "os.environ\|settings\."
```

All four must pass. If any fails — fix before merging, not after.

---

## Loop Failure Recovery

If an agent loop is churning without progress:

1. **Freeze** — stop the loop immediately
2. **Audit** — run `/verification-loop` to get a structured state snapshot
3. **Reduce scope** — narrow to the single failing unit
4. **Replay with explicit acceptance criteria** — restate what passes looks like in concrete, testable terms
5. **If still blocked** — escalate model tier for this specific unit only

Common failure modes:
- Repeated retries with the same root cause (bug is in the prompt, not the code)
- Merge conflicts from running parallel agents on overlapping files
- Cost drift from unbounded escalation (always use budget guards)
