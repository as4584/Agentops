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
from backend.knowledge.context_assembler import ContextAssembler
from backend.knowledge.doc_seed import seed_docs_to_qdrant

router = APIRouter(prefix="/knowledge", tags=["knowledge"])

_store: KnowledgeVectorStore | None = None
_assembler: ContextAssembler | None = None
_llm_client: Any = None


def set_knowledge_store(store: KnowledgeVectorStore | None, llm_client: Any | None = None) -> None:
    global _assembler, _llm_client, _store
    _store = store
    _llm_client = llm_client
    _assembler = ContextAssembler(llm_client) if llm_client is not None else None


def _require_store() -> KnowledgeVectorStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Knowledge store unavailable")
    return _store


def _require_assembler() -> ContextAssembler:
    if _assembler is None:
        raise HTTPException(status_code=503, detail="Knowledge retrieval unavailable")
    return _assembler


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
    """Return active knowledge retrieval backend stats."""
    assembler = _require_assembler()
    health = assembler.health_check()
    legacy_stats = _store.stats() if _store is not None else {}
    return {
        "backend": "context_assembler",
        **health,
        "legacy_chunks": legacy_stats.get("chunks", 0),
        "legacy_business_profile_vectors": legacy_stats.get("business_profile_vectors", 0),
    }


@router.post("/search", response_model=list[SearchResult])
async def knowledge_search(req: SearchRequest) -> list[dict[str, Any]]:
    """Semantic search over the project knowledge index."""
    assembler = _require_assembler()
    return await assembler.retrieve_records(req.query, agent_id="knowledge_agent", limit=req.top_k)


@router.post("/reindex")
async def knowledge_reindex() -> dict[str, Any]:
    """Force reseed Qdrant from project docs."""
    if _llm_client is None:
        raise HTTPException(status_code=503, detail="LLM client unavailable")
    stats = await seed_docs_to_qdrant(_llm_client, force_rebuild=True)
    return {"status": "ok", "stats": stats}


@router.get("/search")
async def knowledge_search_get(
    q: str = Query(..., min_length=1, max_length=2000),
    top_k: int = Query(default=5, ge=1, le=20),
) -> list[dict[str, Any]]:
    """GET variant for browser / curl convenience."""
    assembler = _require_assembler()
    return await assembler.retrieve_records(q, agent_id="knowledge_agent", limit=top_k)
