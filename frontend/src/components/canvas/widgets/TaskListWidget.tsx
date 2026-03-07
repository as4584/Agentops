/**
 * TaskListWidget — displays an ordered list of tasks.
 * Sprint 5.3 — v1 widget.
 */

"use client";

interface Task {
  id?: string;
  label: string;
  status?: "pending" | "running" | "done" | "error";
}

interface TaskListWidgetProps {
  widgetId: string;
  props: {
    title: string;
    tasks: Task[];
    show_completed?: boolean;
  };
}

const STATUS_ICON: Record<string, string> = {
  pending: "○",
  running: "◑",
  done: "●",
  error: "✕",
};

export default function TaskListWidget({ widgetId, props }: TaskListWidgetProps) {
  const tasks = props.show_completed === false
    ? props.tasks.filter((t) => t.status !== "done")
    : props.tasks;

  return (
    <div className="rounded-lg border border-gray-200 p-4 shadow-sm" data-widget-id={widgetId}>
      <h3 className="mb-2 font-semibold text-gray-800">{props.title}</h3>
      <ul className="space-y-1">
        {tasks.map((task, idx) => (
          <li key={task.id ?? idx} className="flex items-center gap-2 text-sm text-gray-700">
            <span className="w-4 shrink-0 text-center text-gray-400">
              {STATUS_ICON[task.status ?? "pending"] ?? "○"}
            </span>
            <span>{task.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
