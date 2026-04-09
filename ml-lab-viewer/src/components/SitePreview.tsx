"use client";

import { GalleryEntry } from "@/types";

interface Props {
  entry: GalleryEntry | null;
  isGenerating: boolean;
}

/** Derive the proxy-safe URL to serve a site file through the FastAPI /ml/webgen/site/ endpoint. */
function siteUrl(entry: GalleryEntry): string {
  const name = entry.gallery_dir.split("/").pop() ?? "";
  return `/api/ml/webgen/site/${encodeURIComponent(name)}/index.html`;
}

export default function SitePreview({ entry, isGenerating }: Props) {
  if (isGenerating) {
    return (
      <div className="flex-1 rounded-xl bg-[var(--surface)] border border-[var(--border)] overflow-hidden flex flex-col items-center justify-center gap-5 min-h-[600px]">
        {/* Skeleton placeholders while Ollama generates */}
        <div className="w-full px-6 space-y-3 animate-pulse">
          {/* Navbar skeleton */}
          <div className="h-10 rounded-lg bg-[var(--border)] w-full" />
          {/* Hero skeleton */}
          <div className="h-48 rounded-xl bg-[var(--border)] w-full" />
          {/* Cards skeleton */}
          <div className="grid grid-cols-3 gap-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-28 rounded-lg bg-[var(--border)]" />
            ))}
          </div>
          {/* Text lines */}
          <div className="h-4 rounded bg-[var(--border)] w-3/4" />
          <div className="h-4 rounded bg-[var(--border)] w-1/2" />
        </div>
        <p className="text-[var(--muted)] text-sm animate-pulse">Ollama is generating your site…</p>
      </div>
    );
  }

  if (!entry) {
    return (
      <div className="flex-1 rounded-xl bg-[var(--surface)] border border-[var(--border)] flex items-center justify-center min-h-[600px]">
        <p className="text-[var(--muted)] text-sm">Select a site from the gallery to preview it.</p>
      </div>
    );
  }

  return (
    <div className="flex-1 rounded-xl overflow-hidden border border-[var(--border)] min-h-[600px]">
      {/* URL bar header */}
      <div className="flex items-center gap-2 px-3 py-2 bg-[var(--surface)] border-b border-[var(--border)]">
        <span className="text-[var(--muted)] text-xs truncate">{siteUrl(entry)}</span>
        <a
          href={siteUrl(entry)}
          target="_blank"
          rel="noopener noreferrer"
          className="ml-auto text-indigo-400 hover:text-indigo-300 text-xs shrink-0"
        >
          Open ↗
        </a>
      </div>
      <iframe
        key={entry.gallery_dir}
        src={siteUrl(entry)}
        title={entry.business_slug}
        className="w-full h-[600px] bg-white"
        sandbox="allow-scripts allow-same-origin"
      />
    </div>
  );
}
