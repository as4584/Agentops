/**
 * extension.ts — Agentop Orchestrator VS Code Extension
 *
 * Registers a Chat Participant (@agentop) that:
 *  1. Maps slash commands to Agentop backend agents.
 *  2. Falls back to intent detection for natural routing.
 *  3. Forwards the user's prompt to POST /chat on the backend.
 *  4. Streams the response back into the VS Code chat panel.
 *  5. Registers all 12 Agentop backend tools as LanguageModelTools
 *     so the LLM can call them directly within a conversation.
 *
 * Architecture note:
 *  The extension acts as the orchestration boundary between VS Code and the
 *  Agentop FastAPI backend.  It does NOT implement agent logic — it delegates
 *  100% to the backend. The LangGraph orchestrator on the backend handles all
 *  routing, memory, DriftGuard enforcement, and tool execution.
 */

import * as vscode from 'vscode';
import { AgentopClient } from './agentClient';
import { registerTools } from './tools';

// ---------------------------------------------------------------------------
// Slash command → agent_id mapping
// ---------------------------------------------------------------------------
const COMMAND_TO_AGENT: Record<string, string> = {
  soul:     'soul_core',
  devops:   'devops_agent',
  monitor:  'monitor_agent',
  security: 'security_agent',
  review:   'code_review_agent',
  data:     'data_agent',
  comms:    'comms_agent',
  it:       'it_agent',
  cs:       'cs_agent',
  // GSD workflow commands
  'gsd-map':    'gsd_agent',
  'gsd-plan':   'gsd_agent',
  'gsd-exec':   'gsd_agent',
  'gsd-quick':  'gsd_agent',
  'gsd-verify': 'gsd_agent',
};

// ---------------------------------------------------------------------------
// Keyword-based intent → agent heuristic (used when no slash command given)
// ---------------------------------------------------------------------------
const INTENT_PATTERNS: Array<{ pattern: RegExp; agent: string }> = [
  // GSD patterns checked first (most specific)
  { pattern: /\b(map-codebase|gsd:map|gsd map)\b/i,                          agent: 'gsd_agent' },
  { pattern: /\b(plan-phase|gsd:plan|gsd plan)\b/i,                           agent: 'gsd_agent' },
  { pattern: /\b(execute-phase|gsd:exec|gsd exec)\b/i,                        agent: 'gsd_agent' },
  { pattern: /\b(gsd:quick|gsd quick|gsd:verify|verify-work)\b/i,             agent: 'gsd_agent' },
  // Existing agent patterns
  { pattern: /\b(git|commit|deploy|pipeline|ci\/cd|branch|diff|merge)\b/i,   agent: 'devops_agent' },
  { pattern: /\b(health|uptime|metric|monitor|alert|latency|log)\b/i,         agent: 'monitor_agent' },
  { pattern: /\b(secret|password|credential|token|scan|cve|vuln)\b/i,         agent: 'security_agent' },
  { pattern: /\b(review|code quality|invariant|drift|lint|architecture)\b/i,  agent: 'code_review_agent' },
  { pattern: /\b(database|sql|query|schema|sqlite|table|migration)\b/i,       agent: 'data_agent' },
  { pattern: /\b(webhook|notify|incident|announcement|slack|email)\b/i,       agent: 'comms_agent' },
  { pattern: /\b(infrastructure|infra|server|disk|cpu|shell|process)\b/i,     agent: 'it_agent' },
  { pattern: /\b(customer|support|ticket|issue|help desk|user)\b/i,           agent: 'cs_agent' },
  { pattern: /\b(soul|goal|trust|reflect|conscience|govern)\b/i,              agent: 'soul_core' },
];

function detectAgent(prompt: string, defaultAgent: string): string {
  for (const { pattern, agent } of INTENT_PATTERNS) {
    if (pattern.test(prompt)) {
      return agent;
    }
  }
  return defaultAgent;
}

