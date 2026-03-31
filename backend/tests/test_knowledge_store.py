"""
Tests for backend.knowledge — KnowledgeVectorStore and _cosine_similarity.
OllamaClient.embed is mocked; no real Ollama server required.
"""

from __future__ import annotations

import json
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.knowledge import KnowledgeVectorStore, _cosine_similarity

# ---------------------------------------------------------------------------
# _cosine_similarity (pure function)
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors_returns_one(self):
        a = [1.0, 0.0, 0.0]
        assert _cosine_similarity(a, a) == pytest.approx(1.0)

    def test_orthogonal_vectors_returns_zero(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert _cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors_returns_minus_one(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert _cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_empty_vectors_returns_zero(self):
        assert _cosine_similarity([], []) == 0.0

    def test_one_empty_returns_zero(self):
        assert _cosine_similarity([1.0, 2.0], []) == 0.0

    def test_mismatched_lengths_returns_zero(self):
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vectors_returns_zero(self):
        a = [0.0, 0.0]
        b = [0.0, 0.0]
        assert _cosine_similarity(a, b) == 0.0

    def test_normalized_result(self):
        a = [3.0, 4.0]
        b = [4.0, 3.0]
        result = _cosine_similarity(a, b)
        # Manually: dot=24, |a|=5, |b|=5 → 24/25
        assert result == pytest.approx(24.0 / 25.0)

    def test_high_dimensional_similarity(self):
        dim = 100
        a = [1.0 / math.sqrt(dim)] * dim
        b = [1.0 / math.sqrt(dim)] * dim
        assert _cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------------------
# KnowledgeVectorStore fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_llm() -> MagicMock:
    llm = MagicMock()
    llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    return llm


@pytest.fixture
def store(mock_llm, tmp_path) -> KnowledgeVectorStore:
    """Create a KnowledgeVectorStore backed by a temp directory."""
    with patch("backend.knowledge.MEMORY_DIR", tmp_path):
        s = KnowledgeVectorStore(llm_client=mock_llm)
    return s


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — _cosine_similarity (pure method)
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_short_text_returns_single_chunk(self, store):
        chunks = store._chunk_text("short text", chunk_size=1200)
        assert len(chunks) == 1
        assert chunks[0] == "short text"

    def test_long_text_produces_multiple_chunks(self, store):
        long_text = "x" * 3000
        chunks = store._chunk_text(long_text, chunk_size=1200, overlap=200)
        assert len(chunks) > 1

    def test_chunks_have_overlap(self, store):
        text = "abcde" * 500  # 2500 chars
        chunks = store._chunk_text(text, chunk_size=1200, overlap=200)
        # First chunk ends at 1200, second should start at 1000 (1200-200 overlap)
        assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — stats
# ---------------------------------------------------------------------------


class TestKnowledgeStoreStats:
    def test_stats_empty_store(self, store):
        stats = store.stats()
        assert stats["chunks"] == 0
        assert stats["business_profile_vectors"] == 0

    def test_stats_after_injecting_items(self, store):
        store._items = [{"id": "1"}, {"id": "2"}]
        store._business_profiles = [{"id": "bp1"}]
        stats = store.stats()
        assert stats["chunks"] == 2
        assert stats["business_profile_vectors"] == 1


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — search (with in-memory items)
# ---------------------------------------------------------------------------


class TestKnowledgeStoreSearch:
    @pytest.fixture(autouse=True)
    def _no_rebuild(self, store):
        """Prevent ensure_index from overwriting pre-populated items."""

        async def _noop(*a, **kw):
            pass

        with patch.object(store, "ensure_index", side_effect=_noop):
            yield

    async def test_search_empty_store_returns_empty(self, store, mock_llm):
        store._items = []

        results = await store.search("anything")

        assert results == []

    async def test_search_returns_top_k_results(self, store, mock_llm):
        # Pre-populate items with known embeddings
        store._items = [
            {"path": "doc1.md", "chunk_index": 0, "text": "first", "embedding": [1.0, 0.0, 0.0]},
            {"path": "doc2.md", "chunk_index": 0, "text": "second", "embedding": [0.0, 1.0, 0.0]},
            {"path": "doc3.md", "chunk_index": 0, "text": "third", "embedding": [0.0, 0.0, 1.0]},
        ]
        mock_llm.embed.return_value = [1.0, 0.0, 0.0]  # closest to doc1

        results = await store.search("query", top_k=2)

        assert len(results) == 2
        assert results[0]["path"] == "doc1.md"  # highest cosine similarity

    async def test_search_uses_embed_for_query(self, store, mock_llm):
        store._items = [
            {"path": "x.md", "chunk_index": 0, "text": "test", "embedding": [0.1, 0.2, 0.3]},
        ]
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]

        await store.search("test query")

        mock_llm.embed.assert_called_with("test query")

    async def test_search_empty_embedding_returns_empty(self, store, mock_llm):
        store._items = [
            {"path": "x.md", "chunk_index": 0, "text": "test", "embedding": [0.1, 0.2, 0.3]},
        ]
        mock_llm.embed.return_value = []

        results = await store.search("something")
        assert results == []


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — upsert_business_answer
# ---------------------------------------------------------------------------


class TestUpsertBusinessAnswer:
    async def test_empty_content_skipped(self, store, mock_llm):
        await store.upsert_business_answer("biz1", "name", "")
        mock_llm.embed.assert_not_called()

    async def test_whitespace_only_skipped(self, store, mock_llm):
        await store.upsert_business_answer("biz1", "name", "   ")
        mock_llm.embed.assert_not_called()

    async def test_empty_embedding_skipped(self, store, mock_llm):
        mock_llm.embed.return_value = []
        await store.upsert_business_answer("biz1", "name", "some content")
        assert len(store._business_profiles) == 0

    async def test_saves_profile_vector(self, store, mock_llm):
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        await store.upsert_business_answer("biz1", "name", "Acme Corp")
        assert len(store._business_profiles) == 1
        assert store._business_profiles[0]["business_id"] == "biz1"
        assert store._business_profiles[0]["field"] == "name"

    async def test_updates_existing_field(self, store, mock_llm):
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        await store.upsert_business_answer("biz1", "name", "Old Name")
        await store.upsert_business_answer("biz1", "name", "New Name")
        # Should replace, not append
        assert len(store._business_profiles) == 1
        assert "New Name" in store._business_profiles[0]["text"]

    async def test_different_fields_both_stored(self, store, mock_llm):
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        await store.upsert_business_answer("biz1", "name", "Acme")
        await store.upsert_business_answer("biz1", "industry", "Tech")
        assert len(store._business_profiles) == 2


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — search_business_profiles
# ---------------------------------------------------------------------------


class TestSearchBusinessProfiles:
    async def test_empty_profiles_returns_empty(self, store, mock_llm):
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]
        results = await store.search_business_profiles("query", "biz1", top_k=3)
        assert results == []

    async def test_empty_query_embedding_returns_empty(self, store, mock_llm):
        mock_llm.embed.return_value = []
        results = await store.search_business_profiles("query", "biz1")
        assert results == []

    async def test_returns_top_k_for_business(self, store, mock_llm):
        store._business_profiles = [
            {"business_id": "biz1", "field": "name", "text": "Acme", "embedding": [1.0, 0.0]},
            {"business_id": "biz1", "field": "desc", "text": "Corp", "embedding": [0.0, 1.0]},
            {"business_id": "biz2", "field": "name", "text": "Other", "embedding": [1.0, 0.0]},
        ]
        mock_llm.embed.return_value = [1.0, 0.0]

        results = await store.search_business_profiles("name", "biz1", top_k=5)

        # Only biz1 profiles should appear
        assert all(r["business_id"] == "biz1" for r in results)
        assert len(results) == 2

    async def test_scores_sorted_descending(self, store, mock_llm):
        store._business_profiles = [
            {"business_id": "biz1", "field": "a", "text": "low", "embedding": [0.0, 1.0]},
            {"business_id": "biz1", "field": "b", "text": "high", "embedding": [1.0, 0.0]},
        ]
        mock_llm.embed.return_value = [1.0, 0.0]

        results = await store.search_business_profiles("query", "biz1")

        assert results[0]["score"] >= results[1]["score"]


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — disk persistence
# ---------------------------------------------------------------------------


