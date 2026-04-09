"use client";

import { useState } from "react";
import { GalleryEntry } from "@/types";

interface Props {
  activeEntry: GalleryEntry | null;
  previousEntry: GalleryEntry | null; // previous version of same business, or null
  onJudge: (verdict: "better" | "worse") => Promise<void>;
}

export default function PreferenceCard({ activeEntry, previousEntry, onJudge }: Props) {
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lastVerdict, setLastVerdict] = useState<"better" | "worse" | null>(null);

  if (!activeEntry) return null;

  // Reset state when active entry changes
  const key = activeEntry.gallery_dir;

  async function handleJudge(verdict: "better" | "worse") {
    setLoading(true);
    await onJudge(verdict);
    setLastVerdict(verdict);
    setSent(true);
    setLoading(false);
  }

  const canCompare = previousEntry !== null;

  return (
    <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold">Your judgment</span>
        <span className="text-xs text-[var(--muted)]">
          v{activeEntry.version} — score {activeEntry.avg_ux_score}
        </span>
      </div>

      {sent ? (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-2xl">{lastVerdict === "better" ? "👍" : "👎"}</span>
          <span className="text-[var(--muted)]">
            Recorded as {lastVerdict === "better" ? "better" : "worse"} than v
            {previousEntry?.version ?? "—"}.{" "}
            <button
              onClick={() => setSent(false)}
              className="text-indigo-400 hover:underline"
            >
              Undo
            </button>
          </span>
        </div>
      ) : (
        <>
          <p className="text-xs text-[var(--muted)]">
            {canCompare
              ? `Is v${activeEntry.version} better or worse than v${previousEntry!.version} (score ${previousEntry!.avg_ux_score})?`
              : "This is the first version — rate it for the record."}
          </p>
          <div className="flex gap-3">
            <button
              onClick={() => handleJudge("better")}
              disabled={loading}
              className="flex-1 py-3 rounded-xl bg-green-900/50 border border-green-700 hover:bg-green-800/60 text-green-300 font-bold text-xl transition-colors disabled:opacity-40"
            >
              👍
              <span className="block text-xs font-normal mt-0.5">Better</span>
            </button>
            <button
              onClick={() => handleJudge("worse")}
              disabled={loading}
              className="flex-1 py-3 rounded-xl bg-red-900/50 border border-red-700 hover:bg-red-800/60 text-red-300 font-bold text-xl transition-colors disabled:opacity-40"
            >
              👎
              <span className="block text-xs font-normal mt-0.5">Worse</span>
            </button>
          </div>
          <p className="text-[10px] text-[var(--muted)] text-center">
            Your vote saves a DPO training pair to data/dpo/
          </p>
        </>
      )}
    </div>
  );
}
