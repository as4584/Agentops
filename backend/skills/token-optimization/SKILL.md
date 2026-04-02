---
name: token-optimization
description: Prompt engineering and LLM token cost optimization strategies
---
# Token Optimization & Vocabulary Power

**Domain:** Prompt Engineering & LLM Economics  
**Key Thinkers:** Claude Shannon, Andrej Karpathy, Ilya Sutskever

## Core Principle

Every token costs compute, energy, and money. Precise vocabulary activates dense knowledge clusters in LLM parameters. Vague language scatters attention across low-signal pathways and wastes context window budget.

## Key Frameworks

### Shannon's Source Coding
- Information has optimal encoding; efficient encoding wins
- Applied to prompting: precise prompts are compressed; vague prompts are bloated

### Token Economics
- **Vague prompt:** Many rounds of clarification, high total token cost
- **Precise prompt:** One-pass clarity, low token cost  
- At scale, imprecision multiplies into infrastructure cost

### Vocabulary Power Model
- **Named concepts** = indexed lookup (4-6 tokens activate an entire knowledge cluster)
- **Vague descriptions** = full-table scan (12+ tokens, fuzzy activation)
- Example: "Ward Cunningham technical debt" vs "that shortcut thing where you save time now but pay later"

### Context Window Budget
- Total available tokens = System prompt + History + Skill injection + Response space
- Every byte of context counts; budget ruthlessly

## Prompt Compression Strategies

1. **Use named frameworks** instead of descriptions
2. **Reference people by name** rather than "famous expert in X"
3. **Invoke patterns** using concise vocabulary
4. **Shared compressed protocols** between human and AI (like TCP/IP has SYN/ACK/FIN)

## Application to Agentop

- Use skill injection strategically; each skill costs tokens
- Name agents by role, not description
- Reference domain knowledge by framework name, not full explanation
- Measure cost: (tokens spent) / (knowledge activated) — higher ratio = more efficient

## Key Concepts

- At pipeline scale, token waste multiplies into real cost
- The most efficient encoding wins (Shannon, 1948)
- LLMs compress language as token sequences; compress your prompts too
