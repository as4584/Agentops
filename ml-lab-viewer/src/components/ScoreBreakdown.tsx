"use client";

import { GalleryEntry } from "@/types";

interface Props {
  entry: GalleryEntry | null;
}

function dot(score: number) {
  if (score >= 80) return "bg-green-400";
  if (score >= 65) return "bg-amber-400";
  return "bg-red-400";
}

function label(score: number) {
  if (score >= 80) return "text-green-400";
  if (score >= 65) return "text-amber-400";
  return "text-red-400";
}

export default function ScoreBreakdown({ entry }: Props) {
  if (!entry || !entry.ux_scores || Object.keys(entry.ux_scores).length === 0) return null;

  const pages = Object.entries(entry.ux_scores).sort((a, b) => b[1] - a[1]);
  const max = 100;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold">Page scores</span>
        <span className="text-xs text-[var(--muted)]">
          avg{" "}
          <span className={`font-bold ${label(entry.avg_ux_score)}`}>{entry.avg_ux_score}</span>
          /100
        </span>
      </div>
      <ul className="space-y-2">
        {pages.map(([slug, score]) => (
          <li key={slug} className="flex items-center gap-2">
            <span className={`w-2 h-2 rounded-full shrink-0 ${dot(score)}`} />
            <span className="text-xs text-[var(--muted)] w-28 truncate">{slug}</span>
            <div className="flex-1 h-2 bg-[var(--border)] rounded-full overflow-hidden">
              <div
                className={`h-full rounded-full ${dot(score)}`}
                style={{ width: `${(score / max) * 100}%` }}
              />
            </div>
            <span className={`text-xs font-bold tabular-nums w-6 text-right ${label(score)}`}>
              {score}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