// ---------------------------------------------------------------------------
// GSD command dispatcher — maps slash commands to /api/gsd/* endpoints
// ---------------------------------------------------------------------------
async function handleGsdCommand(
  client: AgentopClient,
  command: string,
  prompt: string,
): Promise<string> {
  const base = (client as unknown as { base: string }).base;

  // Helper: POST to a GSD endpoint
  async function gsdPost(path: string, body: unknown): Promise<unknown> {
    const resp = await fetch(`${base}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!resp.ok) {
      const err = await resp.text();
      throw new Error(`GSD ${path} → HTTP ${resp.status}: ${err}`);
    }
    return resp.json();
  }

  switch (command) {
    case 'gsd-map': {
      const r = await gsdPost('/api/gsd/map-codebase', { workspace_root: '.' }) as Record<string, unknown>;
      return [
        '**GSD: map-codebase complete** ✅',
        '',
        `Generated at: \`${r['generated_at']}\``,
        '',
        'The following docs are now available:',
        ...(r['docs'] as string[]).map((d: string) => `- \`${d}\``),
        '',
        '> Reference these docs in future \`/gsd-plan\` calls instead of re-reading the entire codebase.',
      ].join('\n');
    }

    case 'gsd-plan': {
      // Parse optional phase number: "/gsd-plan 3 description" or just "description"
      const phaseMatch = prompt.match(/^(\d+)\s*(.*)/s);
      const phaseN = phaseMatch ? parseInt(phaseMatch[1], 10) : 1;
      const description = phaseMatch ? (phaseMatch[2] || prompt) : prompt;
      const r = await gsdPost(`/api/gsd/plan-phase/${phaseN}`, { description }) as Record<string, unknown>;
      const violations = r['gatekeeper_violations'] as string[];
      const lines = [
        `**GSD: plan-phase ${phaseN}** — ${r['title']}`,
        '',
        `Status: \`${r['status']}\``,
        `Tasks: ${r['task_count']} across ${r['waves']} wave(s)`,
        `Plan saved to: \`${r['plan_path']}\``,
      ];
      if (violations?.length) {
        lines.push('', '> ⚠️ **Gatekeeper violations (plan surfaced with warnings):**');
        violations.forEach((v: string) => lines.push(`> - ${v}`));
      }
      return lines.join('\n');
    }

    case 'gsd-exec': {
      // Parse optional phase number and --dry-run flag
      const dryRun = prompt.includes('--dry-run');
      const phaseMatch = prompt.match(/(\d+)/);
      const phaseN = phaseMatch ? parseInt(phaseMatch[1], 10) : 1;
      const r = await gsdPost(`/api/gsd/execute-phase/${phaseN}`, { dry_run: dryRun }) as Record<string, unknown>;
      const violations = r['gatekeeper_violations'] as string[];
      const lines = [
        `**GSD: execute-phase ${phaseN}** — ${r['status']}`,
        '',
        `Waves completed: ${r['waves_completed']}`,
        `Gatekeeper: ${r['gatekeeper_approved'] ? '✅ approved' : '❌ blocked'}`,
      ];
      if (violations?.length) {
        lines.push('', '> ⚠️ **Gatekeeper violations:**');
        violations.forEach((v: string) => lines.push(`> - ${v}`));
      }
      return lines.join('\n');
    }

    case 'gsd-quick': {
      const full = prompt.includes('--full');
      const cleanPrompt = prompt.replace('--full', '').trim();
      const r = await gsdPost('/api/gsd/quick', { prompt: cleanPrompt, full }) as Record<string, unknown>;
      return [
        '**GSD: quick task complete** ✅',
        '',
        r['response'] as string,
        '',
        `Committed: ${r['committed'] ? '✅ yes' : '❌ no'} · Timestamp: \`${r['timestamp']}\``,
      ].join('\n');
    }

    case 'gsd-verify': {
      const phaseMatch = prompt.match(/(\d+)/);
      const phaseN = phaseMatch ? parseInt(phaseMatch[1], 10) : undefined;
      const r = await gsdPost('/api/gsd/verify-work', { phase: phaseN ?? null }) as Record<string, unknown>;
      const report = r['report'] as Record<string, Array<{description: string; detail: string}>>;
      const lines = [
        `**GSD: verify-work** — Phase ${r['phase'] ?? 'latest'}`,
        '',
        `✅ Passed: **${r['passed']}**  ·  ❌ Failed: **${r['failed']}**  ·  ❓ Unverifiable: **${r['unverifiable']}**`,
      ];
      if (report?.['failed']?.length) {
        lines.push('', '**Failed checks:**');
        report['failed'].forEach(i => lines.push(`- ${i.description}: ${i.detail}`));
      }
      if (report?.['passed']?.length) {
        lines.push('', '**Passed checks:**');
        report['passed'].forEach(i => lines.push(`- ${i.description}`));
      }
      return lines.join('\n');
    }

    default:
      return `Unknown GSD command: \`${command}\``;
  }
}

