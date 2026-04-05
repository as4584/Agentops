# OpenClaw Gateway — Multi-Channel Agent Bridge

> Local-first Zapier alternative | Firewall-protected | lex-v2 routed

## What We Built On

OpenClaw (inspired by [GoClaw.sh](https://goclaw.sh) and NetworkChuck's autonomous agent
network concept) is a Node.js gateway that bridges external messaging channels directly
into Agentop's multi-agent orchestrator. Instead of using Make.com or Zapier to glue
things together, OpenClaw runs locally on port 18789 (loopback-only) and routes incoming
messages through the same lex-v2 router that handles internal requests.

**The key idea**: any Discord message, Telegram command, or Slack webhook becomes an
agent task — routed, executed, and governed by the same DriftGuard invariants as
internal operations.

## Architecture

```
Discord / Telegram / Slack
         │
         ▼
OpenClaw Gateway (localhost:18789)
  ├── Rate Limiter (30 req/min per user)
  ├── Message Size Check (4000 char max)
  ├── OpenClawFirewall
  │    ├── 12 red-line patterns (rm -rf, DROP TABLE, chmod 777, ...)
  │    └── 4 exfil domain blocks (pastebin, transfer.sh, 0x0.st, ...)
  ├── User ban/unban support
  └── POST /openclaw/route
         │
         ▼
Agentop Backend (localhost:8000)
  ├── lex-v2 Router (3B, 94.9% accuracy)
  ├── Target Agent (execution)
  ├── DriftGuard (invariant enforcement)
  └── Response → back to channel
```

## Firewall Rules

### Red-Line Patterns (blocked before routing)

| Pattern | Category |
|---------|----------|
| `rm -rf` | Destructive filesystem |
| `DROP TABLE`, `DELETE FROM` | Destructive database |
| `format c:`, `mkfs` | Disk destruction |
| `git push --force main` | Protected branch |
| `chmod 777` | Permission escalation |
| `curl \| sh`, `wget \| bash` | Remote code execution |
| `:(){:\|:&};:` | Fork bomb |
| `>/dev/sda` | Direct disk write |

### Exfiltration Domains (blocked in URLs)

- `pastebin.com`
- `hastebin.com`
- `transfer.sh`
- `0x0.st`

## How It Connects

### Bridge Implementation

The bridge lives in `backend/orchestrator/openclaw_bridge.py`:

```python
class OpenClawBridge:
    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.firewall = OpenClawFirewall()

    async def route_message(self, channel, user_id, message):
        # 1. Firewall check (red lines + exfil + rate limit)
        self.firewall.check(user_id, message)
        # 2. lex-v2 routing (same as internal)
        agent_id = await self.orchestrator.route(message)
        # 3. Agent execution
        result = await self.orchestrator.dispatch(agent_id, message)
        return result
```

### Routes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/openclaw/route` | POST | Route external message to agent |
| `/openclaw/health` | GET | Gateway health check |
| `/openclaw/ban` | POST | Ban a user |
| `/openclaw/unban` | POST | Unban a user |

## Current Status

| Component | Status |
|-----------|--------|
| OpenClawFirewall | ✅ Active (12 rules, 4 domains) |
| Lex-v2 routing integration | ✅ Working (94.9% eval) |
| Bridge endpoints | ✅ Mounted in server.py |
| Rate limiting | ✅ 30 req/min per user |
| Discord integration | ⏳ 40% — bot connects, channel routing partial |
| Telegram integration | ❌ Not started |
| Slack integration | ❌ Not started |
| Persistent job scheduling | ❌ Planned (Feature 9) |

## Agent Routing

| External Message | Routes To |
|-----------------|-----------|
| "deploy the latest build" | devops_agent |
| "check server health" | monitor_agent |
| "scan repo for secrets" | security_agent |
| "what are today's metrics" | data_agent |
| "restart the worker process" | self_healer_agent |

## Configuration

```bash
# .env
OPENCLAW_ENABLED=true
OPENCLAW_PORT=18789
OPENCLAW_RATE_LIMIT=30        # requests per minute per user
OPENCLAW_MAX_MESSAGE_LEN=4000
```

## What Makes This Different From Zapier

| Feature | Zapier/Make | OpenClaw |
|---------|------------|----------|
| Runs locally | No | Yes (loopback only) |
| Agent routing | No | lex-v2 (3B, 94.9%) |
| Governance | No | DriftGuard invariants |
| Firewall | No | 12 red-line + exfil blocking |
| Cost | $20-100/mo | Free (local) |
| Latency | 500ms-2s | ~800ms (including LLM) |
