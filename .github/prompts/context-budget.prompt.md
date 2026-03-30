---
agent: agent
description: "Context Budget — audit token overhead across prompt files, agents, and MCP tools. Identify bloat and surface savings before adding more components."
tools: [search/codebase]
---

# Context Budget

Audit token overhead across the Agentop prompt system — `.github/prompts/`, `backend/agents/`, and MCP configs. Run this before adding new components, or when session quality starts degrading.

## When to Use

- Adding a new prompt file or agent definition
- Noticing degraded output quality in long sessions (context pressure)
- Wanting to know how much headroom is available
- After a batch of new skills were added (like right now)

---

## Phase 1 — Inventory

### Prompt Files

```bash
cd /root/studio/testing/Agentop

# Count tokens (est: words × 1.3) per prompt file
for f in .github/prompts/*.prompt.md; do
    words=$(wc -w < "$f")
    tokens=$(echo "$words * 1.3 / 1" | bc)
    lines=$(wc -l < "$f")
    echo "${tokens} tokens  ${lines} lines  $f"
done | sort -rn
```

Flag files over **400 lines** or **500 tokens** as heavy.

### Agent Definitions

```bash
for f in backend/agents/*.py backend/agents/**/*.py 2>/dev/null; do
    lines=$(wc -l < "$f")
    words=$(wc -w < "$f")
    tokens=$(echo "$words * 1.3 / 1" | bc)
    echo "${tokens}t ${lines}l  $f"
done | sort -rn | head -20
```

### MCP Config

```bash
cat mcp-gateway/config.yaml 2>/dev/null | grep -E "name:|tools:" | head -30
cat mcp-gateway/registry.yaml 2>/dev/null | head -40
```

Estimate: **~500 tokens per MCP tool** schema. Servers wrapping simple CLI commands (git, npm, pip) are the biggest waste — those tools are free from bash.

---

## Phase 2 — Classify

Sort every component:

| Bucket | Criteria | Action |
|---|---|---|
| **Always needed** | Invoked in most sessions, maps to current project phase | Keep |
| **Sometimes needed** | Domain-specific (e.g. only for webgen, not for backend work) | Keep but consider lazy-load |
| **Rarely needed** | No active reference, overlaps with another file, or outdated | Defer or remove |

---

## Phase 3 — Issue Patterns

Look for these known problems:

**Bloated descriptions** — frontmatter `description:` field over 25 words gets loaded in every Copilot invocation. Trim to a tight phrase.

**Redundant skills** — two prompt files teaching the same thing. Examples to watch for:
- `python-patterns` + `coding-standards` (if coding-standards is later imported)
- `tdd-workflow` + `python-testing` — overlapping content; keep both now, consolidate later if they drift

**MCP over-subscription** — more than 10 active MCP tools from servers wrapping CLI tools you already have in bash.

**Outdated sections** — any section referencing a feature that no longer exists in the codebase.

---

## Phase 4 — Report Template

Produce this after running Phase 1:

```
CONTEXT BUDGET REPORT
══════════════════════════════════════

Component               Files   Est. Tokens
─────────────────────────────────────────────
.github/prompts/        N       ~X,XXX
backend/agents/         N       ~X,XXX
MCP tools               N       ~X,XXX
─────────────────────────────────────────────
Total overhead                  ~XX,XXX

Context window: 200K (Claude Sonnet)
Headroom remaining:             ~XXX,XXX (XX%)

⚠ Issues:
1. [heavy file] — N tokens, consider trimming sections no longer relevant
2. [redundant pair] — overlap with [other file], merge or split by trigger
3. [MCP server] — N tools wrapping CLI commands available via bash for free

Top 3 Savings:
1. [action] → save ~X,XXX tokens
2. [action] → save ~X,XXX tokens
3. [action] → save ~X,XXX tokens
```

---

## Token Estimation Rules

- **Prose paragraphs**: `word_count × 1.3`
- **Code blocks**: `char_count / 4`
- **YAML/JSON configs**: `char_count / 3.5`
- **MCP tool schema**: `~500 tokens per tool`

---

## Best Practices

**Agent description frontmatter is loaded always.** Even if the prompt file is never explicitly invoked, its `description:` field is visible in all Copilot tool invocations. Keep descriptions ≤20 words.

**Audit after every addition.** Adding a new prompt or MCP server? Run Phase 1 immediately to see the impact before it silently accumulates.

**Heavy files are fine if they're always relevant.** A 600-token `verification-loop.prompt.md` that is invoked every session is not waste. A 600-token file invoked once a month is.

**Verbose mode for debugging:** When you need to pinpoint what's driving overhead, add `wc -l` and character counts to the Phase 1 scan.

---

## Current Prompt Inventory (as of last audit)

```bash
ls -la /root/studio/testing/Agentop/.github/prompts/*.prompt.md | awk '{print $5, $9}'
```

Run this to get the current state. Add a note here after each audit with the token total so you can track growth over time.
