---
agent: agent
description: "TDD Workflow — test-driven development for Python backend and Playwright E2E. Write tests first, 80% coverage minimum."
tools: [search/codebase]
---

# Test-Driven Development Workflow

Enforce TDD across all Agentop development: Python backend (pytest), and E2E (Playwright). Always write the failing test before touching implementation code.

## When to Activate

- Writing any new feature, endpoint, or agent behaviour
- Fixing a bug (reproduce first with a failing test)
- Refactoring existing code
- Adding a new webgen pipeline stage

## Core Rules

1. **Tests BEFORE code** — red → green → refactor, no exceptions
2. **80% coverage minimum** — measured per file, enforced on PRs
3. **100% coverage on critical paths** — auth, payment, data persistence
4. **Tests are documentation** — test names describe behaviour

## TDD Cycle

### Step 1 — Write User Story

```
As a [role], I want to [action], so that [benefit].

Example:
As the SitePlannerAgent, I want to resolve the correct color palette
for a given domain, so that PageGeneratorAgent produces on-brand HTML.
```

### Step 2 — Write Failing Tests

Write all test cases before any implementation:

```python
# backend/tests/test_site_planner.py
import pytest
from backend.agents.site_planner import SitePlannerAgent

def test_resolves_palette_for_saas_domain():
    agent = SitePlannerAgent()
    result = agent.resolve_palette("fintech")
    assert result["primary"] is not None
    assert result["accent"] is not None

def test_returns_default_palette_for_unknown_domain():
    agent = SitePlannerAgent()
    result = agent.resolve_palette("unknown_xyz_domain")
    assert result == SitePlannerAgent.DEFAULT_PALETTE

def test_raises_on_empty_domain():
    agent = SitePlannerAgent()
    with pytest.raises(ValueError, match="domain cannot be empty"):
        agent.resolve_palette("")
```

### Step 3 — Confirm Tests Fail

```bash
cd /root/studio/testing/Agentop
python -m pytest backend/tests/test_site_planner.py -v 2>&1 | tail -20
# Should show FAILED — that's correct at this stage
```

### Step 4 — Implement Minimal Code

Write the smallest implementation that makes tests pass. No speculative features.

### Step 5 — Confirm Tests Pass

```bash
python -m pytest backend/tests/test_site_planner.py -v 2>&1 | tail -20
# All PASSED
```

### Step 6 — Refactor

Improve naming, remove duplication, extract helpers. Re-run tests after each change.

### Step 7 — Check Coverage

```bash
python -m pytest backend/tests/ --cov=backend --cov-report=term-missing 2>&1 | tail -30
# Target: 80%+ overall, 100% on critical paths
```

## pytest Patterns for Agentop

### Fixtures

```python
# conftest.py
import pytest
from httpx import AsyncClient
from backend.server import app

@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as c:
        yield c

@pytest.fixture
def sample_client_brief():
    return {
        "domain": "saas",
        "brand_name": "TestCo",
        "primary_color": "#2563EB",
        "tone": "professional"
    }
```

### Async Tests (FastAPI)

```python
import pytest

@pytest.mark.asyncio
async def test_webgen_endpoint(client, sample_client_brief):
    response = await client.post("/api/webgen/generate", json=sample_client_brief)
    assert response.status_code == 200
    data = response.json()
    assert "html" in data
    assert len(data["html"]) > 100
```

### Parametrize for Edge Cases

```python
@pytest.mark.parametrize("domain,expected_tone", [
    ("fintech", "professional"),
    ("saas", "modern"),
    ("healthcare", "trustworthy"),
    ("creative", "bold"),
])
def test_domain_to_tone_mapping(domain, expected_tone):
    agent = SitePlannerAgent()
    assert agent.get_tone(domain) == expected_tone
```

### Mocking LLM Calls

```python
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_agent_calls_llm_once(sample_client_brief):
    with patch("backend.llm.client.complete", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = {"content": "<html>test</html>"}
        agent = PageGeneratorAgent()
        result = await agent.generate(sample_client_brief)
        mock_llm.assert_called_once()
        assert "<html>" in result
```

## Playwright E2E Patterns

For frontend tests in `frontend/tests/`:

```typescript
import { test, expect } from '@playwright/test'

test.describe('Webgen output preview', () => {
  test('renders generated site HTML', async ({ page }) => {
    await page.goto('/preview/test-job-id')
    await page.waitForLoadState('networkidle')
    await expect(page.locator('[data-testid="preview-frame"]')).toBeVisible()
  })

  test('shows error state on invalid job ID', async ({ page }) => {
    await page.goto('/preview/invalid-id-xyz')
    await expect(page.locator('[data-testid="error-message"]')).toBeVisible()
  })
})
```

**Always use `waitForResponse` over `waitForTimeout`:**
```typescript
// ❌ BAD
await page.waitForTimeout(3000)

// ✅ GOOD
await page.waitForResponse(r => r.url().includes('/api/webgen'))
```

## Run Commands

```bash
# All backend tests
python -m pytest backend/tests/ -v

# Specific test file
python -m pytest backend/tests/test_agents.py -v -k "test_planner"

# With coverage
python -m pytest backend/tests/ --cov=backend --cov-report=term-missing

# E2E (requires frontend dev server running)
cd frontend && npx playwright test

# E2E headed (debug mode)
cd frontend && npx playwright test --headed --debug
```

## Bug Fix Protocol

When fixing a bug:
1. Write a test that reproduces the bug (it should fail)
2. Fix the bug
3. Confirm test now passes
4. Confirm no other tests broke

This ensures the bug can never silently reappear.
