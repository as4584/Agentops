import { NextRequest } from 'next/server';

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const BACKEND_BASE =
  process.env.AGENTOP_API_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'http://127.0.0.1:8000';
const API_SECRET = process.env.AGENTOP_API_SECRET || '';

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function buildUpstreamUrl(request: NextRequest, path: string[]): string {
  const cleanBase = BACKEND_BASE.replace(/\/+$/, '');
  const upstream = new URL(`${cleanBase}/${path.join('/')}`);
  upstream.search = new URL(request.url).search;
  return upstream.toString();
}

function jsonError(payload: Record<string, unknown>, status: number): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-store',
    },
  });
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('connection');
  if (API_SECRET) {
    headers.set('Authorization', `Bearer ${API_SECRET}`);
  }

  // Generous timeout for long-running pipeline endpoints (5 min)
  // but short enough to avoid infinite hangs.
  // SSE streams (Accept: text/event-stream) get no timeout — they stay open.
  const controller = new AbortController();
  const isSSE = request.headers.get('accept')?.includes('text/event-stream');
  const timeoutMs = isSSE ? 0 : request.method === 'GET' ? 30_000 : 300_000;
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null;

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: 'manual',
    ...(timeoutMs > 0 ? { signal: controller.signal } : {}),
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.arrayBuffer();
  }

  const upstreamUrl = buildUpstreamUrl(request, path);
  let upstream: Response;
  try {
    upstream = await fetch(upstreamUrl, init);
  } catch (error) {
    if (timer) clearTimeout(timer);
    const isAbort = error instanceof DOMException && error.name === 'AbortError';
    return jsonError(
      {
        detail: isAbort
          ? 'Backend request timed out through the Next proxy'
          : 'Backend API is unavailable through the Next proxy',
        upstream: upstreamUrl,
        proxy: '/api/proxy',
        error: error instanceof Error ? error.message : 'Unknown fetch error',
      },
      isAbort ? 504 : 502,
    );
  }
  if (timer) clearTimeout(timer);

  if (upstream.status === 401 && !API_SECRET) {
    return jsonError(
      {
        detail: 'Backend rejected the request because the frontend proxy is missing AGENTOP_API_SECRET',
        upstream: upstreamUrl,
        proxy: '/api/proxy',
        upstream_status: 401,
      },
      401,
    );
  }

  const responseHeaders = new Headers(upstream.headers);
  responseHeaders.delete('content-encoding');
  responseHeaders.delete('content-length');

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}

export async function OPTIONS(request: NextRequest, context: RouteContext): Promise<Response> {
  return proxy(request, context);
}
