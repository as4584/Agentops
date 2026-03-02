/**
 * agentClient.ts — HTTP client for the Agentop FastAPI backend.
 *
 * All communication with localhost:8000 goes through this module.
 * No state is held here — callers provide the base URL from config.
 */

import * as https from 'https';
import * as http from 'http';

export interface ChatResponse {
  agent_id: string;
  message: string;
  drift_status: string;
  timestamp: string;
}

export interface AgentDefinition {
  agent_id: string;
  role: string;
  tool_permissions: string[];
  memory_namespace: string;
  change_impact_level: string;
}

export interface ToolInvokeResponse {
  tool: string;
  success: boolean;
  result: unknown;
  error?: string;
}

export interface SoulReflection {
  reflection: string;
  trigger: string;
  timestamp: string;
}

export interface SoulGoal {
  id: string;
  title: string;
  description: string;
  priority: string;
  created_at: string;
  completed: boolean;
}

// ---------------------------------------------------------------------------
// Core fetch helper — works in Node (no global fetch pre-18.x)
// ---------------------------------------------------------------------------
function request<T>(
  url: string,
  method: 'GET' | 'POST',
  body?: unknown,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const parsed = new URL(url);
    const isHttps = parsed.protocol === 'https:';
    const transport = isHttps ? https : http;
    const postData = body ? JSON.stringify(body) : undefined;

    const options: http.RequestOptions = {
      hostname: parsed.hostname,
      port: parsed.port || (isHttps ? 443 : 80),
      path: parsed.pathname + parsed.search,
      method,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'application/json',
        ...(postData ? { 'Content-Length': Buffer.byteLength(postData) } : {}),
      },
    };

    const req = transport.request(options, (res) => {
      let data = '';
      res.on('data', (chunk: string) => (data += chunk));
      res.on('end', () => {
        if (res.statusCode && res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode}: ${data}`));
        } else {
          try {
            resolve(JSON.parse(data) as T);
          } catch {
            reject(new Error(`Invalid JSON: ${data}`));
          }
        }
      });
    });

    req.on('error', reject);
    if (postData) req.write(postData);
    req.end();
  });
}

// ---------------------------------------------------------------------------
// AgentopClient
// ---------------------------------------------------------------------------
export class AgentopClient {
  private base: string;

  constructor(backendUrl: string) {
    this.base = backendUrl.replace(/\/$/, '');
  }

  /** Send a message to any registered agent. */
  chat(agentId: string, message: string): Promise<ChatResponse> {
    return request<ChatResponse>(`${this.base}/chat`, 'POST', {
      agent_id: agentId,
      message,
    });
  }

  /** Get all registered agent definitions. */
  agents(): Promise<AgentDefinition[]> {
    return request<AgentDefinition[]>(`${this.base}/agents`, 'GET');
  }

  /** Health check. */
  health(): Promise<{ status: string; llm_available: boolean; uptime_seconds: number }> {
    return request(`${this.base}/health`, 'GET');
  }

  /** Invoke a backend tool directly (calls POST /tools/{name}).*/
  invokeTool(toolName: string, input: Record<string, unknown>): Promise<ToolInvokeResponse> {
    // Strip "agentop_" prefix from the VS Code tool name
    const backendName = toolName.replace(/^agentop_/, '');
    return request<ToolInvokeResponse>(`${this.base}/tools/${backendName}`, 'POST', input);
  }

  /** Trigger soul reflection. */
  soulReflect(trigger = 'vscode'): Promise<SoulReflection> {
    return request<SoulReflection>(
      `${this.base}/soul/reflect?trigger=${encodeURIComponent(trigger)}`,
      'POST',
    );
  }

  /** Get all soul goals. */
  soulGoals(): Promise<{ goals: SoulGoal[]; count: number }> {
    return request(`${this.base}/soul/goals`, 'GET');
  }

  /** Add a soul goal. */
  soulAddGoal(title: string, description: string, priority = 'MEDIUM'): Promise<SoulGoal> {
    return request<SoulGoal>(`${this.base}/soul/goals`, 'POST', { title, description, priority });
  }
}
