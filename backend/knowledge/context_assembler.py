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

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.llm import OllamaClient

from backend.config import KNOWN_EMBED_DIMS, QDRANT_DEFAULT_DIM, QDRANT_EMBED_MODEL, QDRANT_HOST, QDRANT_IN_MEMORY, QDRANT_PORT
from backend.ml.vector_store import QDRANT_AVAILABLE, VectorStore

logger = logging.getLogger(__name__)

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
            "fallback_count": ContextAssembler._fallback_count,
            "host": f"{QDRANT_HOST}:{QDRANT_PORT}",
            "in_memory": QDRANT_IN_MEMORY,
            "collections": collections,
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
            return await self._fallback_retrieve(query, limit)

        if not query_vec:
            return await self._fallback_retrieve(query, limit)

        if not QDRANT_AVAILABLE or self._store._client is None:
            return await self._fallback_retrieve(query, limit)

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
        for coll in self.GLOBAL_COLLECTIONS:
            if coll == agent_id:
                continue
            try:
                global_hits = self._store.search(
                    query_vector=query_vec,
                    limit=max(2, limit // 2),
                    collection=coll,
                )
                results.extend(global_hits)
            except Exception as exc:
                logger.debug(f"ContextAssembler: global collection '{coll}' search failed: {exc}")

        if not results:
            return await self._fallback_retrieve(query, limit)

        return self._format_results(results, limit)

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

    def _format_results(self, results: list[dict[str, Any]], limit: int) -> str:
        """Sort, deduplicate, and format retrieved results into a context block."""
        results.sort(key=lambda r: r.get("score", 0.0), reverse=True)
        seen: set[str] = set()
        lines: list[str] = []
        for r in results[:limit]:
            payload = r.get("payload", {})
            content = (
                payload.get("content")
                or payload.get("text")
                or payload.get("answer")
                or ""
            )
            if not content or content in seen:
                continue
            seen.add(content)
            source = payload.get("source") or payload.get("file_path") or ""
            score = r.get("score", 0.0)
            header = f"[score={score:.2f}{f', src={source}' if source else ''}]"
            lines.append(f"{header}\n{content[:400]}")

        if not lines:
            return ""
        return "Retrieved context:\n" + "\n\n".join(lines)

    async def _fallback_retrieve(self, query: str, limit: int) -> str:
        """
        Fall back to JSON KnowledgeVectorStore when Qdrant is unavailable.

        Increments the class-level ``_fallback_count`` counter so operators can
        see fallback activation via ``health_check()`` and the ``/metrics`` endpoint.
        Logs a WARNING on every call — intentionally noisy to surface misconfigurations.
        """
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
                return ""
            results = await kv.search(query=query, top_k=limit)
            if not results:
                return ""
            lines = [
                f"[score={r.get('score', 0.0):.2f}]\n{r.get('text', r.get('content', ''))[:400]}"
                for r in results[:limit]
                if r.get("text") or r.get("content")
            ]
            return "Retrieved context:\n" + "\n\n".join(lines) if lines else ""
        except Exception as exc:
            logger.debug(f"ContextAssembler fallback failed: {exc}")
            return ""
