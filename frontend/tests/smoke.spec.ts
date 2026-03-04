import { expect, test } from '@playwright/test';

test('dashboard loads', async ({ page }) => {
  await page.goto('/');
  await expect(page).toHaveTitle(/Agentop/i);
  await expect(page.locator('body')).toBeVisible();
});
