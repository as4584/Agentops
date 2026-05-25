"""
Qdrant doc seeding helpers for knowledge-agent retrieval.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from backend.config import DOCS_DIR, QDRANT_EMBED_MODEL
from backend.knowledge.context_assembler import get_vector_store
from backend.ml.vector_store import QDRANT_AVAILABLE
from backend.utils import logger

DEFAULT_COLLECTION = "knowledge_agent"
DEFAULT_AGENT_NAMESPACE = "knowledge_agent"
DEFAULT_CHUNK_SIZE = 600
DEFAULT_CHUNK_OVERLAP = 100

# Default extensions for the v1.0 ingestion CLI (Week 2 ticket A1).
# Existing `seed_docs_to_qdrant(...)` call sites pass nothing → keep ``*.md``-only
# behaviour to avoid regressions. The CLI passes the wider tuple below.
DEFAULT_TEXT_EXTENSIONS: tuple[str, ...] = ("*.md", "*.txt", "*.rst")
DEFAULT_OCR_EXTENSIONS: tuple[str, ...] = ("*.pdf",)

# Per-collection ingest manifest: maps relative path → sha256 of file content.
# Used for hash-based dedup so re-running ingestion against an unchanged corpus
# does no embed/upsert work. Stored under data/ so it is gitignored alongside
# the rest of the runtime state.
INGEST_MANIFEST_DIR = Path("data")


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
    extensions: tuple[str, ...] = ("*.md",),
    enable_ocr: bool = False,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Seed documents into Qdrant with deterministic IDs.

    Default behaviour (``extensions=("*.md",)``) is the original markdown-only
    seeder — preserved for existing callers (orchestrator startup, /reindex
    route, sprint-7 tests).

    Week 2 ticket A1 generalises this:
      * ``extensions`` — glob list controlling which files to pull in
        (e.g. ``("*.md", "*.txt", "*.rst")``).
      * ``enable_ocr`` — when True, also route OCR-supported files
        (``*.pdf`` etc.) through ``backend.ocr.extract_text`` and ingest the
        resulting markdown. Degrades gracefully if the OCR sidecar is offline.
      * Hash-based file dedup — a per-collection manifest at
        ``data/ingest_manifest_<collection>.json`` records ``sha256`` of each
        file's content. Files whose hash matches the manifest are skipped
        unless ``force_rebuild=True``.

    Running this twice without ``force_rebuild`` is idempotent both by
    Qdrant point IDs (stable per relative path + chunk index) and by the
    file-content hash manifest (no embed work for unchanged files).

    Uses ``QDRANT_EMBED_MODEL`` (nomic-embed-text, 768-dim) for embeddings,
    not the generation LLM client, to stay consistent with the Qdrant
    collection vector dimensions.
    """
    from backend.llm import OllamaClient

    docs_root = (docs_dir or DOCS_DIR).resolve()
    store = get_vector_store()

    # Use the dedicated embedding model, not the generation LLM.
    embed_client = OllamaClient(model=QDRANT_EMBED_MODEL)

    if not docs_root.is_dir():
        return {
            "agent_id": agent_namespace,
            "chunks": 0,
            "index_size_bytes": 0,
            "index_size_mb": 0.0,
            "source_documents": 0,
            "skipped_unchanged": 0,
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
            "skipped_unchanged": 0,
            "seeded": False,
            "reason": "Qdrant unavailable",
        }

    manifest_file = manifest_path or _default_manifest_path(collection)
    manifest = {} if force_rebuild else _load_manifest(manifest_file)

    if force_rebuild:
        try:
            existing = {c.name for c in store._client.get_collections().collections}
            if collection in existing:
                store._client.delete_collection(collection_name=collection)
                store._collections_initialized.discard(collection)
        except Exception as exc:
            logger.warning(f"Doc seed force rebuild could not clear collection '{collection}': {exc}")

    # Collect candidate files (text + optional OCR), deduplicated, sorted for stable IDs.
    candidate_files: list[tuple[Path, bool]] = []  # (path, needs_ocr)
    seen: set[Path] = set()
    for pattern in extensions:
        for p in sorted(docs_root.rglob(pattern)):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            candidate_files.append((p, False))
    if enable_ocr:
        for pattern in DEFAULT_OCR_EXTENSIONS:
            for p in sorted(docs_root.rglob(pattern)):
                if p in seen or not p.is_file():
                    continue
                seen.add(p)
                candidate_files.append((p, True))

    source_bytes = 0
    total_upserts = 0
    skipped_unchanged = 0
    processed_documents = 0

    for path, needs_ocr in candidate_files:
        rel_path = path.relative_to(docs_root.parent).as_posix()
        raw_bytes = path.read_bytes()
        source_bytes += len(raw_bytes)
        file_hash = hashlib.sha256(raw_bytes).hexdigest()

        # Hash-based dedup — unchanged file, skip all embed/upsert work.
        if manifest.get(rel_path) == file_hash:
            skipped_unchanged += 1
            continue

        if needs_ocr:
            text = await _extract_via_ocr(str(path))
            if text is None:
                logger.warning(
                    f"[doc_seed] OCR unavailable or failed for {rel_path}; skipping. "
                    "Start the GLM-OCR sidecar (port 5002) to ingest this file."
                )
                continue
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                logger.warning(f"[doc_seed] Could not read {rel_path}: {exc}")
                continue

        chunks = chunk_markdown(text, size=chunk_size, overlap=overlap)
        if not chunks:
            continue

        vectors: list[list[float]] = []
        payloads: list[dict[str, Any]] = []
        ids: list[str] = []

        for idx, chunk in enumerate(chunks):
            vec = await embed_client.embed(chunk)
            if not vec:
                continue
            vectors.append(vec)
            payloads.append(
                {
                    "text": chunk,
                    "source": rel_path,
                    "file_path": rel_path,
                    "chunk_index": idx,
                    "content_sha256": file_hash,
                }
            )
            ids.append(str(uuid.UUID(hex=hashlib.sha256(f"{rel_path}:{idx}".encode()).hexdigest()[:32])))

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

        manifest[rel_path] = file_hash
        processed_documents += 1

    _save_manifest(manifest_file, manifest)
    await embed_client.close()
    stored_chunks = store.count(collection)
    return {
        "agent_id": agent_namespace,
        "chunks": stored_chunks if stored_chunks else total_upserts,
        "index_size_bytes": source_bytes,
        "index_size_mb": round(source_bytes / (1024 * 1024), 4),
        "source_documents": len(candidate_files),
        "processed_documents": processed_documents,
        "skipped_unchanged": skipped_unchanged,
        "seeded": True,
        "collection": collection,
    }


# ---------------------------------------------------------------------------
# Manifest helpers (Week 2 ticket A1 — hash-based file dedup)
# ---------------------------------------------------------------------------


def _default_manifest_path(collection: str) -> Path:
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in collection)
    return INGEST_MANIFEST_DIR / f"ingest_manifest_{safe}.json"


def _load_manifest(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"[doc_seed] Could not load ingest manifest {path}: {exc}; treating as empty")
        return {}
    return data if isinstance(data, dict) else {}


def _save_manifest(path: Path, manifest: dict[str, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"[doc_seed] Could not write ingest manifest {path}: {exc}")


async def _extract_via_ocr(file_path: str) -> str | None:
    """Route PDF/image files through backend.ocr (GLM-OCR sidecar)."""
    try:
        from backend import ocr

        if not ocr.is_supported(file_path):
            return None
        return await ocr.extract_text(file_path)
    except Exception as exc:
        logger.warning(f"[doc_seed] OCR extraction failed for {file_path}: {exc}")
        return None
