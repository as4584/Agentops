/**
 * tools.ts — LanguageModelTool registrations.
 *
 * Each tool maps to a backend POST /tools/{name} call.
 * When the LLM decides to call a tool, VS Code calls invoke() here,
 * which forwards the input to the Agentop backend and returns the result.
 */

import * as vscode from 'vscode';
import { AgentopClient } from './agentClient';

// ---------------------------------------------------------------------------
// Helper: create a generic backend-proxying tool
// ---------------------------------------------------------------------------
function makeBackendTool(
  client: AgentopClient,
  toolName: string,
): vscode.LanguageModelTool<Record<string, unknown>> {
  return {
    async invoke(
      options: vscode.LanguageModelToolInvocationOptions<Record<string, unknown>>,
      token: vscode.CancellationToken,
    ): Promise<vscode.LanguageModelToolResult> {
      if (token.isCancellationRequested) {
        return new vscode.LanguageModelToolResult([
          new vscode.LanguageModelTextPart('Cancelled.'),
        ]);
      }
      try {
        const result = await client.invokeTool(toolName, options.input);
        const text = result.success
          ? JSON.stringify(result.result, null, 2)
          : `Error: ${result.error ?? 'Unknown error'}`;
        return new vscode.LanguageModelToolResult([new vscode.LanguageModelTextPart(text)]);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        return new vscode.LanguageModelToolResult([
          new vscode.LanguageModelTextPart(`Tool invocation failed: ${msg}`),
        ]);
      }
    },

    async prepareInvocation(
      options: vscode.LanguageModelToolInvocationPrepareOptions<Record<string, unknown>>,
    ): Promise<vscode.PreparedToolInvocation> {
      return {
        invocationMessage: `Invoking Agentop tool: ${toolName}`,
        confirmationMessages: {
          title: `Agentop — ${toolName}`,
          message: new vscode.MarkdownString(
            `Run **${toolName}** with:\n\`\`\`json\n${JSON.stringify(options.input, null, 2)}\n\`\`\``,
          ),
        },
      };
    },
  };
}

// ---------------------------------------------------------------------------
// Register all 12 tools
// ---------------------------------------------------------------------------
const TOOL_NAMES = [
  'agentop_file_reader',
  'agentop_system_info',
  'agentop_git_ops',
  'agentop_health_check',
  'agentop_log_tail',
  'agentop_secret_scanner',
  'agentop_db_query',
  'agentop_alert_dispatch',
  'agentop_webhook_send',
  'agentop_process_restart',
  'agentop_safe_shell',
  'agentop_doc_updater',
] as const;

export function registerTools(
  context: vscode.ExtensionContext,
  client: AgentopClient,
): void {
  for (const name of TOOL_NAMES) {
    const disposable = vscode.lm.registerTool(name, makeBackendTool(client, name));
    context.subscriptions.push(disposable);
  }
}
