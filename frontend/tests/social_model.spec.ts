/**
 * Playwright regressions for the lightweight_social Social card contract.
 *
 * Covers:
 *   1. DeepSeek appears as a selectable option in the Social card model switcher
 *   2. Selecting DeepSeek PATCHes /agents/comms_agent/model
 *   3. On reload the Social card hydrates model from backend agent_overrides
 *   4. A lightweight_social reply with ordo_trace causes the Ordo panel to render
 *
 * All tests use mocked backend endpoints (same pattern as chat.spec.ts).
 */
import { expect, test } from '@playwright/test';

// ---------------------------------------------------------------------------
// Shared mock helper
// ---------------------------------------------------------------------------

const DEEPSEEK_MODEL = {
  model_id: 'deepseek-r1:7b',
  display_name: 'DeepSeek R1 7B (local)',
  provider: 'ollama',
  context_window: 131072,
  input_cost_per_m: 0,
  output_cost_per_m: 0,
  supports_tools: false,
  available_locally: true,
  role: null,
  alias_of: null,
};

const LLAMA_MODEL = {
  model_id: 'llama3.2',
  display_name: 'Llama 3.2 3B',
  provider: 'ollama',
  context_window: 131072,
  input_cost_per_m: 0,
  output_cost_per_m: 0,
  supports_tools: false,
  available_locally: true,
  role: null,
  alias_of: null,
};

type MockOptions = {
  /** If set, agent_overrides will include comms_agent -> this model */
  commsAgentOverride?: string;
};

async function setupMocks(page: import('@playwright/test').Page, opts: MockOptions = {}) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });

  await page.route('http://localhost:8000/**', async (route) => {
    const url = route.request().url();
    const pathname = new URL(url).pathname;
    const method = route.request().method();

    if (pathname === '/health') {
      return route.fulfill(json({ status: 'ok', llm_available: true, drift_status: 'GREEN', uptime_seconds: 1, timestamp: new Date().toISOString() }));
    }
    if (pathname === '/agents') return route.fulfill(json([]));
    if (pathname === '/tools') return route.fulfill(json([]));
    if (pathname === '/drift') return route.fulfill(json({ status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() }));
    if (pathname === '/logs') return route.fulfill(json([]));
    if (pathname === '/memory/agents') return route.fulfill(json({ agents: [], total_size_bytes: 0, total_size_mb: 0 }));
    if (pathname === '/soul/goals') return route.fulfill(json({ goals: [], count: 0 }));
    if (pathname === '/tasks') return route.fulfill(json({ tasks: [], stats: { total: 0, queued: 0, running: 0, completed: 0, failed: 0 } }));
    if (pathname === '/status') return route.fulfill(json({ agents: [], drift_report: { status: 'GREEN', pending_updates: [], violations: [], last_check: new Date().toISOString() }, recent_logs: [], total_tool_executions: 0, uptime_seconds: 1 }));
    if (pathname === '/llm/stats') {
      return route.fulfill(json({ stats: { total_requests: 0, local_requests: 0, cloud_requests: 0, tokens_in: 0, tokens_out: 0, estimated_cost_usd: 0, avg_latency_ms: 0, cost_per_request_avg: 0 }, cost_log: [], budget: { monthly_limit_usd: 50, spent_usd: 0, remaining_usd: 50, percent_used: 0 }, tokens: { total_in: 0, total_out: 0, total: 0 }, circuit_states: {} }));
    }
    if (pathname === '/llm/capacity') return route.fulfill(json({ available_models: [], total_known_models: 0, model_capacities: [] }));
    if (pathname === '/projects') return route.fulfill(json({ projects: [], total: 0, types: {} }));
    if (pathname === '/folders/browse') return route.fulfill(json({ current: '.', parent: null, entries: [] }));
    if (pathname === '/conversations/active') return route.fulfill(json({ conversation_id: null, messages: [] }));

    // Registry — includes DeepSeek + optional agent_override
    if (pathname === '/models/registry') {
      const overrides: Record<string, string> = {};
      if (opts.commsAgentOverride) overrides['comms_agent'] = opts.commsAgentOverride;
      return route.fulfill(json({ models: [LLAMA_MODEL, DEEPSEEK_MODEL], agent_overrides: overrides }));
    }

    // Model PATCH — record the call and respond success
    if (method === 'PATCH' && pathname.startsWith('/agents/') && pathname.endsWith('/model')) {
      const body = await route.request().postDataJSON();
      return route.fulfill(json({ agent_id: 'comms_agent', model_id: body?.model_id ?? '' }));
    }

    // Chat — return a lightweight_social reply with ordo_trace
    if (pathname === '/chat') {
      return route.fulfill(json({
        agent_id: 'comms_agent',
        message: 'Slide 1: AI Ethics\nSlide 2: Bias in Algorithms',
        routing_method: 'lightweight_social',
        ordo_trace: {
          lane: 'social',
          confidence: 0.91,
          reasoning: 'lightweight_social path matched',
          agent_id: 'comms_agent',
          tool_calls: [],
          error: null,
          grounded_signal: 'carousel intent + news enrichment',
          assessment: 'dispatched directly to comms_agent',
          inferred: false,
        },
        model_used: opts.commsAgentOverride ?? 'llama3.2',
        drift_status: 'GREEN',
        conversation_id: 'test-conv-1',
        run_id: null,
        message_id: null,
        sources: [],
        timestamp: new Date().toISOString(),
      }));
    }

    return route.abort();
  });
}

