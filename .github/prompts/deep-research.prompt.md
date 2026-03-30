---
agent: agent
description: "Deep Research — structured multi-source research workflow with citations, sub-question decomposition, and executive summary output."
tools: [search/codebase]
---

# Deep Research

Produce thorough, cited research reports from multiple sources. Use this skill any time the user wants analysis grounded in evidence rather than training data alone.

## When to Activate

- Researching a technology, library, or architectural pattern
- Competitive analysis of AI tools, SaaS products, or frameworks
- Evaluating a third-party API or vendor before integration
- Understanding "what's the current state of X"
- Any request with keywords: research, deep dive, investigate, what's the latest on, compare

---

## Workflow

### Step 1 — Understand the Goal

Before diving in, clarify intent in 1-2 questions:
- "Is this for making a decision, writing something, or learning?"
- "Any specific angle or depth level you want?"

If the user says "just research it" — skip ahead.

### Step 2 — Break into Sub-Questions

Decompose the topic into 3-5 focused sub-questions. Example:

```
Topic: "Should Agentop use LangGraph or a custom orchestrator for agent pipelines?"

Sub-questions:
1. What specific workflow patterns does LangGraph excel at?
2. What are the known failure modes and limitations of LangGraph?
3. How does LangGraph's state management compare to custom solutions?
4. What are teams reporting in production about cost and latency?
5. What would a minimal custom orchestrator need to match LangGraph's key features?
```

### Step 3 — Execute Multi-Source Search

Search each sub-question using available tools. Use 2-3 keyword variations per sub-question:

**With web tools (if available via MCP):**
```
search: "LangGraph production issues 2025"
search: "LangGraph alternatives custom orchestrator"
search: "LangGraph vs CrewAI performance comparison"
```

**Without web tools — use structured workspace search:**
```bash
# Search existing docs and knowledge in the repo
grep -rn "langgraph\|orchestrator\|agent.*pipeline" \
  /root/studio/testing/Agentop/docs/ \
  /root/studio/testing/Agentop/backend/ \
  --include="*.md" --include="*.py" -l

# Check existing knowledge base
ls /root/studio/testing/Agentop/backend/knowledge/
```

Target 10-20 unique sources. Prioritize: official docs, GitHub issues, technical blogs > forums > social.

### Step 4 — Deep-Read Key Sources

For the most relevant sources, read the full content — don't rely on search snippets alone. For 3-5 key pages, extract the core argument and quantitative data.

### Step 5 — Synthesise and Write Report

Use this structure for every research output:

```markdown
# [Topic]: Research Report
*Date: [date] | Sources: [N] | Confidence: [High/Medium/Low]*

## Executive Summary
[3-5 sentences covering the core finding and recommendation]

## 1. [First Major Theme]
[Findings with inline citations]
- Key point ([Source](url))
- Supporting data with numbers where possible ([Source](url))

## 2. [Second Major Theme]
...

## 3. [Third Major Theme]
...

## Gaps / Uncertainties
- [Area where data was thin or conflicting]
- [Claim that only one source supports — treat as unverified]

## Key Takeaways
- [Actionable insight 1]
- [Actionable insight 2]
- [Actionable insight 3]

## Sources
1. [Title](url) — one-line summary
2. ...

## Methodology
Searched N queries. Analyzed M sources.
Sub-questions investigated: [list them]
```

### Step 6 — Deliver

- **Short topics** (≤3 sub-questions): post full report in chat
- **Long reports** (>5 sub-questions or >1000 words): post executive summary + takeaways in chat, save full report to a file in `docs/`

---

## Quality Rules

1. **Every claim needs a source.** No unsourced assertions, even if plausible.
2. **Cross-reference.** If only one source says it, flag as unverified.
3. **Recency matters.** Prefer sources from the last 12 months for fast-moving topics.
4. **Acknowledge gaps.** If you couldn't find good data on a sub-question, say so explicitly.
5. **No hallucination.** If you don't know, say "insufficient data found" — never fill gaps with training data presented as research.
6. **Separate fact from inference.** Label estimates, projections, and opinions clearly.

---

## Examples for Agentop Context

```
"Research the current state of streaming HTML generation with Claude"
"Deep dive into cost patterns for running 10+ LLM calls per webgen job"
"Investigate whether BM25 or vector search is better for our design system lookup"
"Research competitors to the Agentop webgen pipeline — who else is doing AI-driven site generation?"
"What's the current best practice for rate-limiting FastAPI endpoints?"
```

---

## Saving Research to Docs

For findings that inform architecture decisions, save to `docs/`:

```bash
# Name clearly with date for chronological ordering
cat > /root/studio/testing/Agentop/docs/research-langgraph-vs-custom-2025-07.md << 'EOF'
[paste report here]
EOF
```

Update `docs/SOURCE_OF_TRUTH.md` if the research changes a standing decision.
