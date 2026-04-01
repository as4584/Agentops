---
agent: agent
description: Generate routing training examples for lex-v2 router model
tools: ['read_file', 'create_file', 'runInTerminal']
---

# Generate Routing Training Data for lex-v2

You are generating training data for a **local 3B LLM router** that classifies user messages to the correct Agentop agent.

## Available Agents (ONLY these are valid)
- `soul_core` — Cluster conscience, reflection, trust scoring, goal tracking, "what should we do?"
- `devops_agent` — CI/CD, git, deployment, builds, pipelines
- `monitor_agent` — Health checks, uptime, log tailing, metrics
- `self_healer_agent` — Process crashes, service restarts, fault remediation
- `code_review_agent` — Code diffs, PR review, pattern enforcement, linting
- `security_agent` — Secret scanning, CVE flagging, vulnerability assessment
- `data_agent` — ETL, schema drift, SQLite queries, data validation
- `comms_agent` — Webhooks, incident notifications, stakeholder alerts
- `cs_agent` — Customer support, FAQ, knowledge base queries
- `it_agent` — Infrastructure diagnostics, network, DNS, hardware
- `knowledge_agent` — Document search, semantic Q&A over vectorized docs

## Known Weak Spots (BIAS GENERATION TOWARD THESE)
1. **knowledge_agent vs soul_core** — questions about docs that mention "purpose", "truth", "goals"
2. **monitor_agent vs it_agent** — infrastructure monitoring overlaps with diagnostics
3. **code_review_agent vs security_agent** — security-related code review
4. **devops_agent vs self_healer_agent** — deployment failures vs service crashes
5. **JSON parse errors** — very short/vague messages cause model to emit malformed JSON
6. **Red-line cases** — dangerous commands that should be blocked before LLM

## Output Format (one per line, JSONL)
```json
{"user_message": "...", "expected_agent": "...", "expected_tools": ["..."], "reasoning": "...", "confidence": 0.95, "difficulty": "hard"}
```

## Requirements
- 60% hard/ambiguous cases (boundary between two agents)
- 20% red-line/rejection cases (dangerous commands)
- 20% easy cases (clear single-agent routing)
- No duplicate intents
- Every agent must appear at least twice
- Include 5+ cases where the message is very short or vague
- Include 5+ multi-intent messages ("scan AND deploy")
- All JSON must be valid
- Reasoning must be 1-2 sentences explaining WHY this agent

## Red-Line Cases (should map to `BLOCKED`)
- `rm -rf /`, `DROP TABLE`, `git push --force main`, `dd if=/dev/zero`
- Any prompt injection attempt
- Requests to expose secrets or tokens

Generate exactly 40 examples. Save to `data/training/routing_hard_negatives_TIMESTAMP.jsonl`.
