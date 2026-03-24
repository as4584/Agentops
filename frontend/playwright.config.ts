import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  timeout: 30_000,
  expect: { timeout: 15_000 },
  reporter: [['html', { outputFolder: '../reports/playwright/playwright-report', open: 'never' }]],
  outputDir: '../reports/playwright/test-results',
  use: {
    baseURL: 'http://127.0.0.1:3007',
    trace: 'on-first-retry',
  },
  webServer: {
    command: 'npm run dev',
    port: 3007,
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
