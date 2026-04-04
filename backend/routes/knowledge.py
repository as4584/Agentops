"""
Knowledge Search Routes — REST API for semantic search over project knowledge.
===============================================================================
Exposes the KnowledgeVectorStore as queryable endpoints so external tools,
the Discord bot, and the dashboard can search the local knowledge index.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.knowledge import KnowledgeVectorStore

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_store: KnowledgeVectorStore | None = None


def set_knowledge_store(store: KnowledgeVectorStore | None) -> None:
    global _store
    _store = store


def _require_store() -> KnowledgeVectorStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Knowledge store unavailable")
    return _store


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchResult(BaseModel):
    path: str
    chunk_index: int
    text: str
    score: float


@router.get("/stats")
async def knowledge_stats() -> dict[str, Any]:
    """Return index statistics (chunk count, file count, signature)."""
    store = _require_store()
    return store.stats()


@router.post("/search", response_model=list[SearchResult])
async def knowledge_search(req: SearchRequest) -> list[dict[str, Any]]:
    """Semantic search over the project knowledge index."""
    store = _require_store()
    results = await store.search(req.query, top_k=req.top_k)
    return results


@router.post("/reindex")
async def knowledge_reindex() -> dict[str, Any]:
    """Force rebuild vector index from project docs."""
    store = _require_store()
    stats = await store.rebuild_index()
    return {"status": "ok", "stats": stats}


@router.get("/search")
async def knowledge_search_get(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> list[dict[str, Any]]:
    """GET variant for browser / curl convenience."""
    store = _require_store()
    return await store.search(q, top_k=top_k)
