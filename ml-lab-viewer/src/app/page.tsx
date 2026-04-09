"use client";

import { useCallback, useEffect, useState } from "react";
import type { GalleryEntry, GenerateRequest } from "@/types";
import GalleryList from "@/components/GalleryList";
import SitePreview from "@/components/SitePreview";
import PreferenceCard from "@/components/PreferenceCard";
import ScoreBreakdown from "@/components/ScoreBreakdown";
import GenerateModal from "@/components/GenerateModal";

export default function Home() {
  const [entries, setEntries] = useState<GalleryEntry[]>([]);
  const [active, setActive] = useState<GalleryEntry | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── Load gallery ────────────────────────────────────────────────────────
  const loadGallery = useCallback(async () => {
    try {
      const res = await fetch("/api/ml/webgen/gallery");
      if (!res.ok) throw new Error(`Gallery fetch failed: ${res.status}`);
      const data: GalleryEntry[] = await res.json();
      // Derive entry_name from gallery_dir
      const enriched = data.map((e) => ({
        ...e,
        entry_name: e.gallery_dir.split("/").pop() ?? e.gallery_dir,
      }));
      setEntries(enriched);
    } catch (err) {
      console.error(err);
      setError("Could not reach backend — is Agentop running on port 8000?");
    }
  }, []);

  useEffect(() => {
    loadGallery();
  }, [loadGallery]);

  // ── Find previous version of same business ──────────────────────────────
  const previousEntry: GalleryEntry | null = (() => {
    if (!active) return null;
    const prev = entries.find(
      (e) =>
        e.business_slug === active.business_slug &&
        e.version === active.version - 1,
    );
    return prev ?? null;
  })();

  // ── Generate ────────────────────────────────────────────────────────────
  async function handleGenerate(req: GenerateRequest) {
    setIsGenerating(true);
    setShowModal(false);
    setError(null);
    try {
      const res = await fetch("/api/ml/webgen/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(req),
      });
      if (!res.ok) {
        const detail = await res.text();
        throw new Error(detail);
      }
      const manifest: GalleryEntry = await res.json();
      const fresh = {
        ...manifest,
        entry_name: (manifest.gallery_dir ?? "").split("/").pop() ?? "",
      };
      await loadGallery();
      setActive(fresh);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Generation failed: ${msg}`);
    } finally {
      setIsGenerating(false);
    }
  }

  // ── Human preference ────────────────────────────────────────────────────
  async function handleJudge(verdict: "better" | "worse") {
    if (!active) return;
    const winnerEntry = verdict === "better" ? active : previousEntry ?? active;
    const loserEntry = verdict === "better" ? (previousEntry ?? active) : active;

    await fetch("/api/ml/webgen/preference", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        winner_entry: winnerEntry.entry_name ?? winnerEntry.gallery_dir.split("/").pop(),
        loser_entry: loserEntry.entry_name ?? loserEntry.gallery_dir.split("/").pop(),
        business_slug: active.business_slug,
        judge: "human",
      }),
    });
  }

  return (
    <div className="flex h-screen overflow-hidden">
      {/* ── Left sidebar ─────────────────────────────────────────────────── */}
      <div className="w-72 shrink-0 p-4 border-r border-[var(--border)] overflow-y-auto">
        <div className="mb-4">
          <h1 className="text-base font-bold">WebGen ML Lab</h1>
          <p className="text-xs text-[var(--muted)] mt-0.5">
            {entries.length} site{entries.length !== 1 ? "s" : ""} in gallery
          </p>
        </div>
        <GalleryList
          entries={entries}
          activeEntry={active}
          onSelect={setActive}
          onGenerate={() => setShowModal(true)}
        />
      </div>

      {/* ── Main area ────────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col gap-4 p-4 overflow-y-auto">
        {/* Error banner */}
        {error && (
          <div className="rounded-lg border border-red-700 bg-red-950/50 px-4 py-2.5 text-sm text-red-300 flex items-center justify-between">
            <span>{error}</span>
            <button onClick={() => setError(null)} className="text-red-500 hover:text-red-300 ml-4">
              ✕
            </button>
          </div>
        )}

        {/* Site iframe */}
        <SitePreview entry={active} isGenerating={isGenerating} />

        {/* Bottom cards */}
        <div className="grid grid-cols-2 gap-4">
          <PreferenceCard
            activeEntry={active}
            previousEntry={previousEntry}
            onJudge={handleJudge}
          />
          <ScoreBreakdown entry={active} />
        </div>
      </div>

      {/* ── Generate modal ───────────────────────────────────────────────── */}
      {showModal && (
        <GenerateModal
          onClose={() => setShowModal(false)}
          onSubmit={handleGenerate}
          isLoading={isGenerating}
        />
      )}
    </div>
  );
}
