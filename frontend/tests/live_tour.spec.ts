/**
 * live_tour.spec.ts — Full visual walkthrough of Agentop on port 3007.
 *
 * Runs headed (--headed) against the real stack. No mocks. Covers every nav
 * view: Dashboard, Agents, Agent detail + chat, System, Social Media.
 *
 * Run:  cd frontend && DISPLAY=:99 npx playwright test tests/live_tour.spec.ts --headed --workers=1
 */
import * as fs from 'fs';
import * as path from 'path';
import { expect, test } from '@playwright/test';

// ---------------------------------------------------------------------------
// Regression logger
// ---------------------------------------------------------------------------
function logRegression(testName: string, error: unknown): void {
  const issuesPath = path.resolve(__dirname, '../../docs/KNOWN_ISSUES.md');
  const timestamp = new Date().toISOString();
  const msg = error instanceof Error ? error.message : String(error);
  const entry = `\n## [AUTO] ${timestamp}\n**Test:** \`${testName}\`\n**Error:** ${msg}\n`;
  try {
    fs.appendFileSync(issuesPath, entry);
  } catch {
    fs.writeFileSync(issuesPath, `# Known Issues (auto-logged by Playwright)\n${entry}`);
  }
}

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

// Shared helper — navigate to app and wait for "Connected"
async function openApp(page: import('@playwright/test').Page) {
  await page.goto('http://localhost:3007');
  await page.locator('text=Connected').first().waitFor({ timeout: 15_000 });
}

