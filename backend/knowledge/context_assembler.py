"""
ContextAssembler — System-wide RAG context retrieval for all agents.
====================================================================
Sprint 4: replaces the knowledge_agent-only retrieval path with a
unified service that any agent can call.

Retrieval priority:
  1. Agent-namespaced Qdrant collection  (agent-specific memory/observations)
  2. Global Qdrant collections           (docs, knowledge_agent)
  3. JSON KnowledgeVectorStore fallback  (when Qdrant is unavailable)

Usage::

    assembler = ContextAssembler(llm_client)
    context_str = await assembler.retrieve(query="restart nginx", agent_id="devops_agent")
    ingested = await assembler.ingest_memory(agent_id="devops_agent", content="nginx restarted OK")
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.llm import OllamaClient

from backend.config import (
    ACTIVE_RUNTIME_PROFILE,
    KNOWN_EMBED_DIMS,
    KNOWLEDGE_JSON_FALLBACK_ENABLED,
    QDRANT_DEFAULT_DIM,
    QDRANT_EMBED_MODEL,
    QDRANT_HOST,
    QDRANT_IN_MEMORY,
    QDRANT_PORT,
    RETRIEVAL_MODE,
)
from backend.ml.vector_store import QDRANT_AVAILABLE, VectorStore

logger = logging.getLogger(__name__)

# Lazy imports to avoid circular dependency at module load time.
# Both are resolved inside __init__ after the base assembler is fully constructed.
from backend.knowledge.bm25_index import BM25Index  # noqa: E402
from backend.knowledge.retrieval_engine import RetrievalEngine  # noqa: E402

# Module-level singleton — shared across all agents in the same process.
_vector_store: VectorStore | None = None


def validate_embedding_startup() -> list[str]:
    """Validate embedding model / dimension consistency at startup.

    Returns a list of warning strings.  An empty list means the config is
    self-consistent.  Warnings are also emitted via ``logger.warning`` so they
    appear in startup logs even if the caller ignores the return value.

    Checks performed:
    1. QDRANT_EMBED_MODEL is set to a non-empty value.
    2. QDRANT_DEFAULT_DIM is > 0.
    3. If the model name is in the KNOWN_EMBED_DIMS table, the configured dim
       matches the expected dim for that model.
    """
    warnings: list[str] = []

    if not QDRANT_EMBED_MODEL:
        msg = "QDRANT_EMBED_MODEL is empty — embedding model is unset"
        logger.warning("EmbeddingStartup: %s", msg)
        warnings.append(msg)

    if QDRANT_DEFAULT_DIM <= 0:
        msg = f"QDRANT_DEFAULT_DIM={QDRANT_DEFAULT_DIM} is invalid — must be > 0"
        logger.warning("EmbeddingStartup: %s", msg)
        warnings.append(msg)

    known_dim = KNOWN_EMBED_DIMS.get(QDRANT_EMBED_MODEL.lower())
    if known_dim is not None and known_dim != QDRANT_DEFAULT_DIM:
        msg = (
            f"Dimension mismatch: QDRANT_EMBED_MODEL={QDRANT_EMBED_MODEL!r} "
            f"expects dim={known_dim} but QDRANT_DEFAULT_DIM={QDRANT_DEFAULT_DIM}. "
            "Recreate Qdrant collections or update QDRANT_DEFAULT_DIM."
        )
        logger.warning("EmbeddingStartup: %s", msg)
        warnings.append(msg)

    if not warnings:
        logger.info(
            "EmbeddingStartup: config OK — model=%r dim=%d",
            QDRANT_EMBED_MODEL,
            QDRANT_DEFAULT_DIM,
        )

    return warnings


def get_vector_store() -> VectorStore:
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore(
            host=QDRANT_HOST,
            port=QDRANT_PORT,
            in_memory=QDRANT_IN_MEMORY,
            default_dim=QDRANT_DEFAULT_DIM,
        )
    return _vector_store


# Separate fallback singleton — only created when Qdrant is unavailable.
_fallback_store: Any = None


def _get_fallback_store(llm_client: Any) -> Any:
    """Return the KnowledgeVectorStore singleton for fallback retrieval."""
    if not KNOWLEDGE_JSON_FALLBACK_ENABLED:
        return None
    global _fallback_store
    if _fallback_store is None:
        try:
            from backend.knowledge import KnowledgeVectorStore

            _fallback_store = KnowledgeVectorStore(llm_client)
        except Exception as exc:
            logger.warning(f"ContextAssembler: failed to init fallback KnowledgeVectorStore: {exc}")
    return _fallback_store


class ContextAssembler:
    """
    Unified RAG retrieval service for any Agentop agent.

    Each agent gets its own Qdrant collection (named by ``agent_id``) plus
    access to shared global collections (docs, knowledge_agent).  If Qdrant
    is not running, the service transparently falls back to the JSON
    KnowledgeVectorStore so agents never fail completely due to RAG.
    """

    # Collections searched for every agent regardless of agent_id.
    GLOBAL_COLLECTIONS: list[str] = ["docs", "knowledge_agent"]

    # Class-level counter: total JSON-fallback retrievals since process start.
    # Exposed via health_check() and the /metrics endpoint for operator observability.
    _fallback_count: int = 0

    def __init__(self, llm_client: OllamaClient) -> None:
        self._llm = llm_client
        self._store = get_vector_store()
        if not QDRANT_AVAILABLE:
            logger.warning(
                "ContextAssembler: qdrant-client not installed. "
                "All retrieval will use JSON KnowledgeVectorStore fallback. "
                "Install qdrant-client and run Qdrant to enable vector memory."
            )
        elif self._store._client is None:
            logger.warning(
                f"ContextAssembler: Qdrant client not connected (host={QDRANT_HOST}:{QDRANT_PORT}). "
                "Retrieval will fall back to JSON KnowledgeVectorStore until Qdrant is reachable."
            )

        # Sprint 2: BM25 sparse index + hybrid RRF retrieval.
        # load() is a no-op if the persisted index doesn't exist yet;
        # call build_bm25_from_qdrant() once after doc_seed to populate it.
        self._bm25   = BM25Index()
        self._engine = RetrievalEngine(
            context_assembler=self,
            bm25_index=self._bm25,
        )
        self._bm25.load()

        # Sprint 4: corpus gap enforcement.
        from backend.knowledge.corpus_gap import CorpusGapHandler  # noqa: PLC0415
        self._gap_handler = CorpusGapHandler()

    def health_check(self) -> dict[str, Any]:
        """
        Return the current health state of the vector retrieval backend.

        Used by server lifespan and monitoring routes to surface Qdrant status.

        Returns a dict with keys:
            qdrant_available (bool): qdrant-client is installed and client is connected.
            fallback_active (bool): retrieval is operating on JSON KnowledgeVectorStore.
            host (str): configured Qdrant host:port.
            in_memory (bool): whether in-memory mode is active.
            collections (list[str]): known initialized collection names.
        """
        connected = bool(QDRANT_AVAILABLE and self._store._client is not None)
        try:
            collections = list(self._store._collections_initialized) if connected else []
        except Exception:
            collections = []
        return {
            "qdrant_available": connected,
            "fallback_active": not connected,
            "fallback_enabled": KNOWLEDGE_JSON_FALLBACK_ENABLED,
            "fallback_count": ContextAssembler._fallback_count,
            # Counts search/upsert calls that returned empty because the client was None.
            # Non-zero while Qdrant is down even if no retrieval queries were made.
            "vector_store_fallback_count": VectorStore._silent_fallback_count,
            "host": f"{QDRANT_HOST}:{QDRANT_PORT}",
            "in_memory": QDRANT_IN_MEMORY,
            "collections": collections,
            "runtime_profile": ACTIVE_RUNTIME_PROFILE,
            "retrieval_mode": RETRIEVAL_MODE,
        }

    def _source_prefix_filter(self) -> list[str] | None:
        if RETRIEVAL_MODE == "deep_index":
            return None
        return ["docs/"]

    async def search(
        self,
        query: str,
        top_k: int = 10,
        agent_scope: str | None = None,
        source_prefix: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Hybrid public search API — delegates to RetrievalEngine (RRF merge).
        Falls back to dense-only when BM25 index is absent.
        Returns normalised hit dicts compatible with retrieve_records().
        """
        return await self._engine.retrieve(
            query=query,
            agent_scope=agent_scope,
            corpus_filter=source_prefix,
            top_k=top_k,
        )

    async def build_bm25_from_qdrant(
        self,
        collection: str = "knowledge_agent",
        force_rebuild: bool = True,
    ) -> int:
        """
        Pull all chunks from Qdrant and rebuild the BM25 index.
        Call once after doc_seed.py runs, or when the corpus changes.
        Returns the number of chunks indexed.
        """
        chunks = await self._fetch_all_chunks_from_qdrant(collection=collection)
        self._bm25.build(chunks, force_rebuild=force_rebuild)
        return self._bm25.chunk_count

    async def _fetch_all_chunks_from_qdrant(
        self,
        collection: str = "knowledge_agent",
        batch_sz: int = 500,
    ) -> list[dict[str, Any]]:
        """
        Scroll all points from Qdrant and map to BM25 chunk schema.
        Uses raw Qdrant client scroll — VectorStore has no scroll wrapper.
        """
        if not QDRANT_AVAILABLE or self._store._client is None:
            logger.warning(
                "[ContextAssembler] Qdrant unavailable — BM25 rebuild skipped"
            )
            return []

        chunks: list[dict[str, Any]] = []
        offset = None

        while True:
            try:
                results, next_offset = self._store._client.scroll(
                    collection_name=collection,
                    limit=batch_sz,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception as exc:
                logger.warning(
                    f"[ContextAssembler] Qdrant scroll failed: {exc}"
                )
                break

            for point in results:
                p = point.payload or {}
                chunks.append({
                    "chunk_id":     str(point.id),
                    "text":         p.get("text", ""),
                    "source":       p.get("source", p.get("file_path", "")),
                    "section":      p.get("section", ""),
                    "agent_scope":  p.get("agent_scope", ["all"]),
                    "last_indexed": p.get("last_indexed", ""),
                })

            if next_offset is None:
                break
            offset = next_offset

        logger.info(
            f"[ContextAssembler] Fetched {len(chunks)} chunks "
            f"from Qdrant collection '{collection}' for BM25 rebuild"
        )
        return chunks

    def retrieval_health(self) -> dict[str, Any]:
        """Delegate to RetrievalEngine health — for /health/deps."""
        return self._engine.retrieval_health()

    # ------------------------------------------------------------------ #
    #  Sprint 4: Staleness + confidence + gap enforcement                  #
    # ------------------------------------------------------------------ #

    # Staleness thresholds in hours — mirrors epistemic_principles.md §3.
    # Commit-based scopes use sentinel 0.0 (any modification = stale).
    _STALENESS_THRESHOLDS_HOURS: dict[str, float] = {
        "security":       24.0,
        "network":        168.0,
        "remediation":    336.0,
        "agents":         168.0,
        "code_standards": 0.0,
        "governance":     0.0,
        "cicd":           0.0,
        "schemas":        0.0,
    }

    # Scope adjacency — mirrors epistemic_principles.md §4.
    _SCOPE_ADJACENCY: dict[str, frozenset[str]] = {
        "security":     frozenset({"network"}),
        "network":      frozenset({"security"}),
        "cicd":         frozenset({"code_standards", "remediation"}),
        "code_standards": frozenset({"cicd"}),
        "remediation":  frozenset({"cicd"}),
        "agents":       frozenset({"governance"}),
        "governance":   frozenset({"agents"}),
    }

    def _check_staleness(self, chunk: dict[str, Any]) -> dict[str, Any]:
        """
        Compare chunk last_indexed against source last_modified.

        Returns:
            is_stale:    bool
            stale_since: str | None  (ISO timestamp)
            age_ratio:   float       (0.0–1.0, ratio of threshold consumed)
            scope:       str
        """
        metadata = chunk.get("metadata", chunk)
        scope = str(metadata.get("scope") or chunk.get("agent_scope") or "")
        last_indexed_raw  = metadata.get("last_indexed")
        last_modified_raw = metadata.get("source_last_modified")

        _empty = {"is_stale": False, "stale_since": None, "age_ratio": 0.0, "scope": scope}

        if not last_indexed_raw or not last_modified_raw:
            return _empty

        try:
            last_indexed  = datetime.fromisoformat(str(last_indexed_raw))
            last_modified = datetime.fromisoformat(str(last_modified_raw))
            # Convert to UTC properly — astimezone preserves the instant,
            # unlike .replace() which silently relabels.
            if last_indexed.tzinfo is None:
                last_indexed = last_indexed.replace(tzinfo=timezone.utc)
            else:
                last_indexed = last_indexed.astimezone(timezone.utc)
            if last_modified.tzinfo is None:
                last_modified = last_modified.replace(tzinfo=timezone.utc)
            else:
                last_modified = last_modified.astimezone(timezone.utc)
        except ValueError:
            return _empty

        threshold_hours = self._STALENESS_THRESHOLDS_HOURS.get(scope)

        # Commit-based scope: any modification after indexing = stale.
        if threshold_hours == 0.0:
            is_stale = last_modified > last_indexed
            return {
                "is_stale":    is_stale,
                "stale_since": last_modified.isoformat() if is_stale else None,
                "age_ratio":   1.0 if is_stale else 0.0,
                "scope":       scope,
            }

        # Unknown scope — default 7 days.
        if threshold_hours is None:
            threshold_hours = 168.0

        now = datetime.now(timezone.utc)
        age_hours = (now - last_indexed).total_seconds() / 3600.0
        age_ratio = min(age_hours / threshold_hours, 1.0) if threshold_hours > 0 else 0.0
        is_stale  = last_modified > last_indexed or age_hours >= threshold_hours

        return {
            "is_stale":    is_stale,
            "stale_since": last_modified.isoformat() if is_stale else None,
            "age_ratio":   age_ratio,
            "scope":       scope,
        }

    def _compute_confidence(
        self,
        chunk: dict[str, Any],
        scope: str | None = None,
    ) -> float:
        """
        Compute confidence score per epistemic_principles.md §4.

        confidence = sigmoid(reranker_score) × recency_factor × scope_match_bonus
        """
        # reranker_score_normalised = sigmoid(raw)
        raw_score = (
            chunk.get("_reranker_score")
            or chunk.get("rrf_score")
            or chunk.get("score")
            or 0.0
        )
        reranker_normalised = 1.0 / (1.0 + math.exp(-float(raw_score)))

        # recency_factor from staleness
        staleness = self._check_staleness(chunk)
        if staleness["is_stale"]:
            recency_factor = 0.0
        elif staleness["age_ratio"] >= 0.5:
            recency_factor = 0.75
        else:
            recency_factor = 1.0

        # scope_match_bonus
        chunk_scope = staleness["scope"]
        if not scope or not chunk_scope:
            scope_match_bonus = 1.0
        elif scope == chunk_scope:
            scope_match_bonus = 1.0
        elif chunk_scope in self._SCOPE_ADJACENCY.get(scope, frozenset()):
            scope_match_bonus = 0.85
        else:
            scope_match_bonus = 0.70

        confidence = reranker_normalised * recency_factor * scope_match_bonus
        return round(max(0.0, min(1.0, confidence)), 6)

    async def search_with_gap_check(
        self,
        query: str,
        requesting_agent: str,
        scope: str | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """
        Full retrieval pipeline with staleness annotation,
        confidence scoring, and corpus gap enforcement.

        Returns:
            results:              list[dict]  — annotated chunks
            stale_chunks:         list[str]   — chunk_ids that are stale
            majority_stale:       bool
            top_confidence:       float
            gap_fired:            bool
            agent_should_proceed: bool
            gap_id:               str | None
        """
        raw_results = await self.search(query=query, agent_scope=scope, top_k=top_k)

        annotated: list[dict[str, Any]] = []
        stale_chunk_ids: list[str] = []

        for chunk in raw_results:
            staleness  = self._check_staleness(chunk)
            confidence = self._compute_confidence(chunk, scope=scope)

            annotated_chunk = {
                **chunk,
                "is_stale":    staleness["is_stale"],
                "stale_since": staleness["stale_since"],
                "age_ratio":   staleness["age_ratio"],
                "confidence":  confidence,
            }
            annotated.append(annotated_chunk)

            if staleness["is_stale"]:
                chunk_id = (
                    chunk.get("chunk_id")
                    or chunk.get("id")
                    or str(chunk.get("metadata", {}).get("chunk_id", "unknown"))
                )
                stale_chunk_ids.append(chunk_id)

        majority_stale = (
            len(stale_chunk_ids) > len(annotated) / 2
            if annotated else False
        )

        top_confidence = max(
            (c["confidence"] for c in annotated), default=0.0
        )

        gap_result = self._gap_handler.check(
            requesting_agent=requesting_agent,
            query=query,
            top_confidence=top_confidence,
        )

        if majority_stale:
            gap_result["agent_should_proceed"] = False

        return {
            "results":              annotated,
            "stale_chunks":         stale_chunk_ids,
            "majority_stale":       majority_stale,
            "top_confidence":       top_confidence,
            "gap_fired":            gap_result["gap_fired"],
            "agent_should_proceed": gap_result["agent_should_proceed"],
            "gap_id":               gap_result.get("gap_id"),
        }

    async def retrieve(
        self,
        query: str,
        agent_id: str,
        limit: int = 5,
    ) -> str:
        """
        Retrieve semantically relevant context for a query.

        Args:
            query:    The search query (usually the user message).
            agent_id: The calling agent's ID — used for namespace filtering.
            limit:    Maximum number of context chunks to include.

        Returns:
            A formatted ``Retrieved context:`` block, or empty string if nothing found.
        """
        if not query.strip():
            return ""

        try:
            query_vec = await self._llm.embed(query)
        except Exception as exc:
            logger.warning(f"ContextAssembler embed failed: {exc}")
            return ""

        if not query_vec:
            # embed() returned empty — agent LLM is likely a generation model (e.g. qwen3),
            # not an embedding model.  Skip RAG rather than triggering the JSON fallback
            # which would call embed() hundreds of times and block the event loop.
            return ""

        if not QDRANT_AVAILABLE or self._store._client is None:
            # Qdrant unavailable and no fast fallback — skip RAG silently.
            return ""

        results: list[dict[str, Any]] = []

        # 1. Agent-specific collection
        try:
            agent_hits = self._store.search(
                query_vector=query_vec,
                limit=limit,
                collection=agent_id,
                agent_namespace=agent_id,
            )
            results.extend(agent_hits)
        except Exception as exc:
            logger.debug(f"ContextAssembler: agent collection '{agent_id}' search failed: {exc}")

        # 2. Global collections
        source_prefixes = self._source_prefix_filter()
        for coll in self.GLOBAL_COLLECTIONS:
            if coll == agent_id:
                continue
            try:
                global_hits = self._store.search(
                    query_vector=query_vec,
                    limit=max(2, limit // 2),
                    collection=coll,
                )
                if source_prefixes:
                    global_hits = [
                        hit
                        for hit in global_hits
                        if any(
                            str(hit.get("payload", {}).get("source") or hit.get("payload", {}).get("path") or "").startswith(prefix)
                            for prefix in source_prefixes
                        )
                    ]
                results.extend(global_hits)
            except Exception as exc:
                logger.debug(f"ContextAssembler: global collection '{coll}' search failed: {exc}")

        if not results:
            return await self._fallback_retrieve(query, limit)

        return self._format_results(results, limit)

    async def retrieve_records(
        self,
        query: str,
        agent_id: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Return structured retrieval hits for programmatic callers."""
        if not query.strip():
            return []

        try:
            query_vec = await self._llm.embed(query)
        except Exception as exc:
            logger.warning(f"ContextAssembler embed failed: {exc}")
            return await self._fallback_records(query, limit)

        if not query_vec:
            return await self._fallback_records(query, limit)

        if not QDRANT_AVAILABLE or self._store._client is None:
            return await self._fallback_records(query, limit)

        results: list[dict[str, Any]] = []
        source_prefixes = self._source_prefix_filter()

        try:
            agent_hits = self._store.search(
                query_vector=query_vec,
                limit=limit,
                collection=agent_id,
                agent_namespace=agent_id,
            )
            results.extend(agent_hits)
        except Exception as exc:
            logger.debug(f"ContextAssembler: agent collection '{agent_id}' search failed: {exc}")

        for coll in self.GLOBAL_COLLECTIONS:
            if coll == agent_id:
                continue
            try:
                global_hits = self._store.search(
                    query_vector=query_vec,
                    limit=max(2, limit // 2),
                    collection=coll,
                )
                if source_prefixes:
                    global_hits = [
                        hit
                        for hit in global_hits
                        if any(
                            str(hit.get("payload", {}).get("source") or hit.get("payload", {}).get("path") or "").startswith(prefix)
                            for prefix in source_prefixes
                        )
                    ]
                results.extend(global_hits)
            except Exception as exc:
                logger.debug(f"ContextAssembler: global collection '{coll}' search failed: {exc}")

        if not results:
            return await self._fallback_records(query, limit)

        return self._normalise_results(results, limit)

    async def ingest_memory(
        self,
        agent_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Embed and store a memory entry in the agent's Qdrant collection.

        Silently returns False if Qdrant is unavailable or content is empty,
        so callers do not need to handle RAG errors in the execution path.

        Args:
            agent_id: Agent namespace for the collection.
            content:  Text to embed and store.
            metadata: Optional payload metadata merged with the default payload.

        Returns:
            True on successful upsert, False otherwise.
        """
        if not QDRANT_AVAILABLE or self._store._client is None:
            return False
        if not content.strip():
            return False

        try:
            vec = await self._llm.embed(content)
            if not vec:
                return False
            payload: dict[str, Any] = {"content": content, "agent_id": agent_id}
            if metadata:
                payload.update(metadata)
            self._store.ensure_collection(agent_id, dim=len(vec))
            self._store.upsert(
                vectors=[vec],
                payloads=[payload],
                collection=agent_id,
                agent_namespace=agent_id,
            )
            logger.debug(f"ContextAssembler.ingest_memory: agent={agent_id} chars={len(content)}")
            return True
        except Exception as exc:
            logger.warning(f"ContextAssembler.ingest_memory failed for {agent_id}: {exc}")
            return False

    async def ingest_business_profile(self, business_id: str, field: str, answer: str) -> bool:
        """Store a business intake answer in Qdrant and the JSON fallback store."""
        content = answer.strip()
        if not content:
            return False

        fallback_ok = False
        kv = _get_fallback_store(self._llm)
        if kv is not None:
            try:
                await kv.upsert_business_answer(business_id=business_id, field=field, answer=content)
                fallback_ok = True
            except Exception as exc:
                logger.debug(f"ContextAssembler business profile fallback write failed: {exc}")

        if not QDRANT_AVAILABLE or self._store._client is None:
            return fallback_ok

        try:
            text = f"Business {business_id} | {field}: {content}"
            vec = await self._llm.embed(text)
            if not vec:
                return fallback_ok
            self._store.ensure_collection("business_profiles", dim=len(vec))
            self._store.upsert(
                vectors=[vec],
                payloads=[{"business_id": business_id, "field": field, "text": text}],
                ids=[hashlib.sha256(f"{business_id}:{field}".encode()).hexdigest()],
                collection="business_profiles",
            )
            logger.debug("ContextAssembler.ingest_business_profile: business_id=%s field=%s", business_id, field)
            return True
        except Exception as exc:
            logger.warning(f"ContextAssembler.ingest_business_profile failed for {business_id}:{field}: {exc}")
            return fallback_ok

    async def search_business_profiles(
        self,
        query: str,
        business_id: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        """Retrieve semantic business-profile matches with Qdrant-first fallback."""
        if not query.strip() or not business_id.strip():
            return []

        try:
            query_vec = await self._llm.embed(query)
        except Exception as exc:
            logger.warning(f"ContextAssembler business profile embed failed: {exc}")
            query_vec = []

        if query_vec and QDRANT_AVAILABLE and self._store._client is not None:
            try:
                hits = self._store.search(
                    query_vector=query_vec,
                    limit=limit,
                    collection="business_profiles",
                    filters={"business_id": business_id},
                )
                results = [
                    {
                        "business_id": hit.get("payload", {}).get("business_id", business_id),
                        "field": hit.get("payload", {}).get("field"),
                        "text": hit.get("payload", {}).get("text", ""),
                        "score": float(hit.get("score", 0.0)),
                    }
                    for hit in hits
                    if hit.get("payload", {}).get("text")
                ]
                if results:
                    return results[:limit]
            except Exception as exc:
                logger.debug(f"ContextAssembler business profile Qdrant search failed: {exc}")

        kv = _get_fallback_store(self._llm)
        if kv is None:
            return []
        try:
            return await kv.search_business_profiles(query=query, business_id=business_id, top_k=limit)
        except Exception as exc:
            logger.debug(f"ContextAssembler business profile fallback failed: {exc}")
            return []

    def _normalise_results(self, results: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
        """Sort, deduplicate, and normalize raw vector hits."""
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        seen: set[str] = set()
        normalised: list[dict[str, Any]] = []

        for result in results:
            payload = result.get("payload", {})
            text = payload.get("content") or payload.get("text") or payload.get("answer") or ""
            if not text:
                continue
            path = payload.get("source") or payload.get("file_path") or payload.get("path") or ""
            chunk_index = payload.get("chunk_index", payload.get("chunk_idx", 0))
            dedupe_key = f"{path}::{text[:200]}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            normalised.append(
                {
                    "path": str(path),
                    "chunk_index": int(chunk_index)
                    if isinstance(chunk_index, (int, float, str)) and str(chunk_index).isdigit()
                    else 0,
                    "text": text,
                    "score": float(result.get("score", 0.0)),
                }
            )
            if len(normalised) >= limit:
                break

        return normalised

    def _format_results(self, results: list[dict[str, Any]], limit: int) -> str:
        """Sort, deduplicate, and format retrieved results into a context block."""
        lines: list[str] = []
        for result in self._normalise_results(results, limit):
            content = result["text"]
            source = result["path"]
            score = result["score"]
            header = f"[score={score:.2f}{f', src={source}' if source else ''}]"
            lines.append(f"{header}\n{content[:400]}")

        if not lines:
            return ""
        return "Retrieved context:\n" + "\n\n".join(lines)

    async def _fallback_records(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Return structured fallback hits from KnowledgeVectorStore."""
        ContextAssembler._fallback_count += 1
        logger.warning(
            "ContextAssembler: Qdrant unavailable — using JSON KnowledgeVectorStore fallback "
            "(total_fallback_retrievals=%d). "
            "Set QDRANT_IN_MEMORY=true for tests or point QDRANT_HOST to a running instance.",
            ContextAssembler._fallback_count,
        )
        try:
            kv = _get_fallback_store(self._llm)
            if kv is None:
                return []
            results = await kv.search(query=query, top_k=limit, allow_build=False, mode=RETRIEVAL_MODE)
            return [
                {
                    "path": str(result.get("path", "")),
                    "chunk_index": int(result.get("chunk_index", 0)),
                    "text": str(result.get("text", result.get("content", ""))),
                    "score": float(result.get("score", 0.0)),
                }
                for result in results[:limit]
                if result.get("text") or result.get("content")
            ]
        except Exception as exc:
            logger.debug(f"ContextAssembler fallback failed: {exc}")
            return []

    async def _fallback_retrieve(self, query: str, limit: int) -> str:
        """
        Fall back to JSON KnowledgeVectorStore when Qdrant is unavailable.

        Increments the class-level ``_fallback_count`` counter so operators can
        see fallback activation via ``health_check()`` and the ``/metrics`` endpoint.
        Logs a WARNING on every call — intentionally noisy to surface misconfigurations.
        """
        results = await self._fallback_records(query, limit)
        if not results:
            return ""
        lines = []
        for result in results:
            source_suffix = f", src={result['path']}" if result["path"] else ""
            lines.append(f"[score={result['score']:.2f}{source_suffix}]\n{result['text'][:400]}")
        return "Retrieved context:\n" + "\n\n".join(lines)
