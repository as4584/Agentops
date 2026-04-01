# AI Agent Design Patterns

**Domain:** Agent Engineering & Architecture  
**Key Thinkers:** Andrew Ng, Harrison Chase, Andrej Karpathy

## Operating Model

**Humans decide strategy. Agents execute tactics.**

- Humans own strategic direction, escalation, policy
- Agents own repetitive execution, tool invocation, measurement
- Clear human-agent boundary prevents role confusion

## Agent Behavior Contract

Every agent must define:
- **Inputs:** What it accepts
- **Outputs:** What it produces  
- **Side effects:** What it changes (files, DBs, external APIs)
- **Invariants:** What it never violates

## Tool Orchestration

Production agents need **15-20 tools** for real work:
- Safe shell execution (guarded)
- File read/write (with path restrictions)
- HTTP requests (with URL whitelisting)
- Database queries (with ACLs)
- Logging & alerting
- Memory r/w
- External API calls (GitH ub, Slack, etc.)

## Agent Evaluation Patterns

An ops agent should have **14+ evaluation criteria**:
1. ✓ Correctness (does it solve the problem?)
2. ✓ Boundary respect (stays within role)
3. ✓ Governance compliance (follows drift guard rules)
4. ✓ Safety (doesn't invoke unsafe tools)
5. ✓ Memory isolation (no cross-contamination)
6. ✓ Latency (completes in reasonable time)
7. ✓ Cost (doesn't waste tokens/API calls)
... and more domain-specific criteria

## Memory Namespace Isolation

Each agent owns an isolated memory namespace:
- `/memories/agents/{agent_id}/` — agent's private state
- No direct cross-agent memory access
- All inter-agent communication through orchestrator
- Prevents one agent's corruption from spreading

## CRM Contact Lifecycle Pattern

Entities progress through states:
1. **Prospect** — Unknown, unsolicited
2. **Lead** — Engaged, qualified
3. **Customer** — Active, transacting  
4. **Alumni** — Inactive, historical

Each state has associated workflows, data fields, actions.

## Human-Agent Boundaries

- **Humans:** Strategy, escalation, policy, approval
- **Agents:** Intake, processing, routing, measurement
- Unclear boundaries = role confusion & drift

## Orchestrator-Mediated Communication

Agents never call each other directly:
- ❌ Agent A → Agent B (forbidden)
- ✓ Agent A → Orchestrator → Agent B (required)

Benefits:
- Central audit trail
- Prevents circular calls
- Enforces governance

## Key Takeaways

- Explicit behavior contracts prevent accidents
- 15 tools is minimum for real production work
- Humans own strategy; agents own execution
- Memory namespace isolation prevents cascade failures
- Orchestrator mediation enables governance
