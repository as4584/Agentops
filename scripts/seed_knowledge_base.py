"""
Seed Knowledge Base — embed docs/ into Qdrant for knowledge_agent RAG.

Usage:
    python scripts/seed_knowledge_base.py
    python scripts/seed_knowledge_base.py --query "UX law scoring weights"
    python scripts/seed_knowledge_base.py --docs docs --chunk-size 600
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.llm import OllamaClient
from backend.ml.vector_store import VectorStore

COLLECTION = "knowledge_agent"
EMBED_MODEL = "nomic-embed-text"
EMBED_DIM = 768  # nomic-embed-text produces 768-dim, not the VectorStore default 384
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            # Try to break at a paragraph boundary
            boundary = text.rfind("\n\n", start + size - 200, end)
            if boundary != -1:
                end = boundary
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if len(c) > 40]


async def embed_chunks(client: OllamaClient, chunks: list[str]) -> list[list[float]]:
    vectors = []
    for chunk in chunks:
        vec = await client.embed(chunk)
        vectors.append(vec)
    return vectors


async def seed(docs_dir: Path, chunk_size: int, qdrant_host: str = "localhost") -> None:
    client = OllamaClient(model=EMBED_MODEL)
    store = VectorStore(host=qdrant_host)
    store.ensure_collection(COLLECTION, dim=EMBED_DIM)

    md_files = sorted(docs_dir.rglob("*.md"))
    print(f"Found {len(md_files)} markdown files in '{docs_dir}'\n")

    total = 0
    for path in md_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = chunk_text(text, size=chunk_size)
        if not chunks:
            continue

        vectors = await embed_chunks(client, chunks)
        payloads = [
            {
                "text": c,
                "source": str(path.relative_to(docs_dir.parent)),
                "filename": path.name,
                "chunk_idx": i,
            }
            for i, c in enumerate(chunks)
        ]
        ids = [
            hashlib.md5(f"{path}:{i}".encode()).hexdigest()
            for i in range(len(chunks))
        ]
        # Batch upserts to stay under Qdrant's 32MB payload limit
        batch_size = 50
        n = 0
        for start in range(0, len(chunks), batch_size):
            end = start + batch_size
            n += store.upsert(
                vectors=vectors[start:end],
                payloads=payloads[start:end],
                ids=ids[start:end],
                collection=COLLECTION,
                agent_namespace="knowledge_agent",
            )
        print(f"  {path.name:<50} {n:>4} chunks")
        total += n

    print(f"\nDone. {total} chunks indexed into '{COLLECTION}'")


async def query(question: str, qdrant_host: str = "localhost") -> None:
    client = OllamaClient(model=EMBED_MODEL)
    store = VectorStore(host=qdrant_host)
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
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help="Chars per chunk")
    parser.add_argument("--query", default="", help="After seeding, run this test query")
    parser.add_argument("--qdrant-host", default="localhost", help="Qdrant host (default: localhost)")
    args = parser.parse_args()

    docs_path = Path(args.docs)
    if not docs_path.is_dir():
        print(f"ERROR: docs directory not found: {docs_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(seed(docs_path, args.chunk_size, args.qdrant_host))

    if args.query:
        asyncio.run(query(args.query, args.qdrant_host))
