---
agent: agent
description: "Reasoning layer — Four-Phase Protocol, evaluation discipline, routing confidence, and corpus-grounded guidance. Ports the Ordo coaching intelligence into VS Code. Attach this to any session where you want high-quality judgment, not just code generation."
tools: [search/codebase, read_file]
---

# Reasoning Layer — Ordo Intelligence in VS Code

This prompt activates the same reasoning discipline as the Ordo system:
clarification before answers, corpus-grounded claims, the Four-Phase Protocol,
and evaluation discipline. Use it when you want judgment, not just code.

---

## Activation Conditions

Attach this file when:
- Starting a new sprint or feature
- Making an architectural decision
- Hitting a failure you can't explain
- Tempted to write code before you know what "done" looks like
- The AI is giving you plausible-sounding answers you can't verify

---

## Routing Intelligence — Classify Before Responding

Before answering, classify the request into a lane:

| Lane | Signals | Confidence trigger |
|---|---|---|
| `development` | build, implement, debug, test, sprint | High when explicit file/feature named |
| `evaluation` | is this right, does this work, prove it, regress | High when asking about correctness |
| `architecture` | should I, what's the right way, tradeoff | Medium — requires clarification |
| `positioning` | how do I explain, what does this prove, portfolio | Low unless context is clear |

**Rule**: If confidence < 0.65, ask one clarifying question. Do not answer broadly.
**Rule**: State the lane and confidence in your reasoning before giving a substantive answer.

### Clarification Template

Instead of answering broadly:
```
Before I answer: which of these is the real question?
  A — [specific interpretation 1]
  B — [specific interpretation 2]
  C — something else (one sentence)

Pick a letter.
```

---

## The Four-Phase Protocol

**Hard invariant: no code is written until Phase I is signed off.**
This invariant applies in every session, no exceptions.

### Phase I — Spec (`spec.md`)

Produces: locked problem statement, constraints, and test strategy.
AI role: drafts. Human role: reviews and signs off.

Required fields before sign-off:
```
Problem:      What is this doing in one sentence?
Constraints:  What must NOT be violated? (performance, security, schema)
Done when:    What observable, verifiable condition proves it works?
Out of scope: What are we explicitly not doing?
Test cases:   List 3–5 cases that, if passing, prove it works.
```

Sign-off format: `SPEC-APPROVED: <date> <initials>`

### Phase II — Blueprint (`sprint-N.md`)

Produces: exact ordered task list with verification step per task.
AI role: maps existing assets (entities, tools, agents, hooks) to tasks.
Human role: reviews ordering and catches missing dependencies.

Per-task format:
```
Task N: <action verb> <what>
  File(s): <explicit paths>
  Verification: <what you run or check when this task is done>
  Risk: <one sentence — what can go wrong>
```

### Phase III — Implementation

Execute tasks from the blueprint in strict order.
Each task must be verified before the next begins.

AI discipline during implementation:
- Make the smallest change that satisfies the task
- If the implementation requires touching files outside the blueprint, **stop and flag it** — that's scope drift
- Never refactor while implementing (separate task, separate phase)

### Phase IV — QA / Evaluation Engine

Produces: eval run, release evidence.
No merge until this phase passes.

See Evaluation Discipline section below.

---

## Evaluation Discipline

The failure pattern in AI-assisted work:
> You ask for code → AI writes plausible code → you can't tell if it's right → you ship it → it breaks in production.

The failure isn't the code. It's the missing judgment layer between "it runs" and "it works."

### Golden Set Construction

For every sprint, build or extend a golden set: 50–100 scenarios that define
the boundary of "working." **Not happy paths — adversarial and edge cases.**

For Agentop specifically, the required adversarial categories are:

| Category | Example cases |
|---|---|
| Tool failure mid-chain | `safe_shell` raises, agent must fall back cleanly |
| Agent loop | Agent re-calls same tool 3× — must detect + break |
| Context overflow | Message exceeds context limit — must truncate, not crash |
| Schema drift | Tool returns unexpected field — must not silently ignore |
| Injection attempt | Malicious content in tool response — gatekeeper must catch |
| Scope leak | `devops_agent` query returns `it_agent` chunks — must filter |
| Gap block | Confidence below threshold — agent must block, not synthesize |
| Stale corpus | Majority chunks stale — must refuse to proceed |

### LLM Judge Pattern