// ---------------------------------------------------------------------------
// Format a backend response for display
// ---------------------------------------------------------------------------
function formatResponse(agentId: string, message: string, driftStatus: string): string {
  const driftEmoji = driftStatus === 'GREEN' ? '🟢' : driftStatus === 'RED' ? '🔴' : '🟡';
  return `**[${agentId}]** ${driftEmoji} *drift: ${driftStatus}*\n\n${message}`;
}

// ---------------------------------------------------------------------------
// Chat participant handler
// ---------------------------------------------------------------------------
function createHandler(client: AgentopClient): vscode.ChatRequestHandler {
  return async (
    request: vscode.ChatRequest,
    _context: vscode.ChatContext,
    stream: vscode.ChatResponseStream,
    token: vscode.CancellationToken,
  ): Promise<vscode.ChatResult> => {

    if (token.isCancellationRequested) {
      return {};
    }

    // 1. Resolve target agent
    const config = vscode.workspace.getConfiguration('agentop');
    const defaultAgent = config.get<string>('defaultAgent', 'knowledge_agent');

    let targetAgent: string;
    if (request.command && COMMAND_TO_AGENT[request.command]) {
      targetAgent = COMMAND_TO_AGENT[request.command];
    } else {
      targetAgent = detectAgent(request.prompt, defaultAgent);
    }

    // 2. Show routing info
    stream.progress(`Routing to **${targetAgent}**…`);

    // 3. If this is a GSD command, delegate directly to the GSD REST endpoint
    if (targetAgent === 'gsd_agent' && request.command) {
      try {
        const result = await handleGsdCommand(client, request.command, request.prompt);
        stream.markdown(result);
      } catch (err) {
        stream.markdown(`> ❌ **GSD command failed:** ${err instanceof Error ? err.message : String(err)}`);
      }
      return {};
    }

    // 4. Check backend health (non-fatal)
    try {
      const health = await client.health();
      if (!health.llm_available) {
        stream.markdown(
          '> ⚠️ **Ollama LLM is offline.** Responses may be unavailable.\n\n',
        );
      }
    } catch {
      stream.markdown(
        '> ⚠️ **Agentop backend is unreachable** at ' +
        config.get<string>('backendUrl', 'http://localhost:8000') +
        '. Start the backend with `python3 app.py`.\n\n',
      );
      return {};
    }

    if (token.isCancellationRequested) return {};

    // 5. Send to backend agent
    try {
      const response = await client.chat(targetAgent, request.prompt);

      // 5. Stream the formatted response
      const formatted = formatResponse(
        response.agent_id,
        response.message,
        response.drift_status,
      );
      stream.markdown(formatted);

      // 6. If drift is not GREEN, surface a warning button
      if (response.drift_status !== 'GREEN') {
        stream.button({
          command: 'agentop.openDashboard',
          title: '$(warning) View Drift Dashboard',
        });
      }

    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      stream.markdown(`> ❌ **Agent call failed:** ${msg}`);
    }

    return {};
  };
}

