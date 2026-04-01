# Copilot Instructions for Agentop

## Project Context
Agentop is a local-first multi-agent system. All LLM inference runs through Ollama.
The custom `lex-v2` model is a 3B router that classifies user messages to the correct agent.

## Valid Agent IDs (ONLY these exist)
- `soul_core` — Reflection, trust, purpose, goal arbitration
- `devops_agent` — CI/CD, git, deployment, builds
- `monitor_agent` — Health checks, logs, metrics, alerts
- `self_healer_agent` — Process crashes, restarts, fault remediation
- `code_review_agent` — Code diffs, PR review, pattern enforcement
- `security_agent` — Secret scanning, CVE flagging, vulnerability
- `data_agent` — ETL, schema, SQLite queries, data validation
- `comms_agent` — Webhooks, incident notifications, alerts
- `cs_agent` — Customer support, FAQ, knowledge base
- `it_agent` — Infrastructure diagnostics, network, DNS
- `knowledge_agent` — Document search, semantic Q&A

## Valid Tools (12 native)
safe_shell, file_reader, doc_updater, system_info, webhook_send,
git_ops, health_check, log_tail, alert_dispatch, secret_scanner,
db_query, process_restart

## Training Data Generation Rules

### Routing Examples
- Output JSONL with: user_message, expected_agent, expected_tools, reasoning, confidence, difficulty
- 60% hard/ambiguous, 20% red-line, 20% easy
- Known weak boundaries: knowledge_agent↔soul_core, monitor↔it_agent, review↔security
- NEVER invent agent names that aren't in the list above
- Red-line cases use expected_agent="BLOCKED"

### Trajectory Examples
- Output JSONL with: task, task_type, goal, constraints, chosen_agent, rejected_agents, plan, actions, validations, result, why_this_route_was_correct
- Actions must reference real tools (e.g., "file_reader: read config.py")
- rejected_agents must include reasoning why they were NOT chosen
- Multi-agent chains: specify handoff order

### Preference Pairs
- Output JSONL with: task, user_message, chosen_agent, good_response, bad_response, good_plan, bad_plan, why_good_is_better, good_tools, bad_tools, category
- bad_response must be plausible (not obviously wrong)
- good_response must reference real Agentop tools and agents
- Categories: boundary_*, incident_response, red_line, vague_message, multi_step

## Code Style
- Python: ruff-formatted, mypy-clean, pytest for tests
- Rust: clippy-clean, cargo test
- Conventional commits: feat(scope):, fix(scope):, test:, docs:
- TDD: write test first, then implement

## Architecture
- Backend: FastAPI on port 8000
- Frontend: Next.js on port 3007
- LLM: Ollama on port 11434
- Router: C pre-filter → lex-v2 LLM → Python keyword fallback
- Branch rules: NEVER push to main directly. All work on dev.