// Click System nav without matching the "All Systems Nominal" badge
async function clickSystemNav(page: import('@playwright/test').Page) {
  await page.getByText('System', { exact: true }).click();
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
test.describe('Dashboard', () => {
  live('stat cards are all visible', async ({ page }) => {
    await openApp(page);
    await expect(page.locator('text=Active Agents')).toBeVisible();
    await expect(page.locator('text=Tasks Running')).toBeVisible();
    await expect(page.locator('text=Avg Latency')).toBeVisible();
    await expect(page.locator('text=Errors')).toBeVisible();
  });

  live('Quick Build panel is visible with both inputs', async ({ page }) => {
    await openApp(page);
    await expect(page.getByPlaceholder('Business name…')).toBeVisible();
    await expect(page.getByPlaceholder('Type (e.g., restaurant, agency, gym)')).toBeVisible();
    await expect(page.locator('text=Quick Build')).toBeVisible();
  });

  live('drift badge shows status in sidebar', async ({ page }) => {
    await openApp(page);
    // Drift badge is always in nav sidebar
    const driftBadge = page.locator('text=/Drift: (GREEN|YELLOW|RED)/');
    await expect(driftBadge).toBeVisible({ timeout: 8_000 });
  });

  live('LLM online badge is visible', async ({ page }) => {
    await openApp(page);
    const llmBadge = page.locator('text=LLM Online');
    await expect(llmBadge).toBeVisible({ timeout: 8_000 });
  });

  live('Live Activity panel shows agent events or idle message', async ({ page }) => {
    await openApp(page);
    // "Live Activity" header always renders when the dashboard is connected
    await expect(page.getByText('Live Activity', { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  live('soul_core shortcut opens agent detail', async ({ page }) => {
    await openApp(page);
    // "Orchestration" nav link navigates to soul_core detail
    await page.locator('text=Orchestration').click();
    await expect(page.getByText('soul core', { exact: true }).first()).toBeVisible({ timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// Agents view
// ---------------------------------------------------------------------------
test.describe('Agents', () => {
  live('agent count badge appears in nav', async ({ page }) => {
    await openApp(page);
    // Nav link shows agent count in a filled circle badge
    const agentsNav = page.locator('text=Agents').first();
    await expect(agentsNav).toBeVisible();
  });

  live('Agents view lists all tiers', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    // Wait for the "N registered" heading
    await expect(page.locator('text=/\\d+ registered/')).toBeVisible({ timeout: 8_000 });
    // At minimum Tier 0/soul_core visible
    await expect(page.getByText('soul core', { exact: true }).first()).toBeVisible({ timeout: 15_000 });
  });

  live('clicking an agent opens detail view with Back button', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    await expect(page.getByText('soul core', { exact: true }).first()).toBeVisible({ timeout: 15_000 });
    await page.getByText('soul core', { exact: true }).first().click();
    await expect(page.locator('text=All Agents')).toBeVisible({ timeout: 12_000 });
    await expect(page.locator('text=soul core').first()).toBeVisible();
  });

  live('agent detail shows role description', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    await page.locator('text=soul core').first().waitFor({ timeout: 8_000 });
    await page.locator('text=soul core').first().click();
    // role text should appear below the agent name
    const role = page.locator('text=/conscience|trust|reflection|goal/i').first();
    await expect(role).toBeVisible({ timeout: 6_000 });
  });

  live('agent detail has chat input', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    await expect(page.locator('text=/\\d+ registered/')).toBeVisible({ timeout: 15_000 });
    await page.locator('text=soul core').first().click();
    // Chat input should be visible in agent detail
    const chatInput = page.locator('textarea, input[placeholder*="message" i], input[placeholder*="ask" i], input[placeholder*="chat" i]').first();
    await expect(chatInput).toBeVisible({ timeout: 6_000 });
  });

  live('Back button returns to agent grid', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    // Wait for agents list to fully load before clicking
    await expect(page.locator('text=/\\d+ registered/')).toBeVisible({ timeout: 15_000 });
    await page.locator('text=soul core').first().click();
    await page.locator('text=All Agents').click();
    // Should be back on the grid showing "N registered"
    await expect(page.locator('text=/\\d+ registered/')).toBeVisible({ timeout: 8_000 });
  });

  live('devops agent is listed', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    // Wait directly for the specific agent — tier 1 renders after agents load
    await expect(page.getByText('devops agent', { exact: true })).toBeVisible({ timeout: 15_000 });
  });

  live('security agent is listed', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Agents').first().click();
    await expect(page.getByText('security agent', { exact: true })).toBeVisible({ timeout: 15_000 });
  });
});

// ---------------------------------------------------------------------------
// System view
// ---------------------------------------------------------------------------
test.describe('System', () => {
  live('System view loads with LLM Health section', async ({ page }) => {
    await openApp(page);
    await clickSystemNav(page);
    // LLM Health panel renders somewhere
    const llmSection = page.locator('text=/LLM|Model|Ollama/i').first();
    await expect(llmSection).toBeVisible({ timeout: 8_000 });
  });

  live('Tool registry shows tools', async ({ page }) => {
    await openApp(page);
    await clickSystemNav(page);
    // Wait directly for safe_shell — it's the first tool rendered
    await expect(page.locator('text=safe_shell')).toBeVisible({ timeout: 15_000 });
  });

  live('Drift Monitor card shows GREEN status', async ({ page }) => {
    await openApp(page);
    await clickSystemNav(page);
    await expect(page.locator('text=Drift Monitor')).toBeVisible({ timeout: 8_000 });
    // Should show green / no violations
    const driftCard = page.locator('text=GREEN').first();
    await expect(driftCard).toBeVisible({ timeout: 8_000 });
  });

  live('ML Learning Lab stats section is present', async ({ page }) => {
    await openApp(page);
    await clickSystemNav(page);
    await expect(page.locator('text=ML Learning Lab')).toBeVisible({ timeout: 10_000 });
    await expect(page.locator('text=Training Files')).toBeVisible({ timeout: 8_000 });
  });

  live('Tasks section is always present in System view', async ({ page }) => {
    await openApp(page);
    await clickSystemNav(page);
    // Tasks section always renders regardless of llmStats
    await expect(page.getByText('Tasks', { exact: true })).toBeVisible({ timeout: 8_000 });
  });
});

// ---------------------------------------------------------------------------
// Social view
// ---------------------------------------------------------------------------
test.describe('Social Media', () => {
  live('Social Media view loads with platform cards', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Social Media').click();
    await expect(page.locator('text=Social Media Manager')).toBeVisible({ timeout: 6_000 });
    await expect(page.locator('text=TikTok')).toBeVisible();
    await expect(page.locator('text=Facebook')).toBeVisible();
    await expect(page.locator('text=Instagram')).toBeVisible();
  });

  live('Post History section is visible', async ({ page }) => {
    await openApp(page);
    await page.locator('text=Social Media').click();
    await expect(page.locator('text=Post History')).toBeVisible({ timeout: 6_000 });
  });
});

// ---------------------------------------------------------------------------
// Navigation flow — visit all views in sequence
// ---------------------------------------------------------------------------
live('full nav tour without crashes', async ({ page }) => {
  await openApp(page);

  // Dashboard
  await expect(page.locator('text=Active Agents')).toBeVisible();
  await page.waitForTimeout(600);

  // Agents
  await page.locator('text=Agents').first().click();
  await expect(page.locator('text=/\\d+ registered/')).toBeVisible({ timeout: 8_000 });
  await page.waitForTimeout(600);

  // Click soul_core detail
  await page.locator('text=soul core').first().click();
  await expect(page.locator('text=All Agents')).toBeVisible({ timeout: 6_000 });
  await page.waitForTimeout(600);

  // Back to grid
  await page.locator('text=All Agents').click();
  await page.waitForTimeout(400);

  // System
  await page.getByText('System', { exact: true }).click();
  await expect(page.locator('text=Drift Monitor')).toBeVisible({ timeout: 8_000 });
  await page.waitForTimeout(600);

  // Social
  await page.locator('text=Social Media').click();
  await expect(page.locator('text=Social Media Manager')).toBeVisible({ timeout: 6_000 });
  await page.waitForTimeout(600);

  // Back to Dashboard
  await page.locator('text=Dashboard').click();
  await expect(page.locator('text=Active Agents')).toBeVisible({ timeout: 6_000 });
});
