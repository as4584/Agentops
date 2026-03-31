import { expect, test } from '@playwright/test';

test('chat input is interactive', async ({ page }) => {
  // Mock backend so the dashboard reaches "connected" state without runtime errors
  await page.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url();
    const pathname = new URL(url).pathname;

    const json = (body: unknown) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });

    if (pathname === '/health') {
      return json({ status: 'ok', llm_available: true, drift_status: 'GREEN', uptime_seconds: 1, timestamp: new Date().toISOString() });
    }
    if (pathname === '/agents') return json([]);
    if (pathname === '/tools') return json([]);
    if (pathname === '/drift') return json({ status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() });
    if (pathname === '/logs') return json([]);
    if (pathname === '/memory/agents') return json({ agents: [], total_size_bytes: 0, total_size_mb: 0 });
    if (pathname === '/soul/goals') return json({ goals: [], count: 0 });
    if (pathname === '/tasks') return json({ tasks: [], stats: { total: 0, queued: 0, running: 0, completed: 0, failed: 0 } });
    if (pathname === '/status') return json({ agents: [], drift_report: { status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() }, recent_logs: [], total_tool_executions: 0, uptime_seconds: 1 });
    if (pathname === '/llm/stats') {
      return json({
        stats: { total_requests: 0, local_requests: 0, cloud_requests: 0, tokens_in: 0, tokens_out: 0, estimated_cost_usd: 0, avg_latency_ms: 0, cost_per_request_avg: 0 },
        cost_log: [],
        budget: { monthly_limit_usd: 50, spent_usd: 0, remaining_usd: 50, percent_used: 0 },
        tokens: { total_in: 0, total_out: 0, total: 0 },
        circuit_states: {},
      });
    }
    if (pathname === '/llm/capacity') return json({ available_models: [], total_known_models: 0, model_capacities: [] });
    if (pathname === '/projects') return json({ projects: [], total: 0, types: {} });
    if (pathname === '/folders/browse') return json({ current: '.', parent: null, entries: [] });
    if (pathname === '/chat') return json({ reply: 'pong' });
    // Abort unmocked endpoints (ML, SSE, etc.) so fetchData's try/catch
    // keeps state at safe initial defaults instead of setting {} on arrays
    return route.abort();
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Chat' }).click();
  const textbox = page.getByRole('textbox').first();
  await expect(textbox).toBeVisible();
  await textbox.fill('health check from playwright');
  await expect(textbox).toHaveValue('health check from playwright');
});