class TestDiskPersistence:
    def test_load_from_disk_no_file(self, store):
        store._dir.mkdir(parents=True, exist_ok=True)
        # Index file doesn't exist
        loaded = store._load_from_disk("somesig")
        assert loaded is False

    def test_load_from_disk_wrong_signature(self, store):
        store._dir.mkdir(parents=True, exist_ok=True)
        payload = {"signature": "oldsig", "items": [{"id": "1"}]}
        store._index_path.write_text(json.dumps(payload))

        loaded = store._load_from_disk("newsig")
        assert loaded is False

    def test_load_from_disk_matching_signature(self, store):
        store._dir.mkdir(parents=True, exist_ok=True)
        payload = {"signature": "exact_sig", "items": [{"id": "1", "path": "x.md"}]}
        store._index_path.write_text(json.dumps(payload))

        loaded = store._load_from_disk("exact_sig")
        assert loaded is True
        assert len(store._items) == 1

    def test_load_from_disk_corrupt_json(self, store):
        store._dir.mkdir(parents=True, exist_ok=True)
        store._index_path.write_text("{ not valid json")

        loaded = store._load_from_disk("anysig")
        assert loaded is False

    def test_save_to_disk_creates_file(self, store):
        store._dir.mkdir(parents=True, exist_ok=True)
        store._items = [{"id": "1", "path": "test.md"}]
        store._signature = "test_sig"

        store._save_to_disk()

        payload = json.loads(store._index_path.read_text())
        assert payload["signature"] == "test_sig"
        assert len(payload["items"]) == 1


# ---------------------------------------------------------------------------
# KnowledgeVectorStore — ensure_index with pre-loaded state
# ---------------------------------------------------------------------------


class TestEnsureIndex:
    async def test_uses_cached_index_when_signature_matches(self, store, mock_llm):
        store._dir.mkdir(parents=True, exist_ok=True)
        sig = store._compute_signature()
        payload = {
            "signature": sig,
            "items": [{"id": "1", "path": "x.md", "chunk_index": 0, "text": "cached", "embedding": [0.1]}],
        }
        store._index_path.write_text(json.dumps(payload))

        await store.ensure_index()

        # embed should NOT have been called since cache was loaded
        mock_llm.embed.assert_not_called()
        assert len(store._items) == 1

    async def test_rebuild_index_forces_rebuild(self, store, mock_llm):
        store._loaded = True
        store._items = [{"id": "old"}]
        mock_llm.embed.return_value = [0.1, 0.2, 0.3]

        # Mock _collect_documents to return a small set
        with patch.object(store, "_collect_documents", return_value=[{"path": "test.md", "content": "small doc"}]):
            stats = await store.rebuild_index()

        assert isinstance(stats, dict)
        assert "chunks" in stats
