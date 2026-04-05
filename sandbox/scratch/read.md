# Agentop — Master Project Context
> Paste this file at the root of your Agentop repo as `README.md`  
> Copilot reads this automatically in every session. Keep it updated.

---

## Who I Am / What This Is
This is **Agentop** — a local-first, governance-driven multi-agent orchestration platform built by Alex Santiago.  
It is NOT a SaaS product. It is the automation backbone that runs client work, builds websites, manages content pipelines, and automates deliverables — all running locally to save tokens.

**My role:** I use Agentop to serve clients. Each client has their own folder under `/clients/`. I am the developer, operator, and product owner.

---

## Stack (Never Guess This)
| Layer | Tech |
|-------|------|
| Backend | FastAPI 0.111+, Python 3.11+, Uvicorn |
| Agent Orchestration | LangGraph 0.2 state machine |
| LLM (default) | Ollama local — llama3 or mistral |
| LLM (fallback) | OpenRouter (cloud, costs tokens — avoid) |
| Database | SQLite — customers.db, scheduler.db |
| Frontend Dashboard | Next.js 14.2, React 18, Mantine UI v8 |
| Real-time | WebSocket (FastAPI native) |
| Tools Extension | MCP Gateway (Docker) |
| One-click launch | `python3 app.py` from repo root |

---

## Local Ports (Always Check These First)
| Service | Port | URL |
|---------|------|-----|
| Backend API | 8000 | http://localhost:8000 |
| Frontend Dashboard | 3007 | http://localhost:3007 |
| Ollama | 11434 | http://localhost:11434 |
| Client sites (dev) | 5500 | http://localhost:5500 |

**Start everything:** `cd /root/studio/testing/Agentop && source .venv/bin/activate && python3 app.py`

---

## Project Structure (Key Paths)
```
Agentop/
├── backend/
│   ├── agents/          # SoulAgent, GSDAgent, GatekeeperAgent, ContentAgent
│   ├── skills/          # Skill registry — each skill has skill.json + SKILL.md
│   │   └── newsletter_weekly_tips/   # Damian's newsletter automation skill
│   ├── orchestrator/    # LangGraph routes ALL messages — agents never call each other directly
│   ├── tools/           # 54KB tool registry + MCP gateway
│   ├── middleware/       # DriftGuard governance enforcement
│   └── database/        # CustomerStore, GSDStore (SQLite)
├── clients/
│   ├── ibds/            # Innovation Development Solutions (Damian) ← ACTIVE
│   └── probodyforlife/  # Pro Body For Life ← ACTIVE
├── output/webgen/       # Generated websites live here
│   └── innovation-development-solutions/  # Damian's static site files + MP4s
├── data/                # Runtime state — newsletter_state.json, agent memory
├── mcp-gateway/         # Docker MCP config — Zapier, Vercel, Google Drive
└── app.py               # ONE command to start everything
```

---

## Governance Rules (DriftGuard — Never Break These)
1. Agents CANNOT call each other directly — all routing goes through LangGraph orchestrator
2. Dashboard is READ-ONLY — only allowed to call `/chat`, `/soul/reflect`, `/soul/goals`
3. Memory namespaces must not overlap between agents
4. ARCHITECTURAL_MODIFY operations require a doc update first
5. Tools are classified: READ_ONLY / STATE_MODIFY / ARCHITECTURAL_MODIFY
6. Drift status must stay GREEN. YELLOW = pending docs. RED = system halted.

---

## Active Agents
| Agent | Role | Memory Namespace |
|-------|------|-----------------|
| SoulAgent | System identity, goals, reflection | soul_core |
| GSDAgent | Goal-State-Delta workflow, scheduling | gsd |
| GatekeeperAgent | Sandbox → production release gates | gatekeeper |
| ContentAgent | Video pipeline, scripts, newsletters, QA | content_* |

---

## Skills System
Skills live in `backend/skills/{skill_name}/`.  
Each skill requires TWO files:
- `skill.json` — metadata, trigger phrases, allowed agents, version
- `SKILL.md` — full instructions, prompt templates, integration flow

**To add a skill:** Create the folder + both files, then verify with:
```bash
cd /root/studio/testing/Agentop && source .venv/bin/activate && python3 -c "
from backend.skills.registry import SkillRegistry
r = SkillRegistry()
s = r.get('your_skill_name')
print('LOADED:', s.skill_id, '| valid:', s.valid, '| enabled:', s.enabled)
"
```

---

---

# CLIENT BRIEFS

---

## CLIENT 1 — Innovation Development Solutions (Damian)
**Website:** https://innovationdevelopmentsolutions.com  
**Repo:** github.com/as4584/damianwebsite  
**Vercel Project:** damianwebsite (team: alexander-santiagos-projects)  
**Framework:** Next.js 14 — changes go in `frontend/` directory  
**Contact:** letsmakebusinessbetter@gmail.com | 201-429-5452  
**Vercel deploy:** Auto-deploys on push to `main` branch

### Who Damian Is
Licensed financial advisor. Multistate entity formation expert.  
Works with first-time founders up to elite enterprises and elite wealth management.  
Real results. No fluff. Results that STICK (always capitalize STICK).

