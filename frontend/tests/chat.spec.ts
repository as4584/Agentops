import { expect, test } from '@playwright/test';

test('chat input is interactive', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Chat' }).click();
  const textbox = page.getByRole('textbox').first();
  await expect(textbox).toBeVisible();
  await textbox.fill('health check from playwright');
  await expect(textbox).toHaveValue('health check from playwright');
});
