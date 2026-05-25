#!/usr/bin/env python3
"""
ingest_cli.py — Week 2 ticket A1: knowledge ingestion CLI.
==========================================================

Walk a directory, chunk text files (.md, .txt, .rst, optionally .pdf via the
GLM-OCR sidecar), embed via ``nomic-embed-text`` (768-dim), and upsert into a
named Qdrant collection. Hash-based dedup makes re-running idempotent. The
BM25 sparse index at ``data/bm25_index.pkl`` is rebuilt at the end so
hybrid retrieval picks up the new corpus immediately.

Usage:
    python -m cli.ingest_cli docs/
    python -m cli.ingest_cli docs/ --collection knowledge_agent
    python -m cli.ingest_cli docs/ --reindex          # force_rebuild
    python -m cli.ingest_cli some_dir/ --ocr          # also ingest *.pdf via GLM-OCR

The DoD for ticket A1 is satisfied when ``python -m cli.ingest_cli docs/``
exits 0 and a subsequent ``POST /chat`` to the knowledge_agent asking
"what is the MVP scope?" returns an answer citing docs/MVP_SCOPE.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Ensure project root is on path when invoked as `python cli/ingest_cli.py`.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.knowledge.context_assembler import ContextAssembler  # noqa: E402
from backend.knowledge.doc_seed import (  # noqa: E402
    DEFAULT_TEXT_EXTENSIONS,
    seed_docs_to_qdrant,
)
from backend.llm import OllamaClient  # noqa: E402


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="agentop ingest",
        description="Ingest a directory of documents into the knowledge_agent Qdrant collection.",
    )
    parser.add_argument("path", type=Path, help="Directory to ingest (recursive).")
    parser.add_argument(
        "--collection",
        default="knowledge_agent",
        help="Target Qdrant collection name (default: knowledge_agent).",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Force rebuild: drop the collection + manifest before ingesting.",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Also ingest *.pdf via the GLM-OCR sidecar (must be running on :5002).",
    )
    parser.add_argument(
        "--extensions",
        default=",".join(e.lstrip("*.") for e in DEFAULT_TEXT_EXTENSIONS),
        help=(
            "Comma-separated extensions to ingest (without leading dot). "
            f"Default: {','.join(e.lstrip('*.') for e in DEFAULT_TEXT_EXTENSIONS)}"
        ),
    )
    parser.add_argument(
        "--skip-bm25",
        action="store_true",
        help="Skip the BM25 rebuild step (useful for unit tests / scripted ingest).",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> int:
    if not args.path.exists() or not args.path.is_dir():
        print(f"error: {args.path} is not a directory", file=sys.stderr)
        return 2

    exts = tuple(f"*.{e.strip().lstrip('.')}" for e in args.extensions.split(",") if e.strip())
    if not exts:
        print("error: --extensions must contain at least one entry", file=sys.stderr)
        return 2

    # OllamaClient is required by the API even though seed_docs_to_qdrant
    # uses a dedicated embedding client internally.
    llm = OllamaClient()
    try:
        seed_result = await seed_docs_to_qdrant(
            llm,
            docs_dir=args.path,
            collection=args.collection,
            force_rebuild=args.reindex,
            extensions=exts,
            enable_ocr=args.ocr,
        )
    finally:
        await llm.close()

    if not seed_result.get("seeded"):
        print(json.dumps(seed_result, indent=2))
        print(f"error: ingestion did not run: {seed_result.get('reason', 'unknown')}", file=sys.stderr)
        return 1

    bm25_chunks = 0
    if not args.skip_bm25:
        bm25_llm = OllamaClient()
        assembler = ContextAssembler(bm25_llm)
        try:
            bm25_chunks = await assembler.build_bm25_from_qdrant(
                collection=args.collection,
                force_rebuild=True,
            )
        finally:
            await bm25_llm.close()

    summary = {
        **seed_result,
        "bm25_chunks": bm25_chunks,
    }
    print(json.dumps(summary, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
