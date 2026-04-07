/**
 * Live E2E smoke tests — runs against the real stack on port 3007 + 8000.
 *
 * DOES NOT mock the backend. Every failure here is a real regression.
 * Failures are appended to docs/KNOWN_ISSUES.md so they can never be silently
 * ignored again.
 *
 * Run with:  cd frontend && npx playwright test tests/live_smoke.spec.ts
 * (App must already be running on 3007 / 8000)
 */
import * as fs from 'fs';
import * as path from 'path';
import { expect, test } from '@playwright/test';

// ---------------------------------------------------------------------------
// Regression logger — appends failed assertions to KNOWN_ISSUES.md
// ---------------------------------------------------------------------------
function logRegression(testName: string, error: unknown): void {
  const issuesPath = path.resolve(__dirname, '../../docs/KNOWN_ISSUES.md');
  const timestamp = new Date().toISOString();
  const msg = error instanceof Error ? error.message : String(error);
  const entry = `\n## [AUTO] ${timestamp}\n**Test:** \`${testName}\`\n**Error:** ${msg}\n`;
  try {
    fs.appendFileSync(issuesPath, entry);
  } catch {
    // If the file doesn't exist yet, create it
    fs.writeFileSync(issuesPath, `# Known Issues (auto-logged by Playwright)\n${entry}`);
  }
}

// Wrap test so failures always get logged
function live(name: string, fn: (fixtures: { page: import('@playwright/test').Page }) => Promise<void>) {
  test(name, async ({ page }) => {
    try {
      await fn({ page });
    } catch (e) {
      logRegression(name, e);
      throw e;
    }
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

live('dashboard loads and shows Connected status', async ({ page }) => {
  await page.goto('http://localhost:3007');
  await expect(page).toHaveTitle(/Agentop/i);
  // Connected indicator turns green once /health responds
  const connected = page.locator('text=Connected').first();
  await expect(connected).toBeVisible({ timeout: 15_000 });
});

live('backend health is green', async ({ page }) => {
  const res = await page.request.get('http://localhost:8000/health');
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.status).toBe('healthy');
  expect(body.llm_available).toBe(true);
});

live('drift status is GREEN', async ({ page }) => {
  const secret = (process.env.NEXT_PUBLIC_AGENTOP_API_SECRET || '').trim();
  const res = await page.request.get('http://localhost:8000/drift', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(body.status).not.toBe('RED');
});

live('SSE stream/activity connects without auth error', async ({ page }) => {
  // page.request.get hangs on streaming body. Race with a 2s timeout:
  // 401 resolves instantly; 200 SSE streams forever → timeout = connection established.
  let latestStatus: number | null = null;
  const requestDone = page.request.get('http://localhost:8000/stream/activity').then(r => {
    latestStatus = r.status();
  });
  await Promise.race([requestDone, page.waitForTimeout(2000)]);
  if (latestStatus !== null) {
    // Got a full response — must not be 401
    expect(latestStatus).not.toBe(401);
  }
  // latestStatus === null means still streaming → 200 connection established → pass
});

live('live activity shows Connected not stuck at Connecting', async ({ page }) => {
  await page.goto('http://localhost:3007');
  // Wait for dashboard to fully load
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
  // Navigate to dashboard view (it may already be there)
  const liveActivity = page.locator('text=Live Activity');
  if (await liveActivity.isVisible()) {
    // Should show "Waiting for agent activity" not "Connecting…"
    const connecting = page.locator('text=Connecting…');
    await expect(connecting).not.toBeVisible({ timeout: 5_000 });
  }
});

live('Quick Build form accepts input', async ({ page }) => {
  await page.goto('http://localhost:3007');
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
  const nameInput = page.getByPlaceholder('Business name…');
  await expect(nameInput).toBeVisible();
  await nameInput.fill('Test Business');
  await expect(nameInput).toHaveValue('Test Business');
});

live('agents list loads at least one agent', async ({ page }) => {
  await page.goto('http://localhost:3007');
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
  // Nav to Agents view
  await page.locator('text=Agents').first().click();
  // Agent names render with underscores replaced by spaces e.g. "soul core"
  // Also look for the "N registered" header that appears once agents load
  const registeredText = page.locator('text=/\\d+ registered/');
  const soulCore = page.locator('text=soul core').first();
  await expect(registeredText.or(soulCore).first()).toBeVisible({ timeout: 10_000 });
});

live('/preview/ static mount serves generated HTML', async ({ page }) => {
  // Check if any site has been generated
  const secret = (process.env.NEXT_PUBLIC_AGENTOP_API_SECRET || '').trim();
  const res = await page.request.get('http://localhost:8000/api/webgen/projects', {
    headers: { Authorization: `Bearer ${secret}` },
  });
  if (res.status() !== 200) return; // skip if endpoint unavailable
  const body = await res.json();
  if (!body.projects?.length) return; // skip if no projects yet

  const slug = body.projects[0].business_name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
  const previewRes = await page.request.get(`http://localhost:8000/preview/${slug}/index.html`);
  expect(previewRes.status()).toBe(200);
  const html = await previewRes.text();
  expect(html).toContain('<!DOCTYPE html>');
});

live('no JS console errors on load', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  await page.goto('http://localhost:3007');
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
  // Filter out known benign errors
  const realErrors = errors.filter(e =>
    !e.includes('EventSource') &&
    !e.includes('net::ERR_') &&
    !e.includes('favicon') &&
    !e.includes('CORS') &&
    !e.includes('Access-Control') &&
    !e.includes('404 (Not Found)')  // favicon/asset 404s
  );
  if (realErrors.length > 0) {
    logRegression('no JS console errors on load', new Error(realErrors.join('\n')));
  }
  expect(realErrors).toHaveLength(0);
});

live('page has no horizontal overflow at 1280px', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto('http://localhost:3007');
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth
  );
  expect(overflow).toBeFalsy();
});
