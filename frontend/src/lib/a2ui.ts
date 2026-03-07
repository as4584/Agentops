/**
 * A2UI WebSocket client — bridges canvas events into the UI state store.
 *
 * Sprint 5.3 / 5.4 — Frontend transport skeleton.
 * Full implementation requires the WS control plane (Feature 1 / ws.ts).
 */

export type A2UIComponentType = "status_card" | "task_list" | "kv_table";
export type A2UIOp = "render" | "replace" | "append" | "clear";

export interface A2UIMessage {
  ui_event_id: string;
  session_id: string;
  agent_id: string;
  op: A2UIOp;
  target: string;
  widget_id?: string;
  component?: A2UIComponentType;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  props?: Record<string, any>;
  seq: number;
  timestamp: string;
}

export interface A2UIAction {
  action_id?: string;
  widget_id: string;
  target: string;
  action_type: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  payload?: Record<string, any>;
  agent_id: string;
  session_id: string;
}

type CanvasStateMap = Map<string, Map<string, A2UIMessage>>;

// ---------------------------------------------------------------------------
// Singleton canvas state store
// ---------------------------------------------------------------------------

const _canvasState: CanvasStateMap = new Map();
const _listeners: Array<(state: CanvasStateMap) => void> = [];

export function getCanvasState(): CanvasStateMap {
  return _canvasState;
}

export function subscribeCanvasState(
  listener: (state: CanvasStateMap) => void
): () => void {
  _listeners.push(listener);
  return () => {
    const idx = _listeners.indexOf(listener);
    if (idx >= 0) _listeners.splice(idx, 1);
  };
}

function _notifyListeners() {
  for (const l of _listeners) {
    try {
      l(_canvasState);
    } catch (_) {
      /* swallow */
    }
  }
}

// ---------------------------------------------------------------------------
// Apply incoming A2UI event
// ---------------------------------------------------------------------------

export function applyA2UIEvent(msg: A2UIMessage): void {
  if (msg.op === "clear") {
    if (msg.target) {
      _canvasState.delete(msg.target);
    } else {
      _canvasState.clear();
    }
    _notifyListeners();
    return;
  }

  if (!msg.widget_id) return;

  if (!_canvasState.has(msg.target)) {
    _canvasState.set(msg.target, new Map());
  }
  const targetMap = _canvasState.get(msg.target)!;

  if (msg.op === "render" || msg.op === "replace" || msg.op === "append") {
    targetMap.set(msg.widget_id, msg);
  }

  _notifyListeners();
}

// ---------------------------------------------------------------------------
// Dispatch an action back to the backend
// ---------------------------------------------------------------------------

export async function dispatchA2UIAction(action: A2UIAction): Promise<boolean> {
  try {
    const resp = await fetch("/canvas/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(action),
    });
    return resp.ok;
  } catch {
    return false;
  }
}