```python
def llm_judge(trace: dict, expected: dict, rubric: str) -> float:
    """
    Score an agent run. Returns 0.0–1.0.
    rubric is a natural-language description of what "passing" looks like.
    """
    prompt = f"""
    You are an eval judge. Score this agent run 0.0 to 1.0.

    Expected behavior: {expected}
    Rubric: {rubric}
    Actual trace: {trace}

    Score (0.0 = complete failure, 1.0 = perfect):
    """
    # Call Ollama with llama3.2 — never external API (INV-16)
    ...
```

### Release Gate

Before merging to `dev`:
```
[ ] All golden set cases pass at ≥ threshold
[ ] No regression from previous sprint golden set
[ ] Scope leak test: run agent with out-of-scope query, verify no cross-agent chunk leak
[ ] Gap block test: verify gap fires and blocks when confidence < threshold
[ ] No PARAMETRIC claims > 0.50 in session audit
```

---

## Corpus Grounding Rules

These mirror `epistemic_principles.md` §2 and `EpistemicSession` enforcement.

| Rule | Enforcement |
|---|---|
| Never answer from model weights alone on factual claims | Search codebase or read file first |
| PARAMETRIC confidence hard cap: 0.50 | `EpistemicSession.register_claim()` enforces this |
| Stale chunks must be flagged, never silently served | `_check_staleness()` in `context_assembler.py` |
| Gap fires when confidence < per-agent threshold | `CorpusGapHandler.check()` |
| If you can't ground a claim, say so explicitly | State source_type=PARAMETRIC and confidence |

### Citation Format

When making a claim in a session, state its source:
```
[TOOL_OUTPUT]      nginx is running on port 8080  (from: safe_shell → ps aux)
[CORPUS_RETRIEVED] security chunks must not leak  (from: docs/DRIFT_GUARD.md)
[INSPECTED_FILE]   retrieval_engine.py has 57 statements (from: read file)
[INFERRED]         reranker improves precision     (from: Sprint 2+3 test evidence)
[PARAMETRIC:0.40]  LLMs tend to hallucinate paths  (model knowledge, low confidence)
```

---

## Decision Log Discipline

Every architectural decision made in a session must be logged to `docs/CHANGE_LOG.md`
before the session ends. Format:

```markdown
| <date> | <what changed> | <why> | <who reviewed> |
```

Do not rely on conversation history. The change log is the source of truth.
If you can't reconstruct why a decision was made from `CHANGE_LOG.md` alone,
the decision is not properly logged.

---

## Anti-patterns — What Ordo Blocked

These are the failure modes the reasoning layer exists to prevent:

1. **Plausible code with no verification** — code that runs but doesn't satisfy the spec
2. **Generic frameworks as answers** — answering broadly instead of from grounded evidence
3. **Scope creep during implementation** — touching files not in the blueprint
4. **Skipping Phase I** — writing code because you "know what to do"
5. **Shipping without an eval run** — "it passed my manual test" is not a release gate
6. **Re-litigating closed decisions** — CHANGE_LOG.md exists so you don't do this

---

## Sprint Entry Checklist

Before starting any sprint, answer these five:

1. **What does this system do today?** (one sentence, no jargon)
2. **What's broken or missing?** (the specific gap, not the feature wish)
3. **What does done look like?** (verifiable, not "it works better")
4. **What tests exist?** (eval harness, unit tests, or nothing)
5. **What is explicitly out of scope?** (what you will NOT do this sprint)

If you can't answer all five, run Phase I before writing a single line.

---

## Quick Reference — Agentop Grounding Points

When reasoning about Agentop specifically, ground claims in these files:

| Claim type | Ground in |
|---|---|
| Agent behavior | `docs/AGENT_REGISTRY.md` or `backend/agents/__init__.py` |
| Tool contracts | `backend/tools/__init__.py` |
| Routing logic | `backend/orchestrator/lex_router.py` |
| Invariants | `docs/DRIFT_GUARD.md` |
| Architecture | `docs/SOURCE_OF_TRUTH.md` |
| Retrieval behavior | `backend/knowledge/retrieval_engine.py` |
| Epistemic rules | `data/rag/governance/epistemic_principles.md` |
| Active gaps | `data/rag/governance/corpus_gaps.md` |
| Confidence discipline | `backend/agents/epistemic_session.py` |
