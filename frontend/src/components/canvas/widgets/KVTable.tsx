/**
 * KVTable widget — displays a key/value table.
 * Sprint 5.3 — v1 widget.
 */

"use client";

interface KVRow {
  key: string;
  value: unknown;
}

interface KVTableProps {
  widgetId: string;
  props: {
    title: string;
    rows: KVRow[];
    striped?: boolean;
  };
}

export default function KVTable({ widgetId, props }: KVTableProps) {
  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 shadow-sm" data-widget-id={widgetId}>
      <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 font-semibold text-gray-700">
        {props.title}
      </div>
      <table className="w-full text-sm">
        <tbody>
          {props.rows.map((row, idx) => (
            <tr
              key={idx}
              className={
                props.striped && idx % 2 === 1 ? "bg-gray-50" : "bg-white"
              }
            >
              <td className="w-1/3 px-4 py-1.5 font-medium text-gray-600">
                {row.key}
              </td>
              <td className="px-4 py-1.5 text-gray-800">
                {String(row.value ?? "")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
