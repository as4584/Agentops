"""
Qdrant Vector Store — Persistent memory for Agentop agents.
============================================================
Agent-namespaced vector storage using Qdrant for:
- Persistent memory across sessions
- Semantic search over documents and conversation history
- Agent-specific collections with payload filtering

Supports in-memory mode for testing and Docker/remote for production.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from backend.utils import logger

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

    QDRANT_AVAILABLE = True
except ImportError:
    QdrantClient = None  # type: ignore[assignment,misc]
    Distance = None  # type: ignore[assignment]
    FieldCondition = None  # type: ignore[assignment]
    Filter = None  # type: ignore[assignment]
    MatchValue = None  # type: ignore[assignment]
    PointStruct = None  # type: ignore[assignment]
    VectorParams = None  # type: ignore[assignment]
    QDRANT_AVAILABLE = False


class VectorStore:
    """Qdrant-backed vector store with agent namespace isolation."""

    DEFAULT_COLLECTION = "agentop_memory"
    DEFAULT_DIM = 384  # all-MiniLM-L6-v2 dimension

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        in_memory: bool = False,
        default_dim: int = DEFAULT_DIM,
    ) -> None:
        self._dim = default_dim
        self._collections_initialized: set[str] = set()

        if not QDRANT_AVAILABLE:
            logger.warning("[VectorStore] qdrant-client not installed — store disabled")
            self._client = None
            return

        if in_memory:
            self._client = QdrantClient(location=":memory:")  # type: ignore[misc]
            logger.info("[VectorStore] Running in-memory mode (test/dev)")
        else:
            self._client = QdrantClient(host=host, port=port)  # type: ignore[misc]
            logger.info(f"[VectorStore] Connected to Qdrant at {host}:{port}")

    def ensure_collection(
        self,
        collection: str = "",
        dim: int | None = None,
    ) -> None:
        """Create collection if it doesn't exist."""
        if not self._client:
            return
        coll = collection or self.DEFAULT_COLLECTION
        if coll in self._collections_initialized:
            return
        d = dim or self._dim

        existing = [c.name for c in self._client.get_collections().collections]
        if coll not in existing:
            self._client.create_collection(
                collection_name=coll,
                vectors_config=VectorParams(size=d, distance=Distance.COSINE),  # type: ignore[misc]
            )
            logger.info(f"[VectorStore] Created collection: {coll} (dim={d})")
        self._collections_initialized.add(coll)

    def upsert(
        self,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str] | None = None,
        collection: str = "",
        agent_namespace: str = "",
    ) -> int:
        """Insert or update vectors with payloads. Returns count upserted."""
        if not self._client:
            return 0
        coll = collection or self.DEFAULT_COLLECTION
        self.ensure_collection(coll, dim=len(vectors[0]) if vectors else self._dim)

        points = []
        for i, (vec, payload) in enumerate(zip(vectors, payloads)):
            point_id = ids[i] if ids else self._make_id(payload, i)
            if agent_namespace:
                payload["agent_namespace"] = agent_namespace
            payload.setdefault("indexed_at", time.time())
            points.append(PointStruct(id=point_id, vector=vec, payload=payload))  # type: ignore[misc]

        self._client.upsert(collection_name=coll, points=points)
        return len(points)

    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        collection: str = "",
        agent_namespace: str = "",
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search with optional agent namespace filtering."""
        if not self._client:
            return []
        coll = collection or self.DEFAULT_COLLECTION
        self.ensure_collection(coll, dim=len(query_vector))

        # Build filter
        conditions = []
        if agent_namespace:
            conditions.append(FieldCondition(key="agent_namespace", match=MatchValue(value=agent_namespace)))  # type: ignore[misc]
        if filters:
            for key, value in filters.items():
                conditions.append(FieldCondition(key=key, match=MatchValue(value=value)))  # type: ignore[misc]

        query_filter = Filter(must=conditions) if conditions else None  # type: ignore[arg-type]

        response = self._client.query_points(
            collection_name=coll,
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
        )

        return [
            {
                "id": hit.id,
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in response.points
        ]

    def get_by_id(self, point_id: str, collection: str = "") -> dict[str, Any] | None:
        """Retrieve a point by ID."""
        if not self._client:
            return None
        coll = collection or self.DEFAULT_COLLECTION
        results = self._client.retrieve(collection_name=coll, ids=[point_id])
        if results:
            return {"id": results[0].id, "payload": results[0].payload}
        return None

    def delete(
        self,
        ids: list[str],
        collection: str = "",
    ) -> int:
        """Delete points by ID. Returns count deleted."""
        if not self._client:
            return 0
        coll = collection or self.DEFAULT_COLLECTION
        self._client.delete(collection_name=coll, points_selector=ids)  # type: ignore[arg-type]
        return len(ids)

    def count(self, collection: str = "") -> int:
        """Count points in a collection."""
        if not self._client:
            return 0
        coll = collection or self.DEFAULT_COLLECTION
        self.ensure_collection(coll)
        info = self._client.get_collection(coll)
        return info.points_count or 0

    def list_collections(self) -> list[str]:
        """List all collections."""
        if not self._client:
            return []
        return [c.name for c in self._client.get_collections().collections]

    def store_memory(
        self,
        agent_name: str,
        content: str,
        embedding: list[float],
        memory_type: str = "conversation",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """High-level: store a memory item for an agent."""
        payload = {
            "content": content,
            "memory_type": memory_type,
            "agent_namespace": agent_name,
            **(metadata or {}),
        }
        point_id = self._make_id(payload, int(time.time() * 1000))
        self.upsert(
            vectors=[embedding],
            payloads=[payload],
            ids=[point_id],
            agent_namespace=agent_name,
        )
        return point_id

    def recall_memories(
        self,
        agent_name: str,
        query_embedding: list[float],
        limit: int = 10,
        memory_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """High-level: recall relevant memories for an agent."""
        filters = {}
        if memory_type:
            filters["memory_type"] = memory_type
        return self.search(
            query_vector=query_embedding,
            limit=limit,
            agent_namespace=agent_name,
            filters=filters,
        )

    @staticmethod
    def _make_id(payload: dict[str, Any], suffix: int = 0) -> str:
        """Generate a deterministic UUID-format point ID from payload content."""
        content = payload.get("content", "") or str(payload)
        raw = f"{content}:{suffix}"
        h = hashlib.sha256(raw.encode()).hexdigest()[:32]
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
