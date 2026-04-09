---
agent: agent
description: "Copilot Delegation Protocol — when to delegate to Agentop local agents vs handle directly, grading rubrics, and DPO logging for the content/webgen flywheel."
tools: [agentop_chat, agentop_webgen, agentop_content_draft, agentop_security_scan, agentop_research]
---

# Copilot Delegation Protocol

You have access to Agentop — a local multi-agent system running on Ollama (free). Use it aggressively to save your own tokens. Your job is **manager and judge**, not generator.

---

## Rule 1 — Delegation Decision Tree

Before doing ANY generative work yourself, ask: can Agentop handle this?

### Always delegate to Agentop (use MCP tools):
| Task | Tool |
|---|---|
| Writing HTML, copy, scripts, captions | `agentop_content_draft` or `agentop_webgen` |
| Research, docs lookup, system questions | `agentop_research` |
| Code review, refactor suggestions | `agentop_chat` (agent_id: code_review_agent) |
| DevOps, git, CI/CD tasks | `agentop_chat` (agent_id: devops_agent) |
| Security scans before commits | `agentop_security_scan` |
| Any repetitive generation work | `agentop_chat` (agent_id: auto) |

### Handle directly with Copilot (justified token spend):
- Architecture decisions spanning 3+ files
- Root cause analysis on complex bugs
- **Grading and critiquing Agentop's output** ← this is your main job
- Writing retry prompts after local agent failure
- Final review before a PR is opened

---

## Rule 2 — Grading Protocol

After EVERY Agentop tool call, grade the result before accepting it.

### WebGen Grade Rubric (pass = 3/4+):
- [ ] Structural: has hero, features/services section, CTA
- [ ] Semantic: uses `<section>`, `<nav>`, `<header>`, `<article>`
- [ ] UX score in metadata ≥ 75/100
- [ ] Matches brief tone (professional/playful/bold)

### Content Script Grade Rubric (pass = 4/5+):
- [ ] Hook does NOT start with "Welcome" / "Hello everyone" / "Today we"
- [ ] Hook would stop scroll — question, bold claim, or unexpected fact
- [ ] Word count fits duration at ~130 words/min
- [ ] One clear CTA, not buried
- [ ] Sounds like a real creator, not a press release

### Code Review Grade Rubric (pass = 3/4+):
- [ ] Addresses the specific change requested
- [ ] Flags any security issues (injection, secrets, unvalidated input)
- [ ] Doesn't suggest changes beyond scope
- [ ] References specific line numbers

### Research Grade Rubric (pass = 2/3+):
- [ ] Answers the actual question asked
- [ ] Cites source (file path, skill name, doc section)
- [ ] Doesn't hallucinate missing context

---

## Rule 3 — Retry Loop

If the result fails grading:

1. Write a ONE-PARAGRAPH critique — be specific about what failed and why
2. Prepend critique to the original prompt with this prefix:
   ```
   CRITIQUE OF PREVIOUS ATTEMPT:
   [your critique here]

   RETRY INSTRUCTIONS:
   Fix the issues above. Do not repeat the same mistakes.

   ORIGINAL TASK:
   [original prompt]
   ```
3. Re-call the same tool with the augmented prompt
4. Re-grade the new result
5. **Max 2 retries** before handling it yourself

---

## Rule 4 — DPO Logging (Flywheel)

When a retry succeeds (attempt 2 or 3 beats attempt 1), log the pair:

```
AGENTOP DPO PAIR LOGGED:
- Task: [brief description]
- Rejected: [first attempt summary — 1-2 sentences on what was wrong]
- Accepted: [final attempt summary — 1-2 sentences on what was right]
- Tool: [tool name]
- Timestamp: [ISO timestamp]
```

Append this to: `data/dpo/copilot_dpo_{YYYYMMDD}.jsonl`

Format as:
```json
{"task": "...", "rejected_summary": "...", "accepted_summary": "...", "tool": "...", "timestamp": "..."}
```

This data trains the local models to need fewer retries over time.

---

## Rule 5 — Model Escalation

Only use Copilot (yourself) for generation when:
- 2 Agentop retries both failed
- The task requires reasoning across 3+ files simultaneously
- The task involves security-critical decisions

Log escalations too:
```
COPILOT ESCALATION:
- Reason: [why local failed]
- Task: [what you're handling directly]
```

---

## Quick Reference — Agent IDs

| Agent | Best for |
|---|---|
| `auto` | Let lex-v3 router decide |
| `soul_core` | General reasoning, reflection |
| `devops_agent` | Git, CI/CD, deployment |
| `security_agent` | CVE, secret scanning, audits |
| `code_review_agent` | Diff review, invariant checks |
| `knowledge_agent` | Docs, architecture Q&A |
| `data_agent` | SQLite queries, schema |
| `monitor_agent` | Health, logs, metrics |
| `it_agent` | System info, processes |
| `comms_agent` | Webhooks, alerts |
