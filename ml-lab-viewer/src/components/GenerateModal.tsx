"use client";

import { useState } from "react";
import { GenerateRequest } from "@/types";

const BUSINESS_TYPES = [
  "gym / fitness",
  "restaurant",
  "law firm",
  "auto detailing",
  "real estate",
  "tech startup",
  "dental clinic",
  "e-commerce",
  "photography",
  "consulting",
];

const DESIGN_STYLES = ["premium", "minimal", "bold", "corporate", "playful"];

interface Props {
  onClose: () => void;
  onSubmit: (req: GenerateRequest) => void;
  isLoading: boolean;
}

export default function GenerateModal({ onClose, onSubmit, isLoading }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState(BUSINESS_TYPES[0]);
  const [style, setStyle] = useState("premium");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    onSubmit({ business_name: name.trim(), business_type: type, design_style: style });
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-lg font-semibold">Generate New Site</h2>
          <button
            onClick={onClose}
            disabled={isLoading}
            className="text-[var(--muted)] hover:text-white text-xl leading-none"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label className="block text-xs text-[var(--muted)] mb-1">Business name</label>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Peak Performance Gym"
              disabled={isLoading}
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            />
          </div>

          <div>
            <label className="block text-xs text-[var(--muted)] mb-1">Business type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              disabled={isLoading}
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            >
              {BUSINESS_TYPES.map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs text-[var(--muted)] mb-1">Design style</label>
            <select
              value={style}
              onChange={(e) => setStyle(e.target.value)}
              disabled={isLoading}
              className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-500 disabled:opacity-50"
            >
              {DESIGN_STYLES.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>

          <button
            type="submit"
            disabled={isLoading || !name.trim()}
            className="mt-2 py-2.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold text-sm transition-colors"
          >
            {isLoading ? "Generating… (~60s)" : "Generate"}
          </button>
        </form>

        {isLoading && (
          <p className="mt-4 text-xs text-[var(--muted)] text-center animate-pulse">
            Ollama is building your site — this takes about 60 seconds…
          </p>
        )}
      </div>
    </div>
  );
}
