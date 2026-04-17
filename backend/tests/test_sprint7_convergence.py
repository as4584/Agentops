"""Sprint 7 convergence tests for router alignment and knowledge RAG."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeClient:
    def __init__(self, store: _FakeStore) -> None:
        self._store = store

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=name) for name in self._store._collections])

    def delete_collection(self, collection_name: str) -> None:
        self._store._collections.discard(collection_name)
        self._store._points.pop(collection_name, None)


class _FakeStore:
    def __init__(self) -> None:
        self._collections: set[str] = set()
        self._collections_initialized: set[str] = set()
        self._points: dict[str, dict[str, dict]] = {}
        self._client = _FakeClient(self)

    def ensure_collection(self, collection: str = "", dim: int | None = None) -> None:
        del dim
        coll = collection or "knowledge_agent"
        self._collections.add(coll)
        self._collections_initialized.add(coll)
        self._points.setdefault(coll, {})

    def upsert(self, vectors, payloads, ids=None, collection: str = "", agent_namespace: str = "") -> int:
        del vectors, agent_namespace
        coll = collection or "knowledge_agent"
        self.ensure_collection(coll)
        for idx, payload in enumerate(payloads):
            point_id = ids[idx] if ids else str(idx)
            self._points[coll][point_id] = payload
        return len(payloads)

    def count(self, collection: str = "") -> int:
        coll = collection or "knowledge_agent"
        return len(self._points.get(coll, {}))

    def search(self, query_vector, limit: int = 10, collection: str = "", agent_namespace: str = "", filters=None):
        del query_vector, agent_namespace, filters
        coll = collection or "knowledge_agent"
        payloads = list(self._points.get(coll, {}).values())[:limit]
        return [{"score": 0.9, "payload": payload} for payload in payloads]


@pytest.mark.asyncio
async def test_seed_docs_to_qdrant_is_idempotent(tmp_path: Path) -> None:
    from backend.knowledge.doc_seed import seed_docs_to_qdrant

    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    (docs_dir / "a.md").write_text("# Title\n\n" + "alpha " * 200, encoding="utf-8")
    (docs_dir / "b.md").write_text("# Another\n\n" + "beta " * 200, encoding="utf-8")

    fake_store = _FakeStore()
    mock_llm = MagicMock()
    mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])

    with (
        patch("backend.knowledge.doc_seed.get_vector_store", return_value=fake_store),
        patch("backend.knowledge.doc_seed.QDRANT_AVAILABLE", True),
    ):
        first = await seed_docs_to_qdrant(mock_llm, docs_dir=docs_dir)
        second = await seed_docs_to_qdrant(mock_llm, docs_dir=docs_dir)

    assert first["chunks"] == second["chunks"]
    assert fake_store.count("knowledge_agent") == first["chunks"]


@pytest.mark.asyncio
async def test_context_assembler_retrieve_records_normalises_hits() -> None:
    from backend.knowledge.context_assembler import ContextAssembler

    mock_llm = MagicMock()
    mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    assembler = ContextAssembler(mock_llm)

    fake_store = _FakeStore()
    fake_store.upsert(
        vectors=[[0.1, 0.2, 0.3]],
        payloads=[{"text": "doc text", "source": "docs/SOURCE_OF_TRUTH.md", "chunk_index": 1}],
        ids=["doc-1"],
        collection="knowledge_agent",
    )
    assembler._store = cast(Any, fake_store)

    with patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", True):
        results = await assembler.retrieve_records("source of truth", agent_id="knowledge_agent", limit=3)

    assert results[0]["path"] == "docs/SOURCE_OF_TRUTH.md"
    assert results[0]["chunk_index"] == 1
    assert results[0]["text"] == "doc text"


@pytest.mark.asyncio
async def test_context_assembler_business_profiles_fallback_when_qdrant_down() -> None:
    from backend.knowledge.context_assembler import ContextAssembler

    mock_llm = MagicMock()
    mock_llm.embed = AsyncMock(return_value=[0.1, 0.2, 0.3])
    assembler = ContextAssembler(mock_llm)

    fallback_store = MagicMock()
    fallback_store.search_business_profiles = AsyncMock(
        return_value=[{"business_id": "biz-1", "field": "name", "text": "Acme", "score": 0.9}]
    )

    with (
        patch("backend.knowledge.context_assembler.QDRANT_AVAILABLE", False),
        patch("backend.knowledge.context_assembler._get_fallback_store", return_value=fallback_store),
    ):
        results = await assembler.search_business_profiles("acme", "biz-1", limit=2)

    assert results[0]["business_id"] == "biz-1"
    fallback_store.search_business_profiles.assert_called_once()


@pytest.mark.asyncio
async def test_knowledge_route_uses_context_assembler_for_search() -> None:
    from backend.routes import knowledge as knowledge_routes

    assembler = MagicMock()
    assembler.retrieve_records = AsyncMock(
        return_value=[{"path": "docs/DRIFT_GUARD.md", "chunk_index": 0, "text": "guard rails", "score": 0.7}]
    )

    with patch.object(knowledge_routes, "_assembler", assembler):
        result = await knowledge_routes.knowledge_search(knowledge_routes.SearchRequest(query="guard", top_k=1))

    assembler.retrieve_records.assert_called_once_with("guard", agent_id="knowledge_agent", limit=1)
    assert result[0]["path"] == "docs/DRIFT_GUARD.md"


@pytest.mark.asyncio
async def test_knowledge_route_reindex_uses_qdrant_seed() -> None:
    from backend.routes import knowledge as knowledge_routes

    llm_client = MagicMock()
    with (
        patch.object(knowledge_routes, "_llm_client", llm_client),
        patch("backend.routes.knowledge.seed_docs_to_qdrant", new_callable=AsyncMock) as mock_seed,
    ):
        mock_seed.return_value = {"agent_id": "knowledge_agent", "chunks": 5}
        result = await knowledge_routes.knowledge_reindex()

    mock_seed.assert_called_once_with(llm_client, force_rebuild=True)
    assert result["status"] == "ok"
