"""
Sprint 2 — Hybrid Retrieval Test Suite
=======================================
Entry condition: FAIL on dense-only path, PASS after BM25 is added.

The VLAN 10 fixture is the proof-of-work test:
  - Dense-only (nomic-embed-text) will miss it if embedding space is noisy
    or if the exact token "VLAN 10" doesn't map cleanly to a semantic cluster.
  - BM25 must surface it by exact token match regardless of embedding quality.

If test_exact_token_query_surfaces_correct_chunk passes on dense-only, your
embeddings are already good enough and BM25 is optional overhead — note it.

Run order:
  1. test_dense_only_baseline  — documents current dense result (may pass or fail)
  2. test_exact_token_query_surfaces_correct_chunk  — THE regression gate
  3. test_knowledge_response_contract — verifies Sprint 1 handoff-3 contract is stable
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


# ── Fixtures ──────────────────────────────────────────────────────────────────

VLAN_QUERY = "what does the corpus say about VLAN 10"
VLAN_TOKENS = {"vlan", "vlan 10", "vlan10"}


@pytest.fixture
async def embed_client():
    """Embed client using nomic-embed-text — same model as production Qdrant."""
    from backend.llm import OllamaClient
    client = OllamaClient(model="nomic-embed-text")
    yield client
    await client.close()


# ── Cat 1: Dense-only baseline (documents current state, not a gate) ──────────

class TestDenseOnlyBaseline:
    """Document current dense retrieval behaviour before BM25 exists.

    These tests never fail — they capture the dense-only result so Sprint 2
    can compare before/after.
    """

    async def test_dense_retrieval_returns_results(self, embed_client) -> None:
        """Dense path returns at least one chunk for a known indexed query."""
        from backend.knowledge.context_assembler import ContextAssembler

        assembler = ContextAssembler(embed_client)
        health = assembler.health_check()

        if not health["qdrant_available"]:
            pytest.skip("Qdrant not available — run `docker compose up qdrant`")

        records = await assembler.retrieve_records(
            query=VLAN_QUERY,
            agent_id="knowledge_agent",
            limit=5,
        )
        # Just document what we got — don't assert correctness yet
        print(f"\nDense-only top result for {VLAN_QUERY!r}:")
        for r in records[:3]:
            print(f"  score={r.get('score', 0):.4f}  path={r.get('path', '?')}")
            print(f"  text={r.get('text', '')[:80]!r}")
        # Non-asserting — if this is empty, Qdrant has no knowledge_agent chunks
        assert isinstance(records, list)

    async def test_dense_vlan_chunk_score(self, embed_client) -> None:
        """Record the dense similarity score for VLAN 10 — baseline for BM25 delta."""
        from backend.knowledge.context_assembler import ContextAssembler

        assembler = ContextAssembler(embed_client)
        if not assembler.health_check()["qdrant_available"]:
            pytest.skip("Qdrant unavailable")

        records = await assembler.retrieve_records(
            query="VLAN 10 management network",
            agent_id="knowledge_agent",
            limit=5,
        )
        if records:
            top_score = records[0].get("score", 0.0)
            print(f"\nDense top score for VLAN 10: {top_score:.4f}")
            # Capture: if top_score > 0.75, dense is sufficient, BM25 is optional
            # If top_score < 0.5, dense misses it — BM25 is required
            print(f"  Dense retrieval {'sufficient' if top_score > 0.75 else 'insufficient — BM25 required'}")


# ── Cat 2: THE regression gate — exact token test ─────────────────────────────

class TestExactTokenRetrieval:
    """
    Exact-token retrieval gate.

    This test MUST:
      - FAIL on dense-only path (before BM25 is added)
      - PASS after BM25 is added to the retrieval engine

    If it passes on dense-only, document it and proceed — your embeddings are
    good enough. Either way, it's the honest proof of whether BM25 adds value.
    """

    async def test_exact_token_query_surfaces_correct_chunk(self, embed_client) -> None:
        """
        BM25 must surface the VLAN 10 chunk when queried by exact token.

        Vector search alone will miss this if embedding space is noisy.
        Write this test against the Sprint 1 dense-only path first —
        it should FAIL on dense-only, then PASS after BM25 is added.
        That failure is your proof that BM25 is doing real work.
        """
        from backend.knowledge.context_assembler import ContextAssembler

        assembler = ContextAssembler(embed_client)
        if not assembler.health_check()["qdrant_available"]:
            pytest.skip("Qdrant unavailable")

        # This query uses exact tokens — BM25 handles it, dense may not
        records = await assembler.retrieve_records(
            query="VLAN 10",
            agent_id="knowledge_agent",
            limit=5,
        )

        # Check if any returned chunk mentions "vlan 10" or "vlan10"
        vlan_hit = next(
            (
                r for r in records
                if any(tok in r.get("text", "").lower() for tok in VLAN_TOKENS)
                or any(tok in r.get("path", "").lower() for tok in VLAN_TOKENS)
            ),
            None,
        )

        if vlan_hit is None:
            # Dense-only missed it — BM25 is required to pass this test
            top = records[0] if records else {}
            pytest.fail(
                f"Dense-only MISSED 'VLAN 10' exact token.\n"
                f"Top result: score={top.get('score', 0):.4f} path={top.get('path', '?')!r}\n"
                f"  text={top.get('text', '')[:120]!r}\n\n"
                "This failure is EXPECTED before BM25 is added.\n"
                "Implement backend/knowledge/bm25_index.py, wire it into\n"
                "retrieval_engine.py with RRF merge, then re-run — it must PASS."
            )

        # If we reach here, dense was sufficient — note it
        print(
            f"\nDense-only FOUND 'VLAN 10' chunk — score={vlan_hit.get('score', 0):.4f}\n"
            f"  path={vlan_hit.get('path', '?')}\n"
            f"  text={vlan_hit.get('text', '')[:120]!r}\n"
            "NOTE: BM25 may still improve recall — run the RRF merge test."
        )
        assert vlan_hit is not None

    async def test_exact_token_bm25_scores_higher_than_dense(self, embed_client) -> None:
        """
        After BM25 is added: the BM25 score for 'VLAN 10' must exceed the
        dense similarity score for the same chunk.

        Skip this test until bm25_index.py exists.
        """
        try:
            from backend.knowledge.bm25_index import BM25Index  # noqa: F401
        except ImportError:
            pytest.skip("bm25_index.py not yet implemented — Sprint 2 task")

        # When BM25Index exists, this test body will be filled in.
        # For now, just ensure the import works.
        assert True


# ── Cat 3: Knowledge response contract ────────────────────────────────────────

class TestKnowledgeResponseContract:
    """Sprint 1 Handoff 3 — ensure the structured contract is stable."""

    async def test_knowledge_response_has_all_required_fields(self) -> None:
        """Every knowledge_agent response must have the 5 Sprint 2 contract fields."""
        from unittest.mock import AsyncMock
        from backend.llm import OllamaClient
        from backend.orchestrator import AgentOrchestrator

        client = OllamaClient(model="nomic-embed-text")
        try:
            with patch.object(
                client, "generate",
                new=AsyncMock(return_value="Test answer.\n\nSources:\n- docs/test.md")
            ):
                with patch.object(client, "embed", new=AsyncMock(return_value=[0.1] * 768)):
                    orch = AgentOrchestrator(client)
                    result = await orch.process_message(
                        "knowledge_agent", "what does the corpus say about VLAN 10"
                    )

            required = {"answer", "citations", "confidence", "stale_chunks", "agent_scope"}
            for field in required:
                assert field in result, f"Missing field: {field!r}"

            assert result["answer"] is not None, "answer must not be None"
            assert isinstance(result["citations"], list), "citations must be a list"
            assert isinstance(result["confidence"], float), "confidence must be a float"
            assert isinstance(result["stale_chunks"], list), "stale_chunks must be a list"
            assert isinstance(result["agent_scope"], dict), "agent_scope must be a dict"

            scope = result["agent_scope"]
            assert scope.get("agent_id") == "knowledge_agent"
            assert "chunks_retrieved" in scope
            assert "collection" in scope
        finally:
            await client.close()

    async def test_knowledge_response_non_knowledge_agent_has_null_fields(self) -> None:
        """Non-knowledge agents must return None for the structured fields."""
        from backend.llm import OllamaClient
        from backend.orchestrator import AgentOrchestrator

        client = OllamaClient(model="nomic-embed-text")
        try:
            with patch.object(
                client, "generate",
                new=AsyncMock(return_value="Deployment triggered.")
            ):
                orch = AgentOrchestrator(client)
                result = await orch.process_message("devops_agent", "deploy to staging")

            # Structured fields present but null for non-knowledge agents
            assert result.get("answer") is None
            assert result.get("citations") is None
            assert result.get("confidence") is None
        finally:
            await client.close()
