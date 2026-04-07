"""
Async-safe JSON-backed vector and key-value stores.
Vendored pattern from LightRAG (HKUDS/LightRAG, MIT License) — specifically
the NanoVectorDBStorage and JsonKVStorage approach, adapted for Agentop.

Key improvements over Agentop's original JSON store:
- Per-namespace asyncio locks prevent concurrent write corruption
- Atomic writes via temp-file + os.replace (no partial writes)
- Separate KV store for metadata — no need to reload all vectors for metadata ops
- Content-addressed IDs for deduplication
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Namespace-scoped async locks (shared across store instances in same process)
# ---------------------------------------------------------------------------
_NS_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lock(namespace: str) -> asyncio.Lock:
    if namespace not in _NS_LOCKS:
        _NS_LOCKS[namespace] = asyncio.Lock()
    return _NS_LOCKS[namespace]


# ---------------------------------------------------------------------------
# Content-addressed ID
# ---------------------------------------------------------------------------


def content_id(content: str, prefix: str = "chunk") -> str:
    """Generate a deterministic MD5-based ID for a piece of content."""
    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    return f"{prefix}-{md5}"


# ---------------------------------------------------------------------------
# Async JSON vector store
# ---------------------------------------------------------------------------


class AsyncJsonVectorStore:
    """Async-safe JSON-backed cosine similarity vector store.

    Data is kept in memory as a flat dict keyed by content ID.
    Writes are atomic (temp rename). Reads acquire a namespace lock.
    """

    def __init__(self, path: Path, namespace: str) -> None:
        self._path = path
        self._ns = namespace
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def load(self) -> None:
        async with _get_lock(self._ns):
            if not self._loaded:
                self._data = self._read_from_disk()
                self._loaded = True

    def _read_from_disk(self) -> dict[str, dict[str, Any]]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text()).get("vectors", {})
        except Exception:
            return {}

    async def upsert_batch(self, items: list[tuple[str, list[float], dict[str, Any]]]) -> None:
        """Insert or replace a batch of (id, vector, metadata) tuples."""
        if not self._loaded:
            await self.load()
        async with _get_lock(self._ns):
            for item_id, vector, meta in items:
                self._data[item_id] = {"vector": vector, **meta}
            self._flush()

    async def delete_by_prefix(self, prefix: str) -> int:
        """Delete all entries whose ID starts with prefix. Returns count removed."""
        if not self._loaded:
            await self.load()
        async with _get_lock(self._ns):
            before = len(self._data)
            self._data = {k: v for k, v in self._data.items() if not k.startswith(prefix)}
            removed = before - len(self._data)
            if removed:
                self._flush()
            return removed

    async def query(self, query_vector: list[float], top_k: int = 4) -> list[dict[str, Any]]:
        """Return top-k entries by cosine similarity."""
        if not self._loaded:
            await self.load()
        scored = []
        for item_id, item in self._data.items():
            score = _cosine(query_vector, item["vector"])
            meta = {k: v for k, v in item.items() if k != "vector"}
            scored.append({"id": item_id, "score": score, **meta})
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return len(self._data)

    def all_ids(self) -> list[str]:
        return list(self._data.keys())

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"vectors": self._data}))
        os.replace(str(tmp), str(self._path))


# ---------------------------------------------------------------------------
# Async JSON KV store (for document metadata / signatures)
# ---------------------------------------------------------------------------


class AsyncJsonKVStore:
    """Async-safe flat JSON key-value store.

    Used to track per-document signatures for incremental index updates —
    only files whose mtime/size changed get re-embedded.
    """

    def __init__(self, path: Path, namespace: str) -> None:
        self._path = path
        self._ns = f"{namespace}_kv"
        self._data: dict[str, Any] = {}
        self._loaded = False

    async def load(self) -> None:
        async with _get_lock(self._ns):
            if not self._loaded:
                self._data = self._read_from_disk()
                self._loaded = True

    def _read_from_disk(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text())
        except Exception:
            return {}

    async def get(self, key: str) -> Any:
        if not self._loaded:
            await self.load()
        return self._data.get(key)

    async def set(self, key: str, value: Any) -> None:
        if not self._loaded:
            await self.load()
        async with _get_lock(self._ns):
            self._data[key] = value
            self._flush()

    async def set_batch(self, entries: dict[str, Any]) -> None:
        if not self._loaded:
            await self.load()
        async with _get_lock(self._ns):
            self._data.update(entries)
            self._flush()

    async def delete(self, key: str) -> None:
        if not self._loaded:
            await self.load()
        async with _get_lock(self._ns):
            self._data.pop(key, None)
            self._flush()

    async def all_keys(self) -> list[str]:
        if not self._loaded:
            await self.load()
        return list(self._data.keys())

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data))
        os.replace(str(tmp), str(self._path))


# ---------------------------------------------------------------------------
# Cosine similarity
# ---------------------------------------------------------------------------


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na * nb else 0.0
