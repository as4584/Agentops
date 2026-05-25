"""
Hybrid retrieval engine — RRF merge of dense (Qdrant) + sparse (BM25).

Dense path:  ContextAssembler.retrieve_records() → normalised Qdrant hits
Sparse path: BM25Index.search() → corpus chunks scored by BM25Okapi
Merge:       Reciprocal Rank Fusion  (score = Σ 1 / (k + rank))

Falls back to dense-only silently when BM25 index is absent or unavailable.
Never raises — always returns a list.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from backend.knowledge.bm25_index import BM25Index

if TYPE_CHECKING:
    from backend.knowledge.context_assembler import ContextAssembler

logger = logging.getLogger(__name__)

# Standard RRF constant — rank lists of ~20 results, k=60 is conventional.
RRF_K = 60

# How many results to pull from each retrieval source before merging.
DENSE_TOP_K = 20
SPARSE_TOP_K = 20


class RetrievalEngine:
    """
    Coordinates dense + sparse retrieval and merges via RRF.

    Args:
        context_assembler: ContextAssembler instance — used for the dense path.
        bm25_index:        BM25Index instance — used for the sparse path.
        dense_top_k:       Results to fetch from Qdrant before merge.
        sparse_top_k:      Results to fetch from BM25 before merge.
    """

    def __init__(
        self,
        context_assembler: ContextAssembler,
        bm25_index: BM25Index,
        dense_top_k: int = DENSE_TOP_K,
        sparse_top_k: int = SPARSE_TOP_K,
    ) -> None:
        self.assembler = context_assembler
        self.bm25 = bm25_index
        self.dense_top_k = dense_top_k
        self.sparse_top_k = sparse_top_k

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        agent_scope: str | None = None,
        corpus_filter: list[str] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Hybrid retrieval with RRF merge.
        Falls back to dense-only if BM25 unavailable.
        Never raises — always returns a list.
        """
        agent_id = agent_scope or "knowledge_agent"

        # --- Dense retrieval via ContextAssembler (Qdrant) ---
        try:
            dense_hits: list[dict[str, Any]] = await self.assembler.retrieve_records(
                query=query,
                agent_id=agent_id,
                limit=self.dense_top_k,
            )
        except Exception as exc:
            logger.error(f"[RetrievalEngine] Dense search failed: {exc}")
            dense_hits = []

        # Optional corpus prefix filter on dense results
        if corpus_filter and dense_hits:
            dense_hits = [h for h in dense_hits if any(str(h.get("path", "")).startswith(p) for p in corpus_filter)]

        # --- Sparse retrieval via BM25 ---
        sparse_hits: list[dict[str, Any]] = []
        if self.bm25.available:
            try:
                sparse_hits = self.bm25.search(
                    query=query,
                    top_k=self.sparse_top_k,
                    agent_scope=agent_scope,
                    source_prefix=corpus_filter,
                )
            except Exception as exc:
                logger.warning(f"[RetrievalEngine] BM25 search failed: {exc} — falling back to dense-only")
        else:
            logger.info("[RetrievalEngine] BM25 unavailable — dense-only")

        # --- RRF merge ---
        if sparse_hits:
            merged = self._reciprocal_rank_fusion(dense_hits, sparse_hits)
            method = "hybrid_rrf"
        else:
            merged = dense_hits
            method = "dense_only"

        logger.info(
            f"[RetrievalEngine] method={method} "
            f"dense={len(dense_hits)} sparse={len(sparse_hits)} "
            f"merged={len(merged)} query='{query[:60]}'"
        )

        # Attach retrieval method to each hit for observability
        for hit in merged:
            hit["retrieval_method"] = method

        return merged[:top_k]

    # ----------------------------------------------------------------
    # RRF internals
    # ----------------------------------------------------------------

    def _reciprocal_rank_fusion(
        self,
        dense: list[dict[str, Any]],
        sparse: list[dict[str, Any]],
        k: int = RRF_K,
    ) -> list[dict[str, Any]]:
        """
        RRF score = sum(1 / (k + rank)) across result lists.
        Chunks appearing in both lists receive a double boost.

        Join key priority:
          1. ``chunk_id`` field (set by BM25Index and doc_seed)
          2. ``path::chunk_index`` composite (Qdrant normalised hits)
          3. Positional fallback (``dense_N`` / ``sparse_N``)
        """
        scores: dict[str, float] = {}
        chunk_map: dict[str, dict[str, Any]] = {}

        for rank, hit in enumerate(dense):
            cid = hit.get("chunk_id") or f"{hit.get('path', '')}::{hit.get('chunk_index', rank)}"
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            chunk_map[cid] = hit

        for rank, hit in enumerate(sparse):
            cid = hit.get("chunk_id") or f"{hit.get('source', '')}::{rank}"
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in chunk_map:
                # Normalise BM25 chunk fields to the shared schema
                chunk_map[cid] = {
                    "path": hit.get("source", ""),
                    "text": hit.get("text", ""),
                    "score": hit.get("bm25_score", 0.0),
                    "chunk_index": 0,
                    **hit,
                }

        ranked_ids = sorted(scores, key=lambda x: scores[x], reverse=True)

        return [{**chunk_map[cid], "rrf_score": round(scores[cid], 6)} for cid in ranked_ids]

    # ----------------------------------------------------------------
    # Health
    # ----------------------------------------------------------------

    def retrieval_health(self) -> dict[str, Any]:
        """
        Called by monitor_agent and /health/deps.
        Returns structured state of both retrieval paths.
        """
        return {
            "dense_available": True,  # if assembler is up, dense is up
            "bm25_available": self.bm25.available,
            "bm25_chunk_count": self.bm25.chunk_count,
            "active_method": ("hybrid_rrf" if self.bm25.available else "dense_only"),
        }
