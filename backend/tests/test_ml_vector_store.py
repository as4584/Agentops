"""Tests for Qdrant Vector Store."""

from __future__ import annotations

import uuid

import pytest

try:
    import qdrant_client  # noqa: F401

    _has_qdrant = True
except ImportError:
    _has_qdrant = False

pytestmark = pytest.mark.skipif(not _has_qdrant, reason="qdrant-client not installed")

from backend.ml.vector_store import VectorStore  # noqa: E402


@pytest.fixture
def store() -> VectorStore:
    return VectorStore(in_memory=True, default_dim=4)


def _uid(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, label))


class TestVectorStore:
    def test_ensure_collection(self, store: VectorStore) -> None:
        store.ensure_collection("test_col", dim=4)
        collections = store.list_collections()
        assert "test_col" in collections

    def test_upsert_and_search(self, store: VectorStore) -> None:
        col = "search_test"
        store.ensure_collection(col, dim=4)
        v1 = [1.0, 0.0, 0.0, 0.0]
        v2 = [0.0, 1.0, 0.0, 0.0]
        id_a, id_b = _uid("a"), _uid("b")
        store.upsert(
            vectors=[v1, v2],
            payloads=[{"text": "hello"}, {"text": "world"}],
            ids=[id_a, id_b],
            collection=col,
        )
        results = store.search(query_vector=v1, limit=1, collection=col)
        assert len(results) == 1
        assert results[0]["id"] == id_a

    def test_get_by_id(self, store: VectorStore) -> None:
        col = "getbyid_test"
        store.ensure_collection(col, dim=4)
        id_x = _uid("x")
        store.upsert(
            vectors=[[1, 0, 0, 0]],
            payloads=[{"k": "v"}],
            ids=[id_x],
            collection=col,
        )
        point = store.get_by_id(id_x, collection=col)
        assert point is not None
        assert point["payload"]["k"] == "v"

    def test_get_by_id_not_found(self, store: VectorStore) -> None:
        col = "notfound_test"
        store.ensure_collection(col, dim=4)
        result = store.get_by_id(_uid("missing"), collection=col)
        assert result is None

    def test_delete(self, store: VectorStore) -> None:
        col = "delete_test"
        store.ensure_collection(col, dim=4)
        id_d1 = _uid("d1")
        store.upsert(
            vectors=[[1, 0, 0, 0]],
            payloads=[{}],
            ids=[id_d1],
            collection=col,
        )
        assert store.count(col) == 1
        store.delete(ids=[id_d1], collection=col)
        assert store.count(col) == 0

    def test_count(self, store: VectorStore) -> None:
        col = "count_test"
        store.ensure_collection(col, dim=4)
        assert store.count(col) == 0
        store.upsert(
            vectors=[[1, 0, 0, 0], [0, 1, 0, 0]],
            payloads=[{}, {}],
            ids=[_uid("c1"), _uid("c2")],
            collection=col,
        )
        assert store.count(col) == 2

    def test_store_memory(self, store: VectorStore) -> None:
        store.store_memory(
            agent_name="soul_core",
            content="I learned something important",
            embedding=[0.5, 0.5, 0.5, 0.5],
            memory_type="reflection",
            metadata={"confidence": 0.9},
        )
        memories = store.recall_memories(
            agent_name="soul_core",
            query_embedding=[0.5, 0.5, 0.5, 0.5],
            limit=5,
        )
        assert len(memories) >= 1
        assert memories[0]["payload"]["agent_namespace"] == "soul_core"

    def test_recall_memories_filtered(self, store: VectorStore) -> None:
        store.store_memory(
            agent_name="devops",
            content="Deploy to prod",
            embedding=[1, 0, 0, 0],
            memory_type="task",
        )
        store.store_memory(
            agent_name="monitor",
            content="CPU spike",
            embedding=[0, 1, 0, 0],
            memory_type="alert",
        )
        devops_memories = store.recall_memories(
            agent_name="devops",
            query_embedding=[1, 0, 0, 0],
            limit=10,
        )
        assert all(m["payload"]["agent_namespace"] == "devops" for m in devops_memories)

    def test_recall_by_memory_type(self, store: VectorStore) -> None:
        store.store_memory(
            agent_name="soul_core",
            content="Deep thought",
            embedding=[1, 0, 0, 0],
            memory_type="reflection",
        )
        store.store_memory(
            agent_name="soul_core",
            content="Task done",
            embedding=[0, 1, 0, 0],
            memory_type="task_result",
        )
        reflections = store.recall_memories(
            agent_name="soul_core",
            query_embedding=[1, 0, 0, 0],
            memory_type="reflection",
            limit=10,
        )
        assert all(m["payload"]["memory_type"] == "reflection" for m in reflections)

    def test_list_collections_empty(self, store: VectorStore) -> None:
        assert isinstance(store.list_collections(), list)

    def test_search_with_filter(self, store: VectorStore) -> None:
        col = "filter_test"
        store.ensure_collection(col, dim=4)
        id_f1, id_f2 = _uid("f1"), _uid("f2")
        store.upsert(
            vectors=[[1, 0, 0, 0], [0.9, 0.1, 0, 0]],
            payloads=[{"category": "a"}, {"category": "b"}],
            ids=[id_f1, id_f2],
            collection=col,
        )
        results = store.search(
            query_vector=[1, 0, 0, 0],
            limit=10,
            collection=col,
            filters={"category": "b"},
        )
        assert len(results) == 1
        assert results[0]["id"] == id_f2
