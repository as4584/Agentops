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

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('connection');
  if (API_SECRET) {
    headers.set('Authorization', `Bearer ${API_SECRET}`);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    redirect: 'manual',
  };
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(buildUpstreamUrl(request, path), init);
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
