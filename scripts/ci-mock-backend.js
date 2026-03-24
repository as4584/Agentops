#!/usr/bin/env node
/**
 * Minimal mock backend for CI. Responds to all API endpoints the frontend
 * needs to reach connected=true, so Playwright tests can run without Ollama.
 */
const http = require('http');

const routes = {
  '/health': { status: 'ok', llm_available: false, uptime_seconds: 0, version: 'ci-mock' },
  '/agents': [],
  '/tools': [],
  '/drift': { violations: [], drift_score: 0, last_updated: null },
  '/status': { agents: [] },
  '/tasks': { tasks: [], stats: {} },
  '/projects': { projects: [], types: [] },
  '/llm/stats': { tokens: { total: 0 }, stats: { total_requests: 0 } },
  '/llm/capacity': { available: false },
  '/models': { models: [], available_locally: [], total_known: 0, agent_recommendations: {} },
  '/events': [],
};

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET,POST,PUT,DELETE,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type,Authorization',
};

const server = http.createServer((req, res) => {
  const url = (req.url || '/').split('?')[0];

  if (req.method === 'OPTIONS') {
    res.writeHead(204, CORS);
    return res.end();
  }

  let body;
  if (routes[url] !== undefined) {
    body = routes[url];
  } else if (url.startsWith('/logs')) {
    body = [];
  } else if (url.startsWith('/memory/agents')) {
    body = { agents: [], total_size_bytes: 0, total_size_mb: 0 };
  } else if (url.startsWith('/memory')) {
    body = { namespaces: {}, shared_events_count: 0 };
  } else if (url.startsWith('/soul/goals')) {
    body = { goals: [], count: 0 };
  } else if (url.startsWith('/soul')) {
    body = { reflection: '', goals: [] };
  } else if (url.startsWith('/folders')) {
    body = { entries: [], current: '.', parent: null };
  } else {
    body = {};
  }

  res.writeHead(200, { 'Content-Type': 'application/json', ...CORS });
  res.end(JSON.stringify(body));
});

const PORT = process.env.MOCK_PORT || 8000;
server.listen(PORT, '127.0.0.1', () => {
  console.log(`[ci-mock-backend] listening on http://127.0.0.1:${PORT}`);
});
