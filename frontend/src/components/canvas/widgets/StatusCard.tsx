/**
 * StatusCard widget — displays an agent state with optional progress.
 * Sprint 5.3 — v1 widget.
 */

"use client";

import { dispatchA2UIAction } from "@/lib/a2ui";

interface StatusCardProps {
  widgetId: string;
  props: {
    title: string;
    state: "idle" | "running" | "success" | "warning" | "error" | "info";
    message?: string;
    progress?: number;
  };
  agentId?: string;
  sessionId?: string;
  target?: string;
}

const STATE_COLORS: Record<string, string> = {
  idle: "bg-gray-100 text-gray-700",
  running: "bg-blue-100 text-blue-700",
  success: "bg-green-100 text-green-700",
  warning: "bg-yellow-100 text-yellow-800",
  error: "bg-red-100 text-red-700",
  info: "bg-purple-100 text-purple-700",
};

export default function StatusCard({
  widgetId,
  props,
  agentId = "",
  sessionId = "",
  target = "canvas/main",
}: StatusCardProps) {
  const colorClass = STATE_COLORS[props.state] ?? "bg-gray-100 text-gray-700";

  async function handleDismiss() {
    if (!agentId || !sessionId) return;
    await dispatchA2UIAction({
      widget_id: widgetId,
      target,
      action_type: "dismiss",
      agent_id: agentId,
      session_id: sessionId,
    });
  }

  return (
    <div className={`rounded-lg p-4 shadow-sm ${colorClass}`} data-widget-id={widgetId}>
      <div className="flex items-center justify-between">
        <span className="font-semibold">{props.title}</span>
        <span className="text-xs uppercase tracking-wide">{props.state}</span>
      </div>
      {props.message && (
        <p className="mt-1 text-sm opacity-80">{props.message}</p>
      )}
      {props.progress !== undefined && (
        <div className="mt-2 h-1.5 w-full rounded-full bg-white/40">
          <div
            className="h-full rounded-full bg-current opacity-60"
            style={{ width: `${Math.round(props.progress * 100)}%` }}
          />
        </div>
      )}
      {agentId && (
        <button
          onClick={handleDismiss}
          className="mt-2 text-xs underline opacity-60 hover:opacity-100"
        >
          Dismiss
        </button>
      )}
    </div>
  );
}
