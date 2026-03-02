"""
Knowledge Vector Store — Local semantic index for project knowledge.
===================================================================
Builds a local vector database from project docs/code and performs
semantic retrieval using Ollama embeddings.

Design goals:
- Local-first (no cloud services)
- Deterministic index persistence
- Simple cosine similarity retrieval
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from backend.config import MEMORY_DIR, PROJECT_ROOT
from backend.llm import OllamaClient
from backend.utils import logger


class KnowledgeVectorStore:
    """Persistent local vector store backed by JSON on disk."""

    def __init__(self, llm_client: OllamaClient) -> None:
        self.llm = llm_client
        self._dir = MEMORY_DIR / "knowledge"
        self._index_path = self._dir / "vectors.json"
        self._profiles_path = self._dir / "business_profiles.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._items: list[dict[str, Any]] = []
        self._business_profiles: list[dict[str, Any]] = []
        self._signature: str = ""
        self._loaded = False
        self._load_business_profiles()

    async def ensure_index(self, force_rebuild: bool = False) -> None:
        """Load or build the vector index if needed."""
        current_signature = self._compute_signature()

        if not force_rebuild and self._load_from_disk(current_signature):
            return

        docs = self._collect_documents()
        chunks: list[dict[str, Any]] = []

        for doc in docs:
            for i, chunk in enumerate(self._chunk_text(doc["content"])):
                chunks.append({
                    "path": doc["path"],
                    "chunk_index": i,
                    "text": chunk,
                })

        items: list[dict[str, Any]] = []
        for chunk in chunks:
            embedding = await self.llm.embed(chunk["text"])
            if not embedding:
                continue
            items.append({
                "id": f"{chunk['path']}::{chunk['chunk_index']}",
                "path": chunk["path"],
                "chunk_index": chunk["chunk_index"],
                "text": chunk["text"],
                "embedding": embedding,
            })

        self._items = items
        self._signature = current_signature
        self._loaded = True
        self._save_to_disk()
        logger.info(f"Knowledge index built: files={len(docs)}, chunks={len(items)}")

    async def rebuild_index(self) -> dict[str, int]:
        """Force rebuild vector index and return basic stats."""
        await self.ensure_index(force_rebuild=True)
        return self.stats()

    async def search(self, query: str, top_k: int = 4) -> list[dict[str, Any]]:
        """Retrieve top-k semantically similar chunks for a query."""
        await self.ensure_index()
        if not self._items:
            return []

        query_embedding = await self.llm.embed(query)
        if not query_embedding:
            return []

        scored: list[dict[str, Any]] = []
        for item in self._items:
            score = _cosine_similarity(query_embedding, item["embedding"])
            scored.append({
                "path": item["path"],
                "chunk_index": item["chunk_index"],
                "text": item["text"],
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    async def upsert_business_answer(
        self,
        business_id: str,
        field: str,
        answer: str,
    ) -> None:
        """Embed and persist a business intake answer for semantic retrieval."""
        content = answer.strip()
        if not content:
            return

        text = f"Business {business_id} | {field}: {content}"
        embedding = await self.llm.embed(text)
        if not embedding:
            return

        item = {
            "id": hashlib.sha256(
                f"{business_id}:{field}:{content}".encode("utf-8")
            ).hexdigest(),
            "business_id": business_id,
            "field": field,
            "text": text,
            "embedding": embedding,
        }

        self._business_profiles = [
            existing
            for existing in self._business_profiles
            if not (
                existing.get("business_id") == business_id
                and existing.get("field") == field
            )
        ]
        self._business_profiles.append(item)
        self._save_business_profiles()

    async def search_business_profiles(
        self,
        query: str,
        business_id: str,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Search intake answers for a specific business by semantic similarity."""
        query_embedding = await self.llm.embed(query)
        if not query_embedding:
            return []

        scoped = [
            item for item in self._business_profiles
            if item.get("business_id") == business_id
        ]

        scored: list[dict[str, Any]] = []
        for item in scoped:
            score = _cosine_similarity(query_embedding, item.get("embedding", []))
            scored.append({
                "business_id": item.get("business_id"),
                "field": item.get("field"),
                "text": item.get("text"),
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def _collect_documents(self) -> list[dict[str, str]]:
        """Collect project docs/code eligible for indexing."""
        roots = [
            PROJECT_ROOT / "docs",
            PROJECT_ROOT / "backend",
            PROJECT_ROOT / "frontend" / "src",
        ]
        allowed_suffixes = {".md", ".py", ".ts", ".tsx", ".txt"}
        skip_parts = {
            "node_modules",
            ".next",
            ".venv",
            "__pycache__",
            "backend/logs",
            "backend/memory",
        }

        docs: list[dict[str, str]] = []
        for root in roots:
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
                    continue
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                if any(part in rel for part in skip_parts):
                    continue
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                if not content.strip():
                    continue
                docs.append({"path": rel, "content": content[:200_000]})
        return docs

    def _chunk_text(self, text: str, chunk_size: int = 1200, overlap: int = 200) -> list[str]:
        """Chunk text with overlap for retrieval context continuity."""
        clean = "\n".join(line.rstrip() for line in text.splitlines())
        if len(clean) <= chunk_size:
            return [clean]

        chunks: list[str] = []
        start = 0
        while start < len(clean):
            end = min(len(clean), start + chunk_size)
            chunk = clean[start:end]
            if chunk.strip():
                chunks.append(chunk)
            if end >= len(clean):
                break
            start = max(0, end - overlap)
        return chunks

    def _compute_signature(self) -> str:
        """Compute a deterministic signature of indexable files."""
        hasher = hashlib.sha256()
        roots = [
            PROJECT_ROOT / "docs",
            PROJECT_ROOT / "backend",
            PROJECT_ROOT / "frontend" / "src",
        ]

        paths: list[Path] = []
        for root in roots:
            if root.exists():
                paths.extend([p for p in root.rglob("*") if p.is_file()])

        for path in sorted(paths):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if "node_modules" in rel or ".next" in rel or "__pycache__" in rel:
                continue
            if rel.startswith("backend/logs") or rel.startswith("backend/memory"):
                continue
            stat = path.stat()
            hasher.update(rel.encode("utf-8"))
            hasher.update(str(stat.st_size).encode("utf-8"))
            hasher.update(str(stat.st_mtime_ns).encode("utf-8"))
        return hasher.hexdigest()

    def _load_from_disk(self, signature: str) -> bool:
        """Load persisted index if signature matches."""
        if not self._index_path.exists():
            return False
        try:
            payload = json.loads(self._index_path.read_text())
        except Exception:
            return False

        if payload.get("signature") != signature:
            return False

        self._items = payload.get("items", [])
        self._signature = signature
        self._loaded = True
        logger.info(f"Knowledge index loaded from disk: chunks={len(self._items)}")
        return True

    def _save_to_disk(self) -> None:
        """Persist index for fast startup on next run."""
        payload = {
            "signature": self._signature,
            "items": self._items,
        }
        self._index_path.write_text(json.dumps(payload))

    def _load_business_profiles(self) -> None:
        """Load persisted business profile vectors from disk."""
        if not self._profiles_path.exists():
            self._business_profiles = []
            return
        try:
            payload = json.loads(self._profiles_path.read_text())
            self._business_profiles = payload.get("items", [])
        except Exception:
            self._business_profiles = []

    def _save_business_profiles(self) -> None:
        """Persist business profile vectors."""
        payload = {"items": self._business_profiles}
        self._profiles_path.write_text(json.dumps(payload))

    def stats(self) -> dict[str, int]:
        """Return index statistics for diagnostics endpoints."""
        file_size_bytes = self._index_path.stat().st_size if self._index_path.exists() else 0
        profiles_size_bytes = self._profiles_path.stat().st_size if self._profiles_path.exists() else 0
        return {
            "chunks": len(self._items),
            "file_size_bytes": file_size_bytes,
            "business_profile_vectors": len(self._business_profiles),
            "business_profiles_size_bytes": profiles_size_bytes,
        }


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom == 0:
        return 0.0
    return dot / denom
