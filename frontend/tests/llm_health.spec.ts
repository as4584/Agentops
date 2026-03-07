import { expect, test } from '@playwright/test';

test('system tab shows LLM health badges and red circuit-open state', async ({ page }) => {
  await page.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url();
    const pathname = new URL(url).pathname;

    const json = (body: unknown) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (pathname === '/health') {
      return json({ status: 'ok', llm_available: true, drift_status: 'GREEN', uptime_seconds: 123, timestamp: new Date().toISOString() });
    }
    if (pathname === '/agents') return json([]);
    if (pathname === '/tools') return json([]);
    if (pathname === '/drift') return json({ status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() });
    if (pathname === '/logs') return json([]);
    if (pathname === '/memory/agents') return json({ agents: [], total_size_bytes: 0, total_size_mb: 0 });
    if (pathname === '/soul/goals') return json({ goals: [], count: 0 });
    if (pathname === '/tasks') return json({ tasks: [], stats: { total: 0, queued: 0, running: 0, completed: 0, failed: 0 } });
    if (pathname === '/status') return json({ agents: [], drift_report: { status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() }, recent_logs: [], total_tool_executions: 0, uptime_seconds: 123 });
    if (pathname === '/llm/stats') {
      return json({
        stats: {
          total_requests: 5,
          local_requests: 2,
          cloud_requests: 3,
          tokens_in: 100,
          tokens_out: 50,
          estimated_cost_usd: 0.01,
          avg_latency_ms: 120,
          cost_per_request_avg: 0.002,
        },
        cost_log: [],
        budget: {
          monthly_limit_usd: 50,
          spent_usd: 0.01,
          remaining_usd: 49.99,
          percent_used: 0.02,
        },
        tokens: { total_in: 100, total_out: 50, total: 150 },
        circuit_states: {
          'llama3.2': {
            model_id: 'llama3.2',
            healthy: true,
            circuit_open: false,
            consecutive_failures: 0,
            last_error: null,
          },
          'claude-sonnet': {
            model_id: 'claude-sonnet',
            healthy: false,
            circuit_open: true,
            consecutive_failures: 3,
            last_error: 'RuntimeError: upstream error',
          },
        },
      });
    }
    if (pathname === '/llm/capacity') return json({ available_models: [], total_known_models: 0, model_capacities: [] });
    if (pathname === '/projects') return json({ projects: [], total: 0, types: {} });
    if (pathname === '/folders/browse') return json({ current: '.', parent: null, entries: [] });

    return json({});
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'System' }).click();

  await expect(page.getByTestId('llm-health-panel')).toBeVisible();
  await expect(page.getByTestId('llm-health-badge-claude-sonnet')).toBeVisible();
  await expect(page.getByTestId('llm-health-badge-claude-sonnet')).toContainText('Circuit Open');
});
