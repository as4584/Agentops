---
agent: agent
description: "E2E Testing — Playwright Page Object Model, stable selectors, CI config, flaky test strategies for Agentop's frontend/tests/."
tools: [search/codebase]
---

# E2E Testing Patterns

Playwright standards for `frontend/tests/`. Focuses on stable, maintainable tests that don't flake in CI.

## When to Activate

- Writing new Playwright tests
- Debugging flaky tests in CI
- Adding a new user-visible feature
- Reviewing test coverage of critical flows

## File Organisation

```
frontend/tests/
├── e2e/
│   ├── webgen/
│   │   ├── generate.spec.ts    # Happy path generation flow
│   │   └── errors.spec.ts      # Error states and edge cases
│   ├── preview/
│   │   └── preview.spec.ts     # Site preview rendering
│   └── api/
│       └── endpoints.spec.ts   # API contract tests via browser
├── pages/                      # Page Object Model classes
│   ├── GeneratePage.ts
│   └── PreviewPage.ts
├── fixtures/
│   └── data.ts                 # Test data constants
└── playwright.config.ts
```

## Page Object Model (POM)

Never scatter `page.locator(...)` calls across specs — centralise in a Page class:

```typescript
import { Page, Locator } from '@playwright/test'

export class GeneratePage {
  readonly page: Page
  readonly brandNameInput: Locator
  readonly domainSelect: Locator
  readonly generateButton: Locator
  readonly resultPreview: Locator
  readonly errorMessage: Locator

  constructor(page: Page) {
    this.page = page
    // Always prefer data-testid — CSS classes and text change; test IDs are stable
    this.brandNameInput = page.locator('[data-testid="brand-name-input"]')
    this.domainSelect = page.locator('[data-testid="domain-select"]')
    this.generateButton = page.locator('[data-testid="generate-btn"]')
    this.resultPreview = page.locator('[data-testid="result-preview"]')
    this.errorMessage = page.locator('[data-testid="error-message"]')
  }

  async goto() {
    await this.page.goto('/generate')
    await this.page.waitForLoadState('networkidle')
  }

  async fillBrief(brand: string, domain: string) {
    await this.brandNameInput.fill(brand)
    await this.domainSelect.selectOption(domain)
  }

  async generate() {
    await this.generateButton.click()
    // Wait for the API call, not a fixed timeout
    await this.page.waitForResponse(r => r.url().includes('/api/webgen/generate'))
  }
}
```

## Test Structure

```typescript
import { test, expect } from '@playwright/test'
import { GeneratePage } from '../pages/GeneratePage'

test.describe('Webgen generation flow', () => {
  let generatePage: GeneratePage

  test.beforeEach(async ({ page }) => {
    generatePage = new GeneratePage(page)
    await generatePage.goto()
  })

  test('generates HTML for valid brief', async ({ page }) => {
    await generatePage.fillBrief('TestCo', 'saas')
    await generatePage.generate()

    await expect(generatePage.resultPreview).toBeVisible({ timeout: 15_000 })
    await page.screenshot({ path: 'reports/playwright/generate-success.png' })
  })

  test('shows validation error for empty brand name', async () => {
    await generatePage.generate()  // submit with empty name
    await expect(generatePage.errorMessage).toContainText(/brand name/i)
  })

  test('handles API timeout gracefully', async ({ page }) => {
    // Intercept and delay the API response
    await page.route('**/api/webgen/generate', async route => {
      await new Promise(r => setTimeout(r, 35_000))  // exceed timeout
      await route.continue()
    })
    await generatePage.fillBrief('TestCo', 'saas')
    await generatePage.generate()
    await expect(generatePage.errorMessage).toBeVisible({ timeout: 40_000 })
  })
})
```

## Playwright Config

```typescript
// frontend/playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ['html', { outputFolder: '../reports/playwright' }],
    ['junit', { outputFile: '../reports/playwright/results.xml' }],
  ],
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile-chrome', use: { ...devices['Pixel 5'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:3000',
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
})
```

## Flaky Test Patterns & Fixes

### Rule: Never Use `waitForTimeout`

```typescript
// ❌ BAD — causes flakiness by guessing timing
await page.waitForTimeout(3000)

// ✅ GOOD — wait for the actual condition
await page.waitForResponse(r => r.url().includes('/api/'))
await page.waitForLoadState('networkidle')
await expect(locator).toBeVisible()
```

### Race Condition Fix

```typescript
// ❌ BAD — element might not be ready
await page.click('[data-testid="submit"]')

// ✅ GOOD — Playwright's auto-waiting locators handle it
await page.locator('[data-testid="submit"]').click()
```

### Diagnosing Flakiness

```bash
# Repeat the test 10 times to surface flakiness
cd frontend
npx playwright test tests/e2e/webgen/generate.spec.ts --repeat-each=10

# Run with retries to see failure patterns
npx playwright test tests/e2e/webgen/generate.spec.ts --retries=3
```

### Quarantine Unstable Tests

Use `test.fixme` to track quarantined tests — never just comment them out:

```typescript
test.fixme('intermittent: preview loads on slow connection', async ({ page }) => {
  // Tracked in: https://github.com/org/repo/issues/123
  // Remove fixme when the network interception issue is resolved
})
```

## Running Tests

```bash
# All E2E tests (requires dev server on :3000)
cd /root/studio/testing/Agentop/frontend
npx playwright test

# Specific file
npx playwright test tests/e2e/webgen/generate.spec.ts

# Headed (see the browser)
npx playwright test --headed

# Debug mode (step through)
npx playwright test --debug

# Generate report
npx playwright show-report ../reports/playwright
```

## Selector Priority

Use selectors in this order (most stable → least stable):

1. `[data-testid="..."]` — purpose-built for tests, never changes with styling
2. ARIA roles — `page.getByRole('button', { name: /generate/i })`
3. Labels — `page.getByLabel('Brand name')`
4. Text — `page.getByText('Generate')`
5. ❌ CSS classes — avoid; break when design changes
6. ❌ XPath — avoid; brittle and unreadable

## Adding `data-testid` to Components

When writing a new feature that needs E2E coverage, add test IDs as you build:

```tsx
// ✅ Good — test ID is added immediately with the component
<button data-testid="generate-btn" onClick={handleGenerate}>
  Generate
</button>

<div data-testid="result-preview" className="...">
  {html && <iframe srcDoc={html} />}
</div>
```
