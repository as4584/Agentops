"""
Tests for backend/knowledge/vendor/ modules:
  - storage.py  (AsyncJsonVectorStore, AsyncJsonKVStore, content_id, _cosine)
  - cache.py    (EmbeddingCache)
  - chunking.py (chunk_by_tokens, _chunk_chars)
"""

from __future__ import annotations

import math

import pytest

# ── content_id ────────────────────────────────────────────────────────────────


class TestContentId:
    def test_deterministic(self):
        from backend.knowledge.vendor.storage import content_id

        assert content_id("hello") == content_id("hello")

    def test_different_content_different_id(self):
        from backend.knowledge.vendor.storage import content_id

        assert content_id("hello") != content_id("world")

    def test_prefix_applied(self):
        from backend.knowledge.vendor.storage import content_id

        result = content_id("text", prefix="doc")
        assert result.startswith("doc-")

    def test_default_prefix(self):
        from backend.knowledge.vendor.storage import content_id

        result = content_id("text")
        assert result.startswith("chunk-")

    def test_id_is_string(self):
        from backend.knowledge.vendor.storage import content_id

        assert isinstance(content_id("test"), str)


# ── _cosine ───────────────────────────────────────────────────────────────────


class TestCosine:
    def _cos(self, a, b):
        from backend.knowledge.vendor.storage import _cosine

        return _cosine(a, b)

    def test_identical_vectors_return_1(self):
        v = [1.0, 0.0, 0.0]
        assert abs(self._cos(v, v) - 1.0) < 1e-9

    def test_orthogonal_vectors_return_0(self):
        assert abs(self._cos([1.0, 0.0], [0.0, 1.0])) < 1e-9

    def test_antiparallel_vectors_return_minus1(self):
        result = self._cos([1.0, 0.0], [-1.0, 0.0])
        assert abs(result - (-1.0)) < 1e-9

    def test_empty_vector_returns_0(self):
        assert self._cos([], []) == 0.0

    def test_mismatched_lengths_return_0(self):
        assert self._cos([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector_returns_0(self):
        assert self._cos([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_known_similarity(self):
        a = [1.0, 1.0]
        b = [1.0, 0.0]
        expected = 1.0 / math.sqrt(2)
        assert abs(self._cos(a, b) - expected) < 1e-9


# ── AsyncJsonVectorStore ──────────────────────────────────────────────────────


class TestAsyncJsonVectorStore:
    @pytest.mark.asyncio
    async def test_upsert_and_query(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "vectors.json", "test_ns_vs")
        await store.upsert_batch(
            [
                ("id1", [1.0, 0.0, 0.0], {"content": "apple"}),
                ("id2", [0.0, 1.0, 0.0], {"content": "banana"}),
            ]
        )
        results = await store.query([1.0, 0.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0]["id"] == "id1"
        assert results[0]["score"] > 0.99

    @pytest.mark.asyncio
    async def test_count_after_insert(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "cnt_ns")
        assert store.count() == 0
        await store.upsert_batch([("a", [1.0], {}), ("b", [0.5], {})])
        assert store.count() == 2

    @pytest.mark.asyncio
    async def test_all_ids(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "ids_ns")
        await store.upsert_batch([("x", [1.0], {}), ("y", [0.0], {})])
        ids = store.all_ids()
        assert set(ids) == {"x", "y"}

    @pytest.mark.asyncio
    async def test_delete_by_prefix(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "del_ns")
        await store.upsert_batch(
            [
                ("doc-aaa", [1.0], {}),
                ("doc-bbb", [0.5], {}),
                ("other-ccc", [0.2], {}),
            ]
        )
        removed = await store.delete_by_prefix("doc-")
        assert removed == 2
        assert store.count() == 1

    @pytest.mark.asyncio
    async def test_persistance_across_instances(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        path = tmp_path / "persist.json"
        s1 = AsyncJsonVectorStore(path, "persist_ns")
        await s1.upsert_batch([("k1", [1.0, 0.0], {"content": "hi"})])
        s2 = AsyncJsonVectorStore(path, "persist_ns2")
        await s2.load()
        assert s2.count() == 1

    @pytest.mark.asyncio
    async def test_query_top_k_ordering(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "order_ns")
        await store.upsert_batch(
            [
                ("best", [1.0, 0.0], {}),
                ("mid", [0.7, 0.7], {}),
                ("worst", [0.0, 1.0], {}),
            ]
        )
        results = await store.query([1.0, 0.0], top_k=3)
        assert results[0]["id"] == "best"
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_load_skips_corrupt_file(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        path = tmp_path / "corrupt.json"
        path.write_text("not-json")
        store = AsyncJsonVectorStore(path, "corrupt_ns")
        await store.load()
        assert store.count() == 0

    @pytest.mark.asyncio
    async def test_upsert_overwrites_existing(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "overwrite_ns")
        await store.upsert_batch([("k1", [1.0, 0.0], {"content": "old"})])
        await store.upsert_batch([("k1", [0.5, 0.5], {"content": "new"})])
        assert store.count() == 1
        results = await store.query([0.5, 0.5], top_k=1)
        assert results[0].get("content") == "new"

    @pytest.mark.asyncio
    async def test_delete_nonexistent_prefix_returns_0(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonVectorStore

        store = AsyncJsonVectorStore(tmp_path / "v.json", "nodel_ns")
        await store.upsert_batch([("item-1", [1.0], {})])
        removed = await store.delete_by_prefix("ghost-")
        assert removed == 0
        assert store.count() == 1


# ── AsyncJsonKVStore ──────────────────────────────────────────────────────────


class TestAsyncJsonKVStore:
    @pytest.mark.asyncio
    async def test_set_and_get(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv_ns")
        await store.set("key1", {"value": 42})
        result = await store.get("key1")
        assert result == {"value": 42}

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv2_ns")
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_batch(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv3_ns")
        await store.set_batch({"a": 1, "b": 2, "c": 3})
        keys = await store.all_keys()
        assert set(keys) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_delete(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv4_ns")
        await store.set("key1", "val")
        await store.delete("key1")
        assert await store.get("key1") is None

    @pytest.mark.asyncio
    async def test_delete_missing_key_no_error(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv5_ns")
        await store.delete("ghost")  # should not raise

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        path = tmp_path / "kv.json"
        s1 = AsyncJsonKVStore(path, "kv6a_ns")
        await s1.set("hello", "world")
        s2 = AsyncJsonKVStore(path, "kv6b_ns")
        result = await s2.get("hello")
        assert result == "world"

    @pytest.mark.asyncio
    async def test_load_skips_corrupt_file(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        path = tmp_path / "kv.json"
        path.write_text("corrupted")
        store = AsyncJsonKVStore(path, "kv7_ns")
        result = await store.get("x")
        assert result is None

    @pytest.mark.asyncio
    async def test_all_keys_empty_store(self, tmp_path):
        from backend.knowledge.vendor.storage import AsyncJsonKVStore

        store = AsyncJsonKVStore(tmp_path / "kv.json", "kv8_ns")
        keys = await store.all_keys()
        assert keys == []


# ── EmbeddingCache ────────────────────────────────────────────────────────────


class TestEmbeddingCache:
    def test_get_miss_returns_none(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        result = cache.get("text", "model")
        assert result is None

    def test_set_and_get(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        vec = [0.1, 0.2, 0.3]
        cache.set("hello", "nomic", vec)
        result = cache.get("hello", "nomic")
        assert result == vec

    def test_different_model_different_entry(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        cache.set("text", "model-a", [1.0])
        cache.set("text", "model-b", [2.0])
        assert cache.get("text", "model-a") == [1.0]
        assert cache.get("text", "model-b") == [2.0]

    def test_stats_tracks_hits_and_misses(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        cache.set("t1", "m", [1.0])
        cache.get("t1", "m")  # hit
        cache.get("t2", "m")  # miss
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_stats_counts_entries(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        cache.set("a", "m", [1.0])
        cache.set("b", "m", [2.0])
        assert cache.stats()["entries"] == 2

    def test_persists_to_disk(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        path = tmp_path / "cache.json"
        c1 = EmbeddingCache(path)
        c1.set("persisted", "model", [9.9])
        c2 = EmbeddingCache(path)
        assert c2.get("persisted", "model") == [9.9]

    def test_loads_corrupt_file_gracefully(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        path = tmp_path / "cache.json"
        path.write_text("broken json!!")
        cache = EmbeddingCache(path)
        assert cache.get("x", "m") is None

    def test_set_batch(self, tmp_path):
        from backend.knowledge.vendor.cache import EmbeddingCache

        cache = EmbeddingCache(tmp_path / "cache.json")
        entries = [
            ("text1", "model", [0.1, 0.2]),
            ("text2", "model", [0.3, 0.4]),
        ]
        cache.set_batch(entries)
        assert cache.get("text1", "model") == [0.1, 0.2]
        assert cache.get("text2", "model") == [0.3, 0.4]
        assert cache.stats()["entries"] == 2


# ── chunk_by_tokens ───────────────────────────────────────────────────────────


class TestChunkByTokens:
    def test_empty_text_returns_empty(self):
        from backend.knowledge.vendor.chunking import chunk_by_tokens

        assert chunk_by_tokens("") == []
        assert chunk_by_tokens("   ") == []

    def test_short_text_is_single_chunk(self):
        from backend.knowledge.vendor.chunking import chunk_by_tokens

        text = "Hello world."
        chunks = chunk_by_tokens(text, max_tokens=512)
        assert len(chunks) == 1
        assert text in chunks[0] or chunks[0] in text

    def test_long_text_is_split(self):
        from backend.knowledge.vendor.chunking import chunk_by_tokens

        # ~3000 chars should be split at 512 tokens (≈2048 chars at 4:1)
        text = "word " * 600  # ~3000 chars
        chunks = chunk_by_tokens(text, max_tokens=128, overlap_tokens=16)
        assert len(chunks) > 1

    def test_all_chunks_non_empty(self):
        from backend.knowledge.vendor.chunking import chunk_by_tokens

        text = "Hello world " * 100
        chunks = chunk_by_tokens(text, max_tokens=64, overlap_tokens=8)
        assert all(c.strip() for c in chunks)

    def test_preserves_content(self):
        from backend.knowledge.vendor.chunking import chunk_by_tokens

        text = "The quick brown fox. " * 50
        chunks = chunk_by_tokens(text, max_tokens=64, overlap_tokens=8)
        # All content should appear in at least one chunk
        combined = " ".join(chunks)
        assert "quick brown fox" in combined


class TestChunkChars:
    def test_short_text_single_chunk(self):
        from backend.knowledge.vendor.chunking import _chunk_chars

        text = "Short text."
        chunks = _chunk_chars(text, chunk_size=1000, overlap=100)
        assert chunks == [text]

    def test_long_text_split(self):
        from backend.knowledge.vendor.chunking import _chunk_chars

        text = "A" * 200
        chunks = _chunk_chars(text, chunk_size=50, overlap=10)
        assert len(chunks) > 1
        # Each chunk should be at most 50 chars
        for chunk in chunks:
            assert len(chunk) <= 50

    def test_overlap_produces_shared_content(self):
        from backend.knowledge.vendor.chunking import _chunk_chars

        text = "abcdefghij" * 10  # 100 chars
        chunks = _chunk_chars(text, chunk_size=20, overlap=5)
        # With overlap, consecutive chunks share some content
        assert len(chunks) > 1

    def test_empty_chunks_filtered(self):
        from backend.knowledge.vendor.chunking import _chunk_chars

        text = "word " * 50
        chunks = _chunk_chars(text, chunk_size=20, overlap=5)
        assert all(c.strip() for c in chunks)
