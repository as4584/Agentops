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
    _assembler = None


def _require_store() -> KnowledgeVectorStore:
    if _store is None:
        raise HTTPException(status_code=503, detail="Knowledge store unavailable")
    return _store


def _require_assembler() -> ContextAssembler:
    global _assembler
    if _assembler is None and _llm_client is not None:
        _assembler = ContextAssembler(_llm_client)
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


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)


class StaleChunk(BaseModel):
    path: str
    score: float


class AgentScope(BaseModel):
    agent_id: str
    chunks_retrieved: int
    collection: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[str]
    confidence: float
    stale_chunks: list[StaleChunk]
    agent_scope: AgentScope
    sources: list[str]


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
        "legacy_index_present": legacy_stats.get("index_present", False),
        "legacy_index_stale": legacy_stats.get("stale", False),
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


@router.post("/query", response_model=QueryResponse)
async def knowledge_query(req: QueryRequest) -> QueryResponse:
    """
    Full answer-generation endpoint: retrieves context, generates an LLM answer,
    and returns the complete structured contract (answer, citations, confidence,
    stale_chunks, agent_scope) — identical to what the knowledge_agent produces
    internally when routed through the orchestrator.
    """
    assembler = _require_assembler()
    if _llm_client is None:
        raise HTTPException(status_code=503, detail="LLM client unavailable")

    retrieved = await assembler.retrieve_records(
        req.query, agent_id="knowledge_agent", limit=req.top_k
    )

    context_blocks = [
        f"[Source {i}] {item['path']} (score={item['score']:.3f})\n{item['text']}"
        for i, item in enumerate(retrieved, start=1)
    ]

    system_prompt = (
        "You are a local knowledge agent. Use the provided sources to answer. "
        "If the answer is not in sources, say so clearly. "
        "Include a brief 'Sources:' section listing relevant file paths."
    )
    prompt = (
        "Context:\n"
        + ("\n\n".join(context_blocks) if context_blocks else "No indexed context retrieved.")
        + "\n\nUser question:\n"
        + req.query
    )
    answer = await _llm_client.generate(prompt=prompt, system=system_prompt)

    citations = list(dict.fromkeys(item["path"] for item in retrieved if item.get("path")))
    scores = [item.get("score", 0.0) for item in retrieved]
    confidence = round(sum(scores) / len(scores), 4) if scores else 0.0
    stale_chunks = [
        StaleChunk(path=item["path"], score=item.get("score", 0.0))
        for item in retrieved
        if item.get("score", 1.0) < 0.5 and item.get("path")
    ]

    return QueryResponse(
        answer=answer,
        citations=citations,
        confidence=confidence,
        stale_chunks=stale_chunks,
        agent_scope=AgentScope(
            agent_id="knowledge_agent",
            chunks_retrieved=len(retrieved),
            collection="knowledge_agent",
        ),
        sources=citations,
    )
