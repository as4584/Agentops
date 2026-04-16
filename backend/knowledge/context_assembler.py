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

from backend.config import QDRANT_DEFAULT_DIM, QDRANT_HOST, QDRANT_IN_MEMORY, QDRANT_PORT
from backend.ml.vector_store import QDRANT_AVAILABLE, VectorStore

logger = logging.getLogger(__name__)

# Module-level singleton — shared across all agents in the same process.
_vector_store: VectorStore | None = None


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

    def __init__(self, llm_client: OllamaClient) -> None:
        self._llm = llm_client
        self._store = get_vector_store()

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
        """Fall back to JSON KnowledgeVectorStore when Qdrant is unavailable."""
        try:
            from backend.knowledge import KnowledgeVectorStore

            kv = KnowledgeVectorStore(self._llm)
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
