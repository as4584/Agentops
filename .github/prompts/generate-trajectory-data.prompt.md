---
agent: agent
description: Generate orchestration trajectory examples for lex-v2 training
tools: ['read_file', 'create_file', 'runInTerminal']
---

# Generate Trajectory Training Data for Orchestration

You are generating multi-step orchestration traces that train lex-v2 to plan and execute complex tasks.

## Trajectory Shape
```json
{
  "task": "Deploy updated Discord bot safely",
  "task_type": "deployment",
  "goal": "Ship bot update without breaking current service",
  "constraints": ["Ubuntu only", "minimal diff", "must validate before restart"],
  "retrieval_needed": true,
  "chosen_agent": "devops_agent",
  "rejected_agents": ["self_healer_agent", "it_agent"],
  "plan": ["Inspect service config", "Review changed files", "Run tests", "Restart service"],
  "actions": ["opened systemd service file", "checked bot token env usage", "ran pytest -q"],
  "validations": ["pytest -q", "systemctl status discord-bot"],
  "result": "Deployment approved after passing tests",
  "why_this_route_was_correct": "Deployment task with validation constraints maps to devops, not self-healer (which is reactive, not proactive)"
}
```

## Task Types to Cover
- `deployment` — CI/CD, shipping code, rollbacks
- `incident_response` — something broke, need fix NOW
- `security_audit` — scan, assess, remediate vulnerabilities
- `data_pipeline` — ETL, schema changes, migrations
- `monitoring_setup` — configure alerts, dashboards, health checks
- `code_review` — PR review, pattern enforcement
- `knowledge_query` — "what does doc X say about Y?"
- `multi_agent_chain` — task requires 2+ agents in sequence
- `ambiguous` — could go to multiple agents, reasoning must justify choice

## Requirements
- 30 trajectories total
- Each must include `rejected_agents` with reasoning why they were NOT chosen
- 10 must be `multi_agent_chain` (e.g., security scan → code review → deploy)
- 5 must be `ambiguous` with detailed `why_this_route_was_correct`
- All constraints must be realistic (not generic)
- Actions should reference real Agentop tools: safe_shell, file_reader, git_ops, health_check, etc.
- Validations must be executable commands

Save to `data/training/trajectory_TIMESTAMP.jsonl`.