### Open Website Tasks (Priority Order)
| ID | Area | Task | Priority |
|----|------|------|----------|
| T-01 | Homepage | Replace hero tagline → "Innovation turn-key systematic approaches and systems built for scaling + super efficient operation services, custom tailored to meet your business needs in any industry" | HIGH |
| T-02 | Homepage | Add after tagline: "Proven results. We get results that STICK." | HIGH |
| T-03 | Homepage | Replace CTA → "Ready to scale your business with structure, strategy, and support designed for ambitious first-time founders to experienced business firms and professional groups?" | HIGH |
| T-04 | Homepage | Add media logos bar: Forbes, Harvard Business Review, Entrepreneur (Inc.), Bloomberg — grayscale, hover to color | HIGH |
| T-05 | Homepage | Add wealth management callout in elite enterprise section — mention licensed financial advisor | MED |
| T-06 | Services | Entity Formation card — short: "Multistate entity formation including nonprofit facilitation and compliance management" | HIGH |
| T-07 | Services | Entity Formation expanded: "We facilitate the formation and multistate registration of all entities — including nonprofit entities — ensuring adherence to all state-specific legal, tax, and reporting requirements. We make it easy, quick, and understandable." | HIGH |
| T-08 | Contact | Email: letsmakebusinessbetter@gmail.com (keep existing 2nd email) | HIGH |
| T-09 | Contact | Phone: 201-429-5452 | HIGH |
| T-10 | New Page | /starting-a-business — checklist page + email capture (newsletter opt-in disguised as account creation) | HIGH |
| T-11 | New Page | /privacy-policy — Google-compliant, covers email capture, Vercel hosting | HIGH |
| T-12 | New Page | /terms-of-service — Google-compliant, covers consulting + entity formation + wealth mgmt | HIGH |
| T-13 | Video | landing_page.mp4 `<video>` tag must include `playsinline` for iPhone autoplay | MED |

### Starting a Business Page — Exact Content
**Header (bold):** Before Your Initial Consultation  
**Intro:** To make the most of your consultation, we recommend completing a few simple steps before:

1. **Clarify Your Vision** — Identify your business idea and goals, and the problems you aim to solve
2. **Outline Your Needs** — Consider what support you are seeking: funding, structure, branding, or operational systems
3. **Gather Basic Information** — Business name ideas, industry focus, current stage (idea / startup / established)
4. **Create an Account** — Visit our website, create your account, become familiar with our services *(this is an email capture → newsletter list)*
5. **Prepare Questions** — Write down key questions to address efficiently during your consultation

After checklist: show Forbes / HBR / Entrepreneur / Bloomberg logos  
Then: "Schedule a Consultation" CTA button

### Newsletter Skill — Already Built
Skill location: `backend/skills/newsletter_weekly_tips/`  
- Runs on Ollama (local, zero cloud cost)  
- 10-topic rotation tracked in `data/newsletter_state.json`  
- Sends via Zapier MCP webhook → Mailchimp/ConvertKit  
- Weekly cron: Sunday 6pm EST  
- Brand voice: confident, practical, 8th grade reading level, 300-500 words  
- Always ends with results that STICK

### Video Notes
- `landing_page.mp4` = globe/network visualization (5.4MB) — pulled from live site
- iPhone fix: `<video autoplay muted playsinline loop>` — the `playsinline` attribute is required for iOS Safari
- File lives in `frontend/public/landing_page.mp4`

---

## CLIENT 2 — Pro Body For Life
**Folder:** `/clients/probodyforlife/`  
**Status:** Active — video/social media automation pipeline  
**What they want:** Social media manager that promotes videos  
**Pipeline:** Video automation (note: multiple model failures observed — needs stable model selection)  
**Key clips folder:** `clients/probodyforlife/clips/`

### Open Tasks
- Stabilize video generation pipeline — avoid models with high failure rate
- Automate social media posting from approved video clips
- Connect ContentAgent to their posting schedule

---

## MCP Connections (Available Tools)
These MCP servers are connected and available for Agentop to use:
- **Vercel** — deploy, list projects, get deployment status
- **Supabase** — database operations
- **Gmail** — email sending/reading
- **Stripe** — payments
- **GoDaddy** — domain management
- **Zapier** — workflow automation (used for newsletter sending)
- **Crypto.com** — market data

---

## How Agentop Connects Everything (The Big Picture)
```
Client Brief (Google Drive / this README)
        ↓
  GSDAgent parses task list
        ↓
  ContentAgent generates deliverables
  (runs on LOCAL Ollama — zero token cost)
        ↓
  Alex reviews in Agentop dashboard (:3007)
        ↓
  Approved → pushed via MCP (Vercel / Zapier / Gmail)
        ↓
  Scheduler logs completion in customers.db
        ↓
  Next task auto-queued
```

**Goal:** Agentop is not a service. It is a system. A turn-key operation that builds, automates, and scales client work with minimal manual input.

---

## Common Commands
```bash
# Start everything
cd /root/studio/testing/Agentop && source .venv/bin/activate && python3 app.py

# Serve Damian's site locally
cd /root/studio/testing/Agentop/output/webgen/innovation-development-solutions && python3 -m http.server 5500

# Check drift status
curl http://localhost:8000/drift

# Check all agents
curl http://localhost:8000/agents

# Test a skill loaded
python3 -c "from backend.skills.registry import SkillRegistry; r=SkillRegistry(); s=r.get('newsletter_weekly_tips'); print('valid:', s.valid)"

# Pull latest from live site
git -C /root/studio/testing/damianwebsite/damianwebsite pull origin main
```

---

*Last updated: March 2026 | Maintained by Alex Santiago*
