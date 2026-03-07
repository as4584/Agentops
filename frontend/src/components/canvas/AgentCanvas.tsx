/**
 * AgentCanvas — server-driven canvas shell (Sprint 5.3).
 *
 * Renders a bounded set of widgets driven by A2UI events received via the
 * WebSocket control plane.  No dynamic JS evaluation — all widget types are
 * declared statically in the widget registry below.
 */

"use client";

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  A2UIMessage,
  getCanvasState,
  subscribeCanvasState,
} from "@/lib/a2ui";
import StatusCard from "./widgets/StatusCard";
import TaskListWidget from "./widgets/TaskListWidget";
import KVTable from "./widgets/KVTable";

// ---------------------------------------------------------------------------
// Widget registry (v1) — NO dynamic evaluation
// ---------------------------------------------------------------------------

type WidgetRenderer = (msg: A2UIMessage) => ReactNode;

const WIDGET_REGISTRY: Record<string, WidgetRenderer> = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  status_card: (msg) => (
    <StatusCard key={msg.widget_id} widgetId={msg.widget_id!} props={msg.props as any} />
  ),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  task_list: (msg) => (
    <TaskListWidget key={msg.widget_id} widgetId={msg.widget_id!} props={msg.props as any} />
  ),
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  kv_table: (msg) => (
    <KVTable key={msg.widget_id} widgetId={msg.widget_id!} props={msg.props as any} />
  ),
};

// ---------------------------------------------------------------------------
// AgentCanvas component
// ---------------------------------------------------------------------------

interface AgentCanvasProps {
  target?: string;
  className?: string;
}

export default function AgentCanvas({
  target = "canvas/main",
  className = "",
}: AgentCanvasProps) {
  const [widgets, setWidgets] = useState<A2UIMessage[]>([]);

  useEffect(() => {
    function refresh() {
      const state = getCanvasState();
      const targetMap = state.get(target);
      if (targetMap) {
        setWidgets(Array.from(targetMap.values()));
      } else {
        setWidgets([]);
      }
    }

    refresh();
    const unsub = subscribeCanvasState(refresh);
    return unsub;
  }, [target]);

  if (widgets.length === 0) {
    return null;
  }

  return (
    <div className={`agent-canvas ${className}`} data-target={target}>
      {widgets.map((msg) => {
        const renderer = msg.component ? WIDGET_REGISTRY[msg.component] : null;
        if (!renderer) return null;
        return renderer(msg);
      })}
    </div>
  );
}
