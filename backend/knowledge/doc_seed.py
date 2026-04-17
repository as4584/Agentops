"""
Qdrant doc seeding helpers for knowledge-agent retrieval.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.config import DOCS_DIR
from backend.knowledge.context_assembler import get_vector_store
from backend.ml.vector_store import QDRANT_AVAILABLE
from backend.utils import logger

DEFAULT_COLLECTION = "knowledge_agent"
DEFAULT_AGENT_NAMESPACE = "knowledge_agent"
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100


def chunk_markdown(text: str, size: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Split markdown into deterministic overlapping chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + size
        if end < len(text):
            boundary = text.rfind("\n\n", start + max(size - 200, 0), end)
            if boundary != -1:
                end = boundary
        chunks.append(text[start:end].strip())
        next_start = end - overlap if end < len(text) else end
        start = next_start if next_start > start else end
    return [chunk for chunk in chunks if len(chunk) > 40]


async def seed_docs_to_qdrant(
    llm_client: Any,
    docs_dir: Path | None = None,
    *,
    collection: str = DEFAULT_COLLECTION,
    agent_namespace: str = DEFAULT_AGENT_NAMESPACE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    """Seed markdown docs into Qdrant with deterministic IDs.

    Running this twice without ``force_rebuild`` is idempotent because IDs are
    stable per relative path and chunk index.
    """
    docs_root = (docs_dir or DOCS_DIR).resolve()
    store = get_vector_store()

    if not docs_root.is_dir():
        return {
            "agent_id": agent_namespace,
            "chunks": 0,
            "index_size_bytes": 0,
            "index_size_mb": 0.0,
            "source_documents": 0,
            "seeded": False,
            "reason": f"Docs directory not found: {docs_root}",
        }

    if not QDRANT_AVAILABLE or store._client is None:
        logger.warning("Doc seed skipped: Qdrant unavailable")
        return {
            "agent_id": agent_namespace,
            "chunks": 0,
            "index_size_bytes": 0,
            "index_size_mb": 0.0,
            "source_documents": 0,
            "seeded": False,
            "reason": "Qdrant unavailable",
        }

    if force_rebuild:
        try:
            existing = {c.name for c in store._client.get_collections().collections}
            if collection in existing:
                store._client.delete_collection(collection_name=collection)
                store._collections_initialized.discard(collection)
        except Exception as exc:
            logger.warning(f"Doc seed force rebuild could not clear collection '{collection}': {exc}")

    md_files = sorted(docs_root.rglob("*.md"))
    source_bytes = 0
    total_upserts = 0

    for path in md_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        source_bytes += len(text.encode("utf-8"))
        chunks = chunk_markdown(text, size=chunk_size, overlap=overlap)
        if not chunks:
            continue

        rel_path = path.relative_to(docs_root.parent).as_posix()
        vectors: list[list[float]] = []
        payloads: list[dict[str, Any]] = []
        ids: list[str] = []

        for idx, chunk in enumerate(chunks):
            vec = await llm_client.embed(chunk)
            if not vec:
                continue
            vectors.append(vec)
            payloads.append(
                {
                    "text": chunk,
                    "source": rel_path,
                    "file_path": rel_path,
                    "chunk_index": idx,
                }
            )
            ids.append(hashlib.sha256(f"{rel_path}:{idx}".encode()).hexdigest())

        if not vectors:
            continue

        batch_size = 50
        for start in range(0, len(vectors), batch_size):
            end = start + batch_size
            total_upserts += store.upsert(
                vectors=vectors[start:end],
                payloads=payloads[start:end],
                ids=ids[start:end],
                collection=collection,
                agent_namespace=agent_namespace,
            )

    stored_chunks = store.count(collection)
    return {
        "agent_id": agent_namespace,
        "chunks": stored_chunks if stored_chunks else total_upserts,
        "index_size_bytes": source_bytes,
        "index_size_mb": round(source_bytes / (1024 * 1024), 4),
        "source_documents": len(md_files),
        "seeded": True,
        "collection": collection,
    }
