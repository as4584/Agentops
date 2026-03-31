#!/usr/bin/env python3
"""
scripts/build_spec_pairs.py
────────────────────────────
Strategy 3: IBDS component specs → TypeScript/Mantine implementations.

34 detailed component specs live in clients/ibds/specs/*.md.
This turns each spec into a fine-tuning pair that teaches the model
how to implement production-grade TypeScript + Mantine components.

Modes:
  --raw     Formats spec as instruction + stub answer (no LLM). Fast.
  --ollama  Asks Ollama to write the full TypeScript component from the spec.

Usage:
  python scripts/build_spec_pairs.py --raw
  python scripts/build_spec_pairs.py --ollama
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = ROOT / "clients" / "ibds" / "specs"
OUT_DIR = ROOT / "data" / "training"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

IBDS_SYSTEM_PROMPT = """You are Lex, a TypeScript + React engineer who builds enterprise AI dashboards
using Next.js 14 App Router, Mantine v7, and TailwindCSS. You follow these conventions:
- Functional components with TypeScript strict mode
- Server Components for data fetching, Client Components only when needed (use 'use client')
- Mantine v7 API (use `rem()` not `px`, `useStyles` with `createStyles`, `Group/Stack/Box`)
- Clean prop interfaces with JSDoc where non-obvious
- Proper loading/error states and accessibility attributes
- No inline styles — use Mantine sx prop or CSS modules
Write clean, production-ready code. Reply with the complete TypeScript component file."""


def ollama_implement(spec_content: str, component_name: str) -> str:
    """Ask Ollama to implement a TypeScript component from a spec."""
    try:
        import requests
    except ImportError:
        return build_stub_implementation(component_name, spec_content)

    prompt = f"""Implement this React/TypeScript component for the IBDS enterprise AI dashboard.

**Component:** `{component_name}`

**Specification:**
{spec_content[:2500]}

Write the complete TypeScript component file following Next.js 14 + Mantine v7 conventions.
Include imports, type definitions, and the default export. Add brief comments for non-obvious logic."""

    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": IBDS_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 900},
    }
    try:
        import requests
        resp = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as e:
        return f"[Ollama error: {e}]\n\n{build_stub_implementation(component_name, spec_content)}"


def build_stub_implementation(component_name: str, spec: str) -> str:
    """Build a template implementation with spec notes (no LLM)."""
    # Extract key requirements from spec
    lines = spec.splitlines()
    requirements = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            requirements.append(stripped[2:])
        elif re.match(r"^\d+\.", stripped):
            requirements.append(stripped)

    req_comments = "\n".join(f"  // - {r}" for r in requirements[:8])

    return f"""'use client';
// AUTO-GENERATED STUB — implement based on spec requirements
// Run with --ollama to generate full implementation via local LLM.

import {{ useState }} from 'react';
import {{ Box, Group, Stack, Text, Button, Paper }} from '@mantine/core';

// Requirements from spec:
{req_comments or "  // See spec for full requirements"}

interface {component_name}Props {{
  // TODO: define props based on spec
}}

export default function {component_name}({{ ...props }}: {component_name}Props) {{
  const [loading, setLoading] = useState(false);

  // TODO: implement based on spec:
  // {spec[:200].replace(chr(10), ' // ')[:200]}

  return (
    <Box>
      <Stack gap="md">
        <Text fw={{700}}>{component_name}</Text>
        {{/* TODO: implement UI from spec */}}
      </Stack>
    </Box>
  );
}}"""


def build_question(component_name: str, spec: str) -> str:
    return (
        f"Implement the `{component_name}` component for the IBDS enterprise AI dashboard "
        f"using Next.js 14, Mantine v7, and TypeScript strict mode.\n\n"
        f"**Component Specification:**\n\n{spec[:2000]}"
    )


def pair_to_sharegpt(q: str, a: str) -> dict:
    return {"conversations": [{"from": "human", "value": q}, {"from": "gpt", "value": a}]}


def main() -> None:
    parser = argparse.ArgumentParser(description="IBDS specs → TypeScript implementation pairs.")
    parser.add_argument("--raw", action="store_true", help="Stub implementation (no LLM)")
    parser.add_argument("--ollama", action="store_true", help="Full implementation via Ollama")
    args = parser.parse_args()

    if not args.raw and not args.ollama:
        print("Defaulting to --raw mode.")
        args.raw = True

    spec_files = sorted(SPECS_DIR.glob("*.md"))
    if not spec_files:
        print(f"[error] No spec files found in {SPECS_DIR}")
        return

    print(f"[specs] Found {len(spec_files)} component specs")
    pairs = []

    for i, spec_file in enumerate(spec_files):
        component_name = spec_file.stem  # e.g. "HeroSection"
        spec_content = spec_file.read_text(encoding="utf-8", errors="ignore")

        question = build_question(component_name, spec_content)

        if args.ollama:
            print(f"  [{i+1:2d}/{len(spec_files)}] {component_name:<30}", end="  ", flush=True)
            answer = ollama_implement(spec_content, component_name)
            print(f"→ {len(answer)} chars")
            time.sleep(0.3)
        else:
            answer = build_stub_implementation(component_name, spec_content)
            print(f"  [{i+1:2d}/{len(spec_files)}] {component_name:<30} → stub")

        pairs.append(pair_to_sharegpt(question, answer))

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode = "ollama" if args.ollama else "raw"
    out_path = OUT_DIR / f"spec_pairs_{mode}_{timestamp}.jsonl"

    with out_path.open("w", encoding="utf-8") as f:
        for rec in pairs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"\n✓ {len(pairs)} spec pairs → {out_path}")
    print(f"  Components covered: {', '.join(f.stem for f in spec_files[:5])} + {len(spec_files)-5} more")


if __name__ == "__main__":
    main()
