"use client";

import { GalleryEntry } from "@/types";

interface Props {
  entries: GalleryEntry[];
  activeEntry: GalleryEntry | null;
  onSelect: (entry: GalleryEntry) => void;
  onGenerate: () => void;
}

function scoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 65) return "text-amber-400";
  return "text-red-400";
}

function groupBySlug(entries: GalleryEntry[]): Record<string, GalleryEntry[]> {
  return entries.reduce(
    (acc, e) => {
      const key = e.business_slug;
      acc[key] = [...(acc[key] ?? []), e];
      return acc;
    },
    {} as Record<string, GalleryEntry[]>,
  );
}

export default function GalleryList({ entries, activeEntry, onSelect, onGenerate }: Props) {
  const groups = groupBySlug(entries);

  return (
    <aside className="w-72 shrink-0 flex flex-col gap-4 h-full overflow-y-auto pr-1">
      {/* Generate button */}
      <button
        onClick={onGenerate}
        className="w-full py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-sm transition-colors"
      >
        + Generate New Site
      </button>

      {/* Group list */}
      {Object.entries(groups).map(([slug, versions]) => (
        <div key={slug} className="rounded-xl border border-[var(--border)] overflow-hidden">
          <div className="px-3 py-2 bg-[var(--surface)] text-xs font-semibold uppercase tracking-wider text-[var(--muted)]">
            {slug.replace(/-/g, " ")}
          </div>
          <ul>
            {versions.map((entry) => {
              const name = entry.gallery_dir.split("/").pop() ?? entry.gallery_dir;
              const isActive = activeEntry?.gallery_dir === entry.gallery_dir;
              return (
                <li key={entry.gallery_dir}>
                  <button
                    onClick={() => onSelect(entry)}
                    className={`w-full text-left px-3 py-2.5 flex items-center justify-between text-sm transition-colors border-t border-[var(--border)] ${
                      isActive
                        ? "bg-indigo-950 text-white"
                        : "hover:bg-[var(--surface)] text-[var(--text)]"
                    }`}
                  >
                    <span className="truncate">
                      v{entry.version}
                      <span className="ml-1.5 text-[var(--muted)] text-xs">{entry.model.split(":")[0]}</span>
                    </span>
                    <span className={`font-bold tabular-nums text-xs ${scoreColor(entry.avg_ux_score)}`}>
                      {entry.avg_ux_score}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      {entries.length === 0 && (
        <p className="text-[var(--muted)] text-sm text-center py-8">
          No sites generated yet.
          <br />
          Click the button above to start.
        </p>
      )}
    </aside>
  );
}
