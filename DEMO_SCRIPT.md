# Agentop — Live Demo Script

> **Read-off script** for a ~10-minute walkthrough.
> Estimated times in brackets. Adjust pacing to audience.
> Dashboard: http://localhost:3007 | Backend: http://localhost:8000

---

## Pre-Demo Checklist (run 2 minutes before)

```bash
cd /root/studio/testing/Agentop
source .venv/bin/activate
APIKEY=$(grep -E '^AGENTOP_API_SECRET=' .env | cut -d= -f2-)

# Verify both services are healthy
curl -s http://localhost:8000/health
# Expected: {"status":"healthy","llm_available":true,"drift_status":"GREEN",...}

# Dashboard should be at http://localhost:3007
```

If backend is down:
```bash
python -m backend.port_guard serve backend.server:app --host 127.0.0.1 --port 8000
```

If frontend is down:
```bash
cd frontend && npm run dev > /tmp/frontend.log 2>&1 &
```

---

## Opening [~1 min]

**[Open browser to http://localhost:3007]**

> "This is Agentop — a fully local, production-grade multi-agent system I built from scratch.
> Everything you see runs on this machine. No cloud. No API keys leaking anywhere. No OpenAI bill.
>
> The idea is simple: instead of one big LLM trying to do everything, you have a team of
> specialized agents — each with their own role, memory, and tools — orchestrated by a
> fast router that figures out which agent should handle your request.
>
> Right now we have 12 registered agents, 47 tools, and a 3-tier routing pipeline. Let me show
> you how it works."

---

## Part 1 — The Dashboard [~1.5 min]

**[Walk through the dashboard panels]**

> "The dashboard is a Next.js app on port 3007. It polls the backend every 5 seconds.
> You can see:
> - The agent registry — all 12 agents, their tier, status, and last activity
> - The live event log — every agent action, tool call, and response streams in here in real time
> - The drift guard panel — this is a governance layer that enforces architectural invariants.
>   Right now it's GREEN, meaning no violations detected
> - Soul goals — the soul_core agent maintains active goals for the system across sessions
>
> I'll keep this open so you can watch the events come in as I run commands."

---

## Part 2 — Orchestrator Routing [~2 min]

**[Open a terminal]**

> "The first thing I want to show is the routing pipeline. When a message comes in,
> it passes through three layers:
> one — a C compiled fast router that handles obvious patterns in under a millisecond,
> two — lex-v2, a custom 3B language model I fine-tuned specifically for agent classification,
> three — a Python keyword fallback if the LLM is uncertain.
>
> Watch what happens when I send a vague message with `agent_id: auto`."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"auto","message":"check disk usage on this machine"}' \
  -m 45 | python3 -m json.tool
```

> "Notice the `agent_id` in the response — that's what lex-v2 routed to. It classified
> 'check disk usage' as an `it_agent` task. Let me try something else."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"auto","message":"what were the top AI news stories today?"}' \
  -m 45 | python3 -m json.tool
```

> "That went to `knowledge_agent` or `monitor_agent` — the router correctly identified
> it as an information retrieval task, not a DevOps task. Zero configuration. Just inference."

---

## Part 3 — Soul Core (System Identity) [~1.5 min]

> "Soul Core is the Tier-0 agent — the conscience of the system. It maintains
> the cluster's goals, trust scores, and reflection memory across sessions.
> Every time the system boots, soul_core runs a boot sequence, restores its goals,
> and checks the trust state of all other agents."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"soul_core","message":"What are your current active goals and what is your trust assessment of the system right now?"}' \
  -m 45 | python3 -m json.tool
```

> "Watch the dashboard — you should see a REACT_STEP event fire, then an AGENT_RESPONSE.
> The soul agent reads its own memory namespace, checks the goal store, and gives you a
> grounded answer based on its actual persisted state — not a hallucinated reply.
>
> This is the key architectural difference from a plain chatbot: agents have memory,
> and that memory persists across reboots."

---

## Part 4 — DevOps Agent (Real Tool Calls) [~1.5 min]

> "Now let's look at an agent that actually does real work. The devops agent has access
> to `git_ops`, `safe_shell`, `health_check`, and `file_reader`. Watch it use those tools."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"devops_agent","message":"show me the last 5 git commits and the current branch"}' \
  -m 45 | python3 -m json.tool
```

> "The agent called `git_ops` under the hood — a whitelisted wrapper that only allows
> safe read-only git subcommands. No `git push`, no `git reset --hard`. The tool layer
> enforces the policy, not the LLM prompt.
>
> Let me show one more — the security agent."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"security_agent","message":"scan the backend directory for any hardcoded secrets or credentials"}' \
  -m 45 | python3 -m json.tool
```

> "The secret_scanner tool runs 8 regex patterns — API keys, tokens, passwords, private keys.
> It came back clean. That's because all secrets are in `.env`, which is gitignored."

---

## Part 5 — WebGen Pipeline [~2.5 min]

> "This is the flagship demo. Agentop has a full website generation pipeline:
> six specialized agents — SitePlanner, PageGenerator, SEO, AEO, QA, and a template learner.
> A single prompt kicks off a multi-agent chain that plans, builds, and validates a complete website.
>
> Let me generate one now."

```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"auto","message":"Build a landing page for a local AI consulting firm called NeuraStack. Include a hero section, a services section with three offerings, and a contact form. Modern dark theme."}' \
  -m 90 | python3 -m json.tool