// ---------------------------------------------------------------------------
// 1. DeepSeek appears in the Social card model switcher
// ---------------------------------------------------------------------------
test('Social card model switcher lists DeepSeek', async ({ page }) => {
  await setupMocks(page);
  await page.goto('/');
  await page.getByRole('tab', { name: 'Command' }).click();

  // The Social & Support card shows a model switcher — open it
  // The switcher button shows the current model display name
  const socialCard = page.locator('text=Social & Support').locator('../..');
  const switcherButton = socialCard.locator('button').filter({ hasText: /llama|deepseek|mistral/i }).first();
  await expect(switcherButton).toBeVisible({ timeout: 8000 });
  await switcherButton.click();

  // DeepSeek should appear in the dropdown options
  await expect(page.getByText('DeepSeek R1 7B', { exact: false })).toBeVisible({ timeout: 4000 });
});

// ---------------------------------------------------------------------------
// 2. Selecting DeepSeek PATCHes /agents/comms_agent/model
// ---------------------------------------------------------------------------
test('Selecting DeepSeek in Social switcher calls PATCH /agents/comms_agent/model', async ({ page }) => {
  const patchRequests: string[] = [];

  await setupMocks(page);
  // Intercept PATCH to record it
  await page.route('http://localhost:8000/agents/comms_agent/model', async (route) => {
    if (route.request().method() === 'PATCH') {
      const body = await route.request().postDataJSON();
      patchRequests.push(body?.model_id ?? '');
    }
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ agent_id: 'comms_agent', model_id: 'deepseek-r1:7b' }) });
  });

  await page.goto('/');
  await page.getByRole('tab', { name: 'Command' }).click();

  const socialCard = page.locator('text=Social & Support').locator('../..');
  const switcherButton = socialCard.locator('button').filter({ hasText: /llama|deepseek|mistral/i }).first();
  await expect(switcherButton).toBeVisible({ timeout: 8000 });
  await switcherButton.click();

  // Click the DeepSeek option
  await page.getByText('DeepSeek R1 7B', { exact: false }).click();

  // Verify the PATCH was sent with the correct model_id
  expect(patchRequests).toContain('deepseek-r1:7b');
});

// ---------------------------------------------------------------------------
// 3. Social card hydrates from backend override on load
// ---------------------------------------------------------------------------
test('Social card shows backend override model on mount', async ({ page }) => {
  // Backend reports comms_agent is set to deepseek-r1:7b
  await setupMocks(page, { commsAgentOverride: 'deepseek-r1:7b' });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Command' }).click();

  // The Social card switcher button should eventually show DeepSeek as the selected model
  const socialCard = page.locator('text=Social & Support').locator('../..');
  await expect(
    socialCard.locator('button').filter({ hasText: /deepseek/i }).first()
  ).toBeVisible({ timeout: 6000 });
});

// ---------------------------------------------------------------------------
// 4. Ordo panel renders for lightweight_social reply
// ---------------------------------------------------------------------------
test('Ordo panel is visible after a lightweight_social response', async ({ page }) => {
  await setupMocks(page);
  await page.goto('/');
  await page.getByRole('tab', { name: 'Command' }).click();

  // Find the Social card chat input and send a carousel request
  const socialCard = page.locator('text=Social & Support').locator('../..');
  const chatInput = socialCard.locator('textarea').first();
  await expect(chatInput).toBeVisible({ timeout: 8000 });
  await chatInput.fill('make a carousel using the news from discord');

  // Submit by pressing Enter or clicking send
  await chatInput.press('Enter');

  // The Ordo panel should appear — it renders with the text "Ordo"
  await expect(page.getByText('Ordo').first()).toBeVisible({ timeout: 8000 });
});
