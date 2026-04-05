#!/usr/bin/env python3
"""
scripts/fetch_openrouter_models.py
───────────────────────────────────
Pull the current free model catalog from OpenRouter and save reference
benchmark data for the 5 selected models (3 molds).

Mold 1 — Tiny Router  (replaces / competes with lex-v2, small enough for local)
Mold 2 — Medium Local (fits 12 GB VRAM, used to train lex-v3)
Mold 3 — Large Cloud  (free via OpenRouter, max quality fallback)

Output files (data/benchmarks/):
  openrouter_free_models.json          — full catalog, all free models
  openrouter_selected_models.json      — 5 selected models + reference benchmarks
  openrouter_reference_benchmarks.json — hardcoded published benchmark scores

Usage:
  python scripts/fetch_openrouter_models.py
  python scripts/fetch_openrouter_models.py --dry-run   # prints list, no API call
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = ROOT / "data" / "benchmarks"
BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# ── Reference benchmark scores (published, OpenRouter / HuggingFace leaderboards)
# Source: openrouter.ai model pages + HuggingFace Open LLM Leaderboard
# Last verified: 2026-04-05
REFERENCE_BENCHMARKS: dict[str, dict] = {
    "google/gemma-3n-e2b-it:free": {
        "name": "Google: Gemma 3n 2B (free)",
        "mold": "tiny_router",
        "params_b": 2.0,
        "vram_required_gb": 2.0,
        "mmlu": 52.1,
        "hellaswag": 71.4,
        "arc_challenge": 48.3,
        "context_length": 8192,
        "notes": "MatFormer architecture, effective 2B from 6B. Fast, tiny, Mold-1 lex competitor.",
        "ollama_tag": "gemma3:2b",
    },
    "meta-llama/llama-3.2-3b-instruct:free": {
        "name": "Meta: Llama 3.2 3B Instruct (free)",
        "mold": "tiny_router",
        "params_b": 3.0,
        "vram_required_gb": 2.5,
        "mmlu": 58.0,
        "hellaswag": 74.1,
        "arc_challenge": 51.5,
        "context_length": 131072,
        "notes": "Current lex-v2 base. Direct baseline. Long context 128k.",
        "ollama_tag": "llama3.2:3b",
    },
    "google/gemma-3-12b-it:free": {
        "name": "Google: Gemma 3 12B (free)",
        "mold": "medium_local",
        "params_b": 12.0,
        "vram_required_gb": 7.5,
        "mmlu": 74.8,
        "hellaswag": 84.2,
        "arc_challenge": 64.7,
        "context_length": 131072,
        "notes": "Target base for lex-v3. Fits 12 GB VRAM at q4. Multimodal (text+image).",
        "ollama_tag": "gemma3:12b",
    },
    "google/gemma-3-27b-it:free": {
        "name": "Google: Gemma 3 27B (free)",
        "mold": "large_cloud",
        "params_b": 27.0,
        "vram_required_gb": 18.0,
        "mmlu": 81.2,
        "hellaswag": 87.9,
        "arc_challenge": 72.1,
        "context_length": 131072,
        "notes": "Best Gemma free tier. Too large for 12 GB VRAM — use via OpenRouter API only.",
        "ollama_tag": None,
    },
    "nousresearch/hermes-3-llama-3.1-405b:free": {
        "name": "Nous: Hermes 3 405B Instruct (free)",
        "mold": "large_cloud",
        "params_b": 405.0,
        "vram_required_gb": None,
        "mmlu": 88.7,
        "hellaswag": 90.8,
        "arc_challenge": 82.5,
        "context_length": 131072,
        "notes": "Max quality free model. Agentic-focused, strong tool calling. Cloud only.",
        "ollama_tag": None,
    },
}

# ── Model IDs we care about (for selective lookup in full catalog)
SELECTED_IDS = set(REFERENCE_BENCHMARKS.keys())


def fetch_free_models(dry_run: bool = False) -> list[dict]:
    """Fetch all free models from OpenRouter API."""
    if dry_run:
        print("[dry-run] Would fetch:", OPENROUTER_MODELS_URL)
        return []

    req = urllib.request.Request(
        OPENROUTER_MODELS_URL,
        headers={
            "User-Agent": "Agentop/1.0 (benchmark collection; https://github.com/as4584/Agentops)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode())

    all_models: list[dict] = data.get("data", [])
    free_models = [m for m in all_models if m.get("pricing", {}).get("prompt") == "0"]
    return free_models


def build_selected_catalog(free_models: list[dict]) -> list[dict]:
    """Merge live OpenRouter metadata with our reference benchmark scores."""
    live_by_id = {m["id"]: m for m in free_models}
    selected = []

    for model_id, bench in REFERENCE_BENCHMARKS.items():
        live = live_by_id.get(model_id, {})
        entry = {
            "id": model_id,
            **bench,
            "live_context_length": live.get("context_length"),
            "live_max_completion": live.get("top_provider", {}).get("max_completion_tokens"),
            "supported_parameters": live.get("supported_parameters", []),
            "tool_calling": "tools" in live.get("supported_parameters", []),
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        selected.append(entry)

    return selected


def print_summary(selected: list[dict]) -> None:
    molds = {"tiny_router": [], "medium_local": [], "large_cloud": []}
    for m in selected:
        molds[m["mold"]].append(m)

    print("\n┌─ Agentop Model Selection ──────────────────────────────────────")
    for mold_name, models in molds.items():
        label = mold_name.replace("_", " ").upper()
        print(f"│\n│  [{label}]")
        for m in models:
            vram = f"{m['vram_required_gb']} GB" if m["vram_required_gb"] else "cloud only"
            print(f"│    • {m['name']}")
            print(f"│      MMLU {m['mmlu']} | VRAM {vram} | ctx {m['context_length']:,}")
    print("└────────────────────────────────────────────────────────────────\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch OpenRouter free model catalog")
    parser.add_argument("--dry-run", action="store_true", help="Print selection, no API call")
    args = parser.parse_args()

    if args.dry_run:
        print("[dry-run] Selected model IDs:")
        for model_id, bench in REFERENCE_BENCHMARKS.items():
            print(f"  [{bench['mold']}] {model_id}")
        print_summary(list(REFERENCE_BENCHMARKS.values()))
        sys.exit(0)

    print("Fetching free model catalog from OpenRouter...")
    try:
        free_models = fetch_free_models()
        print(f"  Found {len(free_models)} free models total")
    except Exception as e:
        print(f"  Warning: API fetch failed ({e}), using reference data only")
        free_models = []

    # Save full free catalog
    full_catalog_path = BENCHMARK_DIR / "openrouter_free_models.json"
    with open(full_catalog_path, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "source": OPENROUTER_MODELS_URL,
                "count": len(free_models),
                "models": free_models,
            },
            f,
            indent=2,
        )
    print(f"  Saved full catalog → {full_catalog_path.relative_to(ROOT)}")

    # Save selected 5 models with benchmark data
    selected = build_selected_catalog(free_models)
    selected_path = BENCHMARK_DIR / "openrouter_selected_models.json"
    with open(selected_path, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now(UTC).isoformat(),
                "description": "5 selected models across 3 molds for Agentop lex-v3 training and routing",
                "molds": {
                    "tiny_router": "Replaces / competes with lex-v2. Runs locally.",
                    "medium_local": "Training base for lex-v3. Fits 12 GB VRAM.",
                    "large_cloud": "Max quality via OpenRouter free tier. Cloud only.",
                },
                "models": selected,
            },
            f,
            indent=2,
        )
    print(f"  Saved selected catalog → {selected_path.relative_to(ROOT)}")

    # Save reference benchmarks separately (clean reference doc)
    ref_path = BENCHMARK_DIR / "openrouter_reference_benchmarks.json"
    with open(ref_path, "w") as f:
        json.dump(
            {
                "source": "OpenRouter model pages + HuggingFace Open LLM Leaderboard",
                "note": "Published scores — not measured by Agentop. Used for model selection only.",
                "last_verified": "2026-04-05",
                "benchmarks": REFERENCE_BENCHMARKS,
            },
            f,
            indent=2,
        )
    print(f"  Saved reference benchmarks → {ref_path.relative_to(ROOT)}")

    print_summary(selected)


if __name__ == "__main__":
    main()
