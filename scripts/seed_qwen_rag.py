#!/usr/bin/env python3
"""
Seed Qwen knowledge docs into the knowledge-agent Qdrant collection.

Usage:
    python scripts/seed_qwen_rag.py [--force]

    --force    Delete and rebuild the collection from scratch.

Requires: nomic-embed-text running in Ollama (ollama pull nomic-embed-text)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to sys.path so backend imports resolve
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import DOCS_DIR
from backend.knowledge.doc_seed import seed_docs_to_qdrant
from backend.llm import OllamaClient
from backend.utils import logger


QWEN_DOCS_DIR = DOCS_DIR / "qwen"
COLLECTION = "knowledge_agent"
AGENT_NAMESPACE = "knowledge_agent"


async def main(force: bool = False) -> None:
    if not QWEN_DOCS_DIR.is_dir():
        logger.error(f"Qwen docs directory not found: {QWEN_DOCS_DIR}")
        sys.exit(1)

    md_files = list(QWEN_DOCS_DIR.rglob("*.md"))
    if not md_files:
        logger.error(f"No .md files found in {QWEN_DOCS_DIR}")
        sys.exit(1)

    logger.info(f"Found {len(md_files)} Qwen doc files to seed:")
    for f in sorted(md_files):
        logger.info(f"  {f.relative_to(PROJECT_ROOT)}")

    llm = OllamaClient()  # embed_client resolved from QDRANT_EMBED_MODEL internally

    logger.info(
        f"Seeding into collection='{COLLECTION}', namespace='{AGENT_NAMESPACE}', "
        f"force_rebuild={force}"
    )

    result = await seed_docs_to_qdrant(
        llm_client=llm,
        docs_dir=DOCS_DIR,          # rglob picks up docs/qwen/*.md automatically
        collection=COLLECTION,
        agent_namespace=AGENT_NAMESPACE,
        chunk_size=600,
        overlap=100,
        force_rebuild=force,
    )

    await llm.close()

    if result.get("seeded"):
        logger.info("Seed complete:")
        logger.info(f"  chunks upserted  : {result['chunks']}")
        logger.info(f"  source documents : {result['source_documents']}")
        logger.info(f"  index size       : {result['index_size_mb']} MB")
    else:
        reason = result.get("reason", "unknown")
        logger.warning(f"Seed skipped: {reason}")
        if "Qdrant unavailable" in reason:
            logger.warning(
                "Qdrant is not running. Start it with:\n"
                "  docker run -p 6333:6333 qdrant/qdrant\n"
                "Or run with the KnowledgeVectorStore JSON fallback — "
                "the seeder will still embed via nomic-embed-text once Qdrant is available."
            )
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed Qwen docs into RAG knowledge store")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete and rebuild the collection from scratch (re-embeds all chunks)",
    )
    args = parser.parse_args()
    asyncio.run(main(force=args.force))