```

> "While that's running — watch the event log in the dashboard. You'll see the orchestrator
> hand off to the WebGen pipeline. Each agent in the chain appends its output before
> passing to the next stage.
>
> The output is a complete HTML/CSS page — not a template, not a theme, not a WordPress install.
> Generated from scratch, in-context, by a local 4B parameter model.
>
> [When response arrives:]
> There it is. You can see the planner laid out the sections, the page generator wrote the markup,
> and the SEO agent added meta tags. All locally, in under a minute."

**[Optional: open the output file in browser if the pipeline saves it]**

---

## Part 6 — Architecture Call-Out [~1 min]

**[Back to dashboard or slide if you have one]**

> "Before I wrap up — a few engineering choices I'm particularly proud of.
>
> First: the 3-tier router. The C pre-filter handles pattern matching at native speed — that's
> a compiled `.so` loaded via ctypes. lex-v2 handles ambiguous cases with a fine-tuned model.
> The Python fallback catches anything that slips through. Total routing overhead: under 2ms.
>
> Second: the embedding fix we shipped literally this session. RAG retrieval was causing
> 180-second timeouts because the wrong LLM model was being used as the embed client.
> qwen3:4b is a generation model — not an embedding model. Every embed call was timing out,
> blocking the Ollama queue, and starving the chat_with_schema call.
> The fix was 4 lines in context_assembler.py. Response time went from 180s timeout to 8 seconds.
>
> Third: zero cloud dependency. Every inference call goes to localhost:11434 — that's Ollama.
> If the internet goes down, this system keeps running."

---

## Part 7 — Close [~30 sec]

> "To summarize:
> - 12 agents with isolated memory namespaces
> - 47 tools — 13 native, 26 via MCP Docker bridge, 8 browser
> - 3-tier routing pipeline with a custom fine-tuned router
> - Full WebGen and content creation pipelines
> - 1,165 tests at 63% coverage, zero CVEs, CI-gated
> - Everything runs on a single machine with a 3.5GB model
>
> The codebase is at `/root/studio/testing/Agentop`.
> Questions?"

---

## Backup Prompts (if something fails)

If WebGen is slow, pivot to this shorter version:
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"auto","message":"Create a simple pricing page for a SaaS tool called FlowCore with Free, Pro, and Enterprise tiers"}' \
  -m 60 | python3 -m json.tool
```

If soul_core is slow, pivot to monitor_agent:
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"monitor_agent","message":"give me a health summary of all running services"}' \
  -m 45 | python3 -m json.tool
```

If routing demo needs a stronger example of classification:
```bash
curl -s -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APIKEY" \
  -d '{"agent_id":"auto","message":"review the lex_router.py file for any code quality issues"}' \
  -m 45 | python3 -m json.tool
# Expected route: code_review_agent
```

---

## Key Numbers to Drop Naturally

| Stat | Value |
|------|-------|
| Agents | 12 core + 9 content + 6 webgen |
| Tools | 47 (13 native + 26 MCP + 8 browser) |
| Tests | 1,165+ passed, 63% coverage |
| Router latency | < 2ms (C pre-filter) |
| Chat latency | ~8-9s (qwen3:4b, after RAG fix) |
| Training data | 186 JSONL files, 5,624 examples |
| CVEs | 0 |
| Cloud dependencies | 0 |
| Model size | 3.5GB (qwen3:4b) |
| Lines of code | 56,000+ |
