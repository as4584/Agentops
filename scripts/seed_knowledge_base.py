"""Seed Qdrant from project docs for knowledge-agent retrieval."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import QDRANT_DEFAULT_DIM, QDRANT_EMBED_MODEL
from backend.knowledge.doc_seed import DEFAULT_CHUNK_SIZE, seed_docs_to_qdrant
from backend.llm import OllamaClient
from backend.ml.vector_store import VectorStore

COLLECTION = "knowledge_agent"


async def seed(docs_dir: Path, chunk_size: int, qdrant_host: str = "localhost", force_rebuild: bool = False) -> None:
    client = OllamaClient(model=QDRANT_EMBED_MODEL)
    stats = await seed_docs_to_qdrant(
        client,
        docs_dir=docs_dir,
        collection=COLLECTION,
        agent_namespace="knowledge_agent",
        chunk_size=chunk_size,
        force_rebuild=force_rebuild,
    )
    print(f"Seeded {stats.get('chunks', 0)} chunks from {stats.get('source_documents', 0)} docs into '{COLLECTION}'")
    if not stats.get("seeded", False):
        print(f"  skipped: {stats.get('reason', 'unknown reason')}")


async def query(question: str, qdrant_host: str = "localhost") -> None:
    client = OllamaClient(model=QDRANT_EMBED_MODEL)
    store = VectorStore(host=qdrant_host, default_dim=QDRANT_DEFAULT_DIM)
    vec = await client.embed(question)
    results = store.search(
        query_vector=vec,
        limit=5,
        collection=COLLECTION,
        agent_namespace="knowledge_agent",
    )
    print(f'\nTop results for: "{question}"\n')
    for r in results:
        p = r["payload"]
        print(f"  [{r['score']:.3f}] {p['source']}  chunk {p['chunk_idx']}")
        print(f"         {p['text'][:120].strip()!r}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed knowledge_agent vector store from docs/")
    parser.add_argument("--docs", default="docs", help="Path to docs directory (default: docs)")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Chars per chunk")
    parser.add_argument("--query", default="", help="After seeding, run this test query")
    parser.add_argument("--qdrant-host", default="localhost", help="Qdrant host (default: localhost)")
    parser.add_argument("--force-rebuild", action="store_true", help="Drop and rebuild the Qdrant collection")
    args = parser.parse_args()

    docs_path = Path(args.docs)
    if not docs_path.is_dir():
        print(f"ERROR: docs directory not found: {docs_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(seed(docs_path, args.chunk_size, args.qdrant_host, force_rebuild=args.force_rebuild))

    if args.query:
        asyncio.run(query(args.query, args.qdrant_host))
