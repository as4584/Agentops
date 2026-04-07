"""
MD5-keyed disk cache for LLM/embedding responses.
Vendored pattern from LightRAG (HKUDS/LightRAG, MIT License) — handle_cache / save_to_cache.

Eliminates redundant Ollama embedding calls for unchanged content.
Cache file: backend/memory/knowledge/embed_cache.json
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any


def _cache_key(*args: Any) -> str:
    """Deterministic MD5 key from arbitrary args."""
    serialized = json.dumps(args, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Disk-persisted cache for embedding vectors keyed by text + model.

    Cache layout: {md5_key: {"embedding": [...], "model": "...", "ts": float}}
    Atomic writes prevent corruption on crash mid-write.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, dict[str, Any]] = {}
        self._loaded = False
        self._hits = 0
        self._misses = 0

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except Exception:
                self._data = {}
        self._loaded = True

    def get(self, text: str, model: str) -> list[float] | None:
        self._ensure_loaded()
        key = _cache_key(text, model)
        entry = self._data.get(key)
        if entry:
            self._hits += 1
            return entry.get("embedding")
        self._misses += 1
        return None

    def set(self, text: str, model: str, embedding: list[float]) -> None:
        self._ensure_loaded()
        key = _cache_key(text, model)
        self._data[key] = {
            "embedding": embedding,
            "model": model,
            "ts": time.time(),
        }
        self._flush()

    def set_batch(self, entries: list[tuple[str, str, list[float]]]) -> None:
        """Persist multiple (text, model, embedding) tuples in one write."""
        self._ensure_loaded()
        for text, model, embedding in entries:
            key = _cache_key(text, model)
            self._data[key] = {"embedding": embedding, "model": model, "ts": time.time()}
        self._flush()

    def stats(self) -> dict[str, int]:
        self._ensure_loaded()
        return {
            "entries": len(self._data),
            "hits": self._hits,
            "misses": self._misses,
        }

    def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data))
        os.replace(str(tmp), str(self._path))
