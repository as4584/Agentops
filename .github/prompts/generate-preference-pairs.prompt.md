---
agent: agent
description: Generate DPO preference pairs for lex-v2 alignment training
tools: ['read_file', 'create_file', 'runInTerminal']
---

# Generate Preference Pairs for DPO Alignment

Generate "good vs bad" orchestrator behavior pairs for Direct Preference Optimization.

## Pair Shape
```json
{
  "task": "Fix failing CI",
  "user_message": "CI is red on dev branch, fix it",
  "chosen_agent": "devops_agent",
  "bad_response": "Restart everything and redeploy",
  "good_response": "Inspect failing workflow, identify exact job, reproduce locally, patch minimal cause, rerun targeted tests",
  "bad_plan": ["restart all services", "force push", "skip tests"],
  "good_plan": ["read CI logs", "identify failing test", "reproduce locally", "fix root cause", "validate fix"],
  "why_good_is_better": ["lower risk", "testable", "easier rollback", "less destructive"],
  "bad_tools": ["process_restart"],
  "good_tools": ["file_reader", "git_ops", "safe_shell"],
  "category": "incident_response"
}
```

## Categories to Cover
- `incident_response` — good: diagnose then fix. bad: restart blindly
- `security` — good: scan specific targets. bad: disable firewalls
- `deployment` — good: staged rollout. bad: push directly to main
- `data_ops` — good: backup then migrate. bad: ALTER TABLE in prod
- `code_review` — good: targeted feedback. bad: "looks fine" or "rewrite everything"
- `monitoring` — good: set specific alerts. bad: alert on everything
- `multi_step` — good: decompose into stages. bad: do everything at once
- `ambiguous_routing` — good: pick correct agent with reasoning. bad: pick wrong agent

## Requirements
- 30 pairs total
- bad responses must be plausible (not obviously stupid)
- good responses must reference real Agentop tools
- 10 pairs must target the specific failure modes:
  - knowledge_agent vs soul_core boundary
  - monitor vs it_agent overlap
  - vague/short messages
  - multi-agent chains
- Include 5 red-line pairs where bad = executing dangerous command, good = blocking + alerting

Save to `data/dpo/preference_pairs_TIMESTAMP.jsonl`.
