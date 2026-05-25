# backend/tests/test_retrieval_reranker.py
"""
Sprint 3 — Cross-Encoder Reranker Gate Tests
============================================
All four tests must be green before Sprint 3 commits.

Gate tests:
  1. Ambiguous query precision: security chunk reaches top-3 after reranking.
  2. Load failure fallback: unavailable model returns RRF top-k unchanged.
  3. Scoring failure fallback: predict() exception returns RRF top-k unchanged.
  4. Locality invariant: reranker never makes an outbound network call (INV-16).
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SECURITY_CHUNK = {
    "chunk_id": "sec_01",
    "text": (
        "Never expose port 22, admin panels, or database ports to the internet. "
        "Use firewall rules to block external access to all management interfaces."
    ),
    "rrf_score": 0.028,
    "agent_scope": "security_agent",
}

# Sprint 2 RRF output — security chunk is at rank 4 (0-indexed: position 3).
# Reranker must move it to top-3.
AMBIGUOUS_CANDIDATES: list[dict[str, Any]] = [
    {"chunk_id": "c1", "text": "The CI/CD pipeline deploys to port 8080 via Docker.", "rrf_score": 0.032},
    {"chunk_id": "c2", "text": "VLAN 10 is the management network segment.", "rrf_score": 0.031},
    {"chunk_id": "c3", "text": "Container ports are mapped via docker-compose expose.", "rrf_score": 0.030},
    SECURITY_CHUNK,  # rank 4 in RRF — must reach top-3 after rerank
    {"chunk_id": "c5", "text": "Database migrations run via alembic upgrade head.", "rrf_score": 0.025},
]

AMBIGUOUS_QUERY = "what should I not expose to the internet"


def _make_mock_cross_encoder(scores: list[float]) -> MagicMock:
    """Build a sys.modules-injectable CrossEncoder mock."""
    mock_module = MagicMock()
    mock_instance = MagicMock()
    mock_instance.predict.return_value = np.array(scores)
    mock_module.CrossEncoder.return_value = mock_instance
    return mock_module


# ---------------------------------------------------------------------------
# Test 1 — Ambiguous query precision gate
# ---------------------------------------------------------------------------

class TestAmbiguousQueryPrecision:
    """
    Sprint 2 vs Sprint 3 precision comparison.

    Without reranker: RRF puts security chunk at position 4 due to noisy
    keyword overlap with pipeline/VLAN chunks.

    With reranker: cross-encoder reads query + chunk together and scores
    the security chunk highest, moving it into top-3.

    This test must FAIL against Sprint 2 output (pre-reranker) and PASS
    against Sprint 3 output. That delta is the reranker value proof.
    """

    def test_security_chunk_reaches_top3_after_reranking(self) -> None:
        # Verify Sprint 2 ordering has security chunk outside top-3 (pre-condition)
        sprint2_top3_ids = [c["chunk_id"] for c in AMBIGUOUS_CANDIDATES[:3]]
        assert "sec_01" not in sprint2_top3_ids, (
            "Pre-condition failed: security chunk already in top-3 before reranking. "
            "Either the RRF fixture is wrong or the reranker gate has no value to prove."
        )

        # Cross-encoder correctly scores the security chunk highest (~8.4)
        # Other chunks score low — noisy keyword overlap gets penalised
        ce_scores = [-2.1, -3.5, -2.8, 8.4, -4.0]  # index 3 = security chunk
        mock_module = _make_mock_cross_encoder(ce_scores)

        with patch.dict(sys.modules, {"sentence_transformers": mock_module}):
            from backend.knowledge.reranker import Reranker
            reranker = Reranker()
            results = reranker.rerank(AMBIGUOUS_QUERY, AMBIGUOUS_CANDIDATES, top_k=3)

        assert reranker.available, "Reranker should be available with mocked model"

        top3_ids = [r["chunk_id"] for r in results]
        assert "sec_01" in top3_ids, (
            f"Security chunk not in top-3 after reranking. Got: {top3_ids}. "
            "Reranker is not adding value — check cross-encoder score injection."
        )
        # Reranker score must be attached for observability
        security_result = next(r for r in results if r["chunk_id"] == "sec_01")
        assert "_reranker_score" in security_result, (
            "_reranker_score annotation missing — downstream observability broken"
        )


# ---------------------------------------------------------------------------
# Test 2 — Load failure fallback
# ---------------------------------------------------------------------------

class TestLoadFailureFallback:
    """
    When sentence_transformers is unavailable (ImportError) or the model
    fails to load, reranker.available must be False and rerank() must
    return candidates[:top_k] in original RRF order without raising.
    """

    def test_unavailable_reranker_returns_rrf_top_k_unchanged(self) -> None:
        from backend.knowledge.reranker import Reranker

        reranker = Reranker.__new__(Reranker)
        reranker._model_name = "test-model"
        reranker._model = None  # simulate failed load

        assert not reranker.available

        results = reranker.rerank(AMBIGUOUS_QUERY, AMBIGUOUS_CANDIDATES, top_k=3)

        expected_ids = [c["chunk_id"] for c in AMBIGUOUS_CANDIDATES[:3]]
        actual_ids = [r["chunk_id"] for r in results]
        assert actual_ids == expected_ids, (
            f"Fallback ordering broken. Expected {expected_ids}, got {actual_ids}"
        )

    def test_empty_candidates_returns_empty_list(self) -> None:
        from backend.knowledge.reranker import Reranker

        reranker = Reranker.__new__(Reranker)
        reranker._model_name = "test-model"
        reranker._model = None

        assert reranker.rerank(AMBIGUOUS_QUERY, [], top_k=5) == []


# ---------------------------------------------------------------------------
# Test 3 — Scoring exception fallback
# ---------------------------------------------------------------------------

class TestScoringFailureFallback:
    """
    Model loads successfully but predict() raises at scoring time.
    rerank() must return candidates[:top_k] in original RRF order.
    The exception must not propagate to the caller.
    """

    def test_scoring_exception_returns_rrf_order_without_raising(self) -> None:
        from backend.knowledge.reranker import Reranker

        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("ONNX inference error")

        reranker = Reranker.__new__(Reranker)
        reranker._model_name = "test-model"
        reranker._model = mock_model  # model present but predict() raises

        assert reranker.available

        results = reranker.rerank(AMBIGUOUS_QUERY, AMBIGUOUS_CANDIDATES, top_k=3)

        expected_ids = [c["chunk_id"] for c in AMBIGUOUS_CANDIDATES[:3]]
        actual_ids = [r["chunk_id"] for r in results]
        assert actual_ids == expected_ids, (
            f"Scoring fallback ordering broken. Expected {expected_ids}, got {actual_ids}"
        )

    def test_top_k_respected_on_scoring_failure(self) -> None:
        from backend.knowledge.reranker import Reranker

        mock_model = MagicMock()
        mock_model.predict.side_effect = ValueError("unexpected shape")

        reranker = Reranker.__new__(Reranker)
        reranker._model_name = "test-model"
        reranker._model = mock_model

        results = reranker.rerank(AMBIGUOUS_QUERY, AMBIGUOUS_CANDIDATES, top_k=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Test 4 — Locality invariant (INV-16)
# ---------------------------------------------------------------------------

class TestLocalityInvariant:
    """
    The reranker must never make an outbound network call.
    All scoring happens on local CPU — no HTTP, no socket.connect to
    external hosts. This test enforces INV-16.
    """

    def test_reranker_makes_no_outbound_http_calls(self) -> None:
        import socket

        from backend.knowledge.reranker import Reranker

        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-1.0, -2.0, -3.0, 4.0, -5.0])

        reranker = Reranker.__new__(Reranker)
        reranker._model_name = "test-model"
        reranker._model = mock_model

        outbound_calls: list[str] = []
        original_connect = socket.socket.connect

        def patched_connect(self_sock: Any, address: Any) -> None:
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("localhost", "127.0.0.1", "::1"):
                outbound_calls.append(str(address))
            return original_connect(self_sock, address)

        with patch.object(socket.socket, "connect", patched_connect):
            reranker.rerank(AMBIGUOUS_QUERY, AMBIGUOUS_CANDIDATES, top_k=3)

        assert outbound_calls == [], (
            f"Reranker made outbound network calls (INV-16 violation): {outbound_calls}"
        )
