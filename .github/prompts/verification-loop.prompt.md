---
agent: agent
description: "Verification Loop — run quality gates after any significant code change or before PR"
tools: [search/codebase]
---

# Verification Loop

Run this skill after completing a feature, significant refactor, or before creating a PR. Produces a structured PASS/FAIL report across build, types, lint, tests, security, and diff.

## When to Invoke

- After completing a feature or bug fix
- Before creating a PR
- After any refactor touching multiple files
- When output quality feels off after a long session

## Phase 1 — Build

```bash
# Python backend
cd /root/studio/testing/Agentop
python -m py_compile backend/**/*.py 2>&1 | head -20

# Frontend
cd frontend && npm run build 2>&1 | tail -30
```

If build fails, **STOP** — do not run remaining phases.

## Phase 2 — Type Check

```bash
# Python (pyright configured in pyrightconfig.json)
cd /root/studio/testing/Agentop
pyright backend/ 2>&1 | head -40

# TypeScript frontend
cd frontend && npx tsc --noEmit 2>&1 | head -40
```

Report all errors. Fix critical ones before continuing.

## Phase 3 — Lint

```bash
# Python
cd /root/studio/testing/Agentop
ruff check backend/ 2>&1 | head -30

# Frontend
cd frontend && npm run lint 2>&1 | head -30
```

## Phase 4 — Tests

```bash
# Python backend tests
cd /root/studio/testing/Agentop
python -m pytest backend/tests/ -v --tb=short 2>&1 | tail -50

# Frontend unit tests (if any)
cd frontend && npm test -- --passWithNoTests 2>&1 | tail -30

# E2E (Playwright) — only run if directly relevant to changes
cd frontend && npx playwright test --reporter=list 2>&1 | tail -40
```

Coverage target: **80% minimum** for any file you wrote or modified.

```bash
python -m pytest backend/tests/ --cov=backend --cov-report=term-missing 2>&1 | tail -30
```

## Phase 5 — Security Scan

```bash
cd /root/studio/testing/Agentop

# Hardcoded secrets
grep -rn "sk-\|api_key\s*=\s*['\"]" --include="*.py" --include="*.ts" --include="*.js" backend/ frontend/src/ 2>/dev/null | grep -v ".env" | grep -v "os.environ" | grep -v "process.env" | head -10

# Console.log left in frontend
grep -rn "console\.log" --include="*.ts" --include="*.tsx" frontend/src/ 2>/dev/null | head -10

# TODO/FIXME markers that might hide incomplete security logic
grep -rn "TODO.*auth\|FIXME.*auth\|TODO.*permission\|TODO.*secret" --include="*.py" backend/ 2>/dev/null | head -10
```

## Phase 6 — Diff Review

```bash
git diff --stat HEAD
git diff HEAD --name-only
```

For each changed file, check:
- No unintended side effects
- Error handling present at boundaries
- No new SQL string concatenation (use parameterized queries only)
- No new hardcoded values that belong in config/.env

## Output Format

After all phases, produce this report:

```
VERIFICATION REPORT
===================

Build:     [PASS/FAIL]
Types:     [PASS/FAIL] (N errors)
Lint:      [PASS/FAIL] (N warnings)
Tests:     [PASS/FAIL] (N/M passed, X% coverage)
Security:  [PASS/FAIL] (N issues)
Diff:      [N files changed]

Overall:   [READY / NOT READY] for PR

Issues to Fix:
1. ...
2. ...

Skipped:
- <reason if any phase was skipped>
```

## Continuous Use

For long sessions, invoke after each major milestone — don't wait for PR time. The earlier you catch a type error, the cheaper it is to fix.

Set a mental checkpoint at:
- After completing a new agent or skill
- After adding a new API route
- After modifying `backend/database/` or any model
- Before running Playwright tests against a changed UI

---

## Loop Escape Rule

**Do NOT loop more than 3 attempts on fixing the same linter error, type error, or test failure in the same file.**

After the third failed attempt on an identical error:
1. **Stop the loop immediately** — do not make a fourth edit
2. **Escalate to the user** with this structure:

```
STUCK LOOP REPORT
=================
File:     <path>
Error:    <exact error message>
Attempts: 3
Tried:    <brief summary of each approach>
Hypothesis: <what you think the root cause is>
Needs:    <what you need from the user to unblock — e.g., clarification, a dependency, a design decision>
```

Looping on the same error with superficially different edits wastes tokens and degrades output quality. A clear escalation is always better than a 4th guess.

---

## API Contract Verification

After creating a new API route, **test it immediately** — in the same task, before moving on.

Run at minimum 3 cases in parallel:
1. **Happy path** — valid input, expected 2xx response
2. **Invalid input** — malformed body or missing required fields, expect 4xx
3. **Auth boundary** — unauthenticated request, expect 401/403

```bash
# Example for a newly created POST /api/webgen/generate route
cd /root/studio/testing/Agentop

# Happy path
curl -s -X POST http://localhost:8000/api/webgen/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TEST_TOKEN" \
  -d '{"business_name":"TestCo","business_type":"saas"}' | jq .status

# Invalid input
curl -s -X POST http://localhost:8000/api/webgen/generate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TEST_TOKEN" \
  -d '{}' | jq .status  # expect 422

# Auth boundary
curl -s -X POST http://localhost:8000/api/webgen/generate \
  -H "Content-Type: application/json" \
  -d '{"business_name":"TestCo","business_type":"saas"}' | jq .status  # expect 401
```

This is not TDD (that's in `/tdd-workflow`) — it is **post-creation contract verification**: confirming the route behaves as documented before it becomes a dependency.