// ---------------------------------------------------------------------------
// Extension lifecycle
// ---------------------------------------------------------------------------
export function activate(context: vscode.ExtensionContext): void {
  const config = vscode.workspace.getConfiguration('agentop');
  const backendUrl = config.get<string>('backendUrl', 'http://localhost:8000');

  const client = new AgentopClient(backendUrl);

  // ---------------------------------------------------------------------------
  // Chat Participant
  // ---------------------------------------------------------------------------
  const participant = vscode.chat.createChatParticipant(
    'agentop.orchestrator',
    createHandler(client),
  );

  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, 'assets', 'agentop.png');

  // Followup provider — suggest relevant commands after each response
  participant.followupProvider = {
    provideFollowups(
      _result: vscode.ChatResult,
      _context: vscode.ChatContext,
      _token: vscode.CancellationToken,
    ): vscode.ProviderResult<vscode.ChatFollowup[]> {
      return [
        { prompt: 'Reflect on the cluster state', label: '🔮 Soul reflection', command: 'soul' },
        { prompt: 'Check all service health endpoints', label: '🩺 Health check', command: 'monitor' },
        { prompt: 'Scan codebase for exposed secrets', label: '🔒 Secret scan', command: 'security' },
        { prompt: 'Show recent git log', label: '📋 Git log', command: 'devops' },
      ];
    },
  };

  context.subscriptions.push(participant);

  // ---------------------------------------------------------------------------
  // LanguageModel Tools (all 12 backend tools)
  // ---------------------------------------------------------------------------
  registerTools(context, client);

  // ---------------------------------------------------------------------------
  // Commands
  // ---------------------------------------------------------------------------

  // Open the Agentop web dashboard
  context.subscriptions.push(
    vscode.commands.registerCommand('agentop.openDashboard', () => {
      const url = config.get<string>('backendUrl', 'http://localhost:8000').replace(':8000', ':3000');
      vscode.env.openExternal(vscode.Uri.parse(url));
    }),
  );

  // Show agent list in a quick-pick
  context.subscriptions.push(
    vscode.commands.registerCommand('agentop.listAgents', async () => {
      let agents;
      try {
        agents = await client.agents();
      } catch {
        vscode.window.showErrorMessage('Could not reach Agentop backend.');
        return;
      }
      const items = agents.map((a) => ({
        label: `$(robot) ${a.agent_id}`,
        description: a.change_impact_level,
        detail: a.role,
      }));
      await vscode.window.showQuickPick(items, {
        title: 'Agentop — Registered Agents',
        placeHolder: 'Select an agent to learn more',
      });
    }),
  );

  // Trigger soul reflection from command palette
  context.subscriptions.push(
    vscode.commands.registerCommand('agentop.soulReflect', async () => {
      const trigger = await vscode.window.showInputBox({
        prompt: 'Reflection trigger label',
        value: 'vscode-manual',
      });
      if (!trigger) return;
      vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: 'Agentop: Soul reflecting…' },
        async () => {
          try {
            const r = await client.soulReflect(trigger);
            vscode.window.showInformationMessage(
              `Soul reflection complete (${r.timestamp.slice(0, 19)}): ${r.reflection.slice(0, 120)}…`,
            );
          } catch (err) {
            vscode.window.showErrorMessage(`Soul reflection failed: ${err}`);
          }
        },
      );
    }),
  );

  // Watch for config changes and rebuild client
  context.subscriptions.push(
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration('agentop.backendUrl')) {
        const newUrl = vscode.workspace.getConfiguration('agentop').get<string>('backendUrl', 'http://localhost:8000');
        (client as unknown as { base: string }).base = newUrl.replace(/\/$/, '');
        vscode.window.showInformationMessage(`Agentop backend URL updated to: ${newUrl}`);
      }
    }),
  );

  console.log('Agentop Orchestrator extension activated.');
}

export function deactivate(): void {
  console.log('Agentop Orchestrator extension deactivated.');
}
