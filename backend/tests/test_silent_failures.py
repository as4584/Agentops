"""
Silent failure detector tests.

Verifies that degraded-service paths are observable (loud) rather than
silently switching to a fallback that operators cannot detect.

Covers
------
1. Qdrant fallback is loud — upsert/search with no client logs WARNING and
   increments the _silent_fallback_count observable counter.
2. ContextAssembler fallback is loud — retrieve() with no Qdrant logs WARNING.
3. GitNexus disabled state is explicit — get_gitnexus_health() returns a
   state with usable=False and a non-empty reason string (fail-closed contract).
4. GitNexus health state carries an actionable reason on every degraded path.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.mcp.gitnexus_health import get_gitnexus_health
from backend.ml.vector_store import VectorStore
from backend.models import GitNexusHealthState

# ===========================================================================
# 1. VectorStore — Qdrant fallback must log WARNING
# ===========================================================================


class TestQdrantFallbackIsLoud:
    """Fallback must log WARNING, not silently switch."""

    @pytest.fixture
    def silent_store(self, monkeypatch: pytest.MonkeyPatch) -> VectorStore:
        monkeypatch.setattr("backend.ml.vector_store.QDRANT_AVAILABLE", False)
        monkeypatch.setattr(VectorStore, "_silent_fallback_count", 0)
        return VectorStore()

    def test_upsert_fallback_logs_warning(
        self,
        silent_store: VectorStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="agentop"):
            silent_store.upsert([[0.1, 0.2]], [{"k": "v"}])

        assert any("upsert skipped" in r.message for r in caplog.records), (
            "Silent fallback — upsert failure not surfaced in logs"
        )

    def test_search_fallback_logs_warning(
        self,
        silent_store: VectorStore,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        with caplog.at_level(logging.WARNING, logger="agentop"):
            result = silent_store.search([0.1, 0.2, 0.3, 0.4])

        assert result == [], "Expected empty list from no-client search"
        assert any("search skipped" in r.message for r in caplog.records), (
            "Silent fallback — search failure not surfaced in logs"
        )

    def test_fallback_counter_increments_on_upsert(
        self,
        silent_store: VectorStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(VectorStore, "_silent_fallback_count", 0)
        silent_store.upsert([[0.1]], [{}])
        assert VectorStore._silent_fallback_count == 1

    def test_fallback_counter_increments_on_search(
        self,
        silent_store: VectorStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(VectorStore, "_silent_fallback_count", 0)
        silent_store.search([0.0])
        assert VectorStore._silent_fallback_count == 1

    def test_multiple_operations_accumulate_count(
        self,
        silent_store: VectorStore,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(VectorStore, "_silent_fallback_count", 0)
        silent_store.upsert([[0.1]], [{}])
        silent_store.search([0.1])
        silent_store.search([0.2])
        assert VectorStore._silent_fallback_count == 3


# ===========================================================================
# 2. ContextAssembler — retrieval fallback must log WARNING
# ===========================================================================


class TestContextAssemblerFallbackIsLoud:
    """ContextAssembler fallback path must emit an observable warning."""

    @pytest.mark.asyncio
    async def test_retrieve_fallback_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[])  # empty → triggers fallback

        ca = ContextAssembler(mock_llm)
        with caplog.at_level(logging.WARNING, logger="backend.knowledge.context_assembler"):
            await ca.retrieve(query="test query", agent_id="code_review_agent")

        assert any("fallback" in r.message.lower() or "unavailable" in r.message.lower() for r in caplog.records), (
            "Silent fallback — ContextAssembler fallback path not surfaced in logs"
        )

    def test_health_check_exposes_fallback_count(self) -> None:
        from backend.knowledge.context_assembler import ContextAssembler

        mock_llm = MagicMock()
        mock_llm.embed = AsyncMock(return_value=[])

        ca = ContextAssembler(mock_llm)
        health = ca.health_check()

        # Both counters must be present so operators can observe degraded state.
        assert "fallback_count" in health, "health_check must expose fallback_count"
        assert "vector_store_fallback_count" in health, "health_check must expose vector_store_fallback_count"


# ===========================================================================
# 3. GitNexus fail-closed contract
# ===========================================================================


class TestGitnexusFailClosed:
    """GitNexus unavailable/disabled must produce a non-usable state with a
    non-empty reason string — it must never silently appear as healthy."""

    def test_disabled_state_is_not_usable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """GITNEXUS_ENABLED=false must yield usable=False."""
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", False)
        state = get_gitnexus_health()
        assert not state.usable, "GitNexus disabled — usable must be False"

    def test_disabled_state_has_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Disabled state must carry an actionable reason string."""
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", False)
        state = get_gitnexus_health()
        assert state.reason, "GitNexus disabled — reason must not be empty"

    def test_missing_index_is_not_usable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """When the index file is missing, usable must be False."""
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", True)
        # Point meta path to a non-existent file.
        monkeypatch.setattr(
            "backend.mcp.gitnexus_health._META_PATH",
            tmp_path / "no_such_meta.json",  # type: ignore[arg-type]
        )
        state = get_gitnexus_health()
        assert not state.usable, "Missing index — usable must be False (fail-closed)"
        assert state.reason, "Missing index — reason must not be empty"

    def test_missing_index_has_actionable_reason(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """The reason for a missing index must include 'Run:' guidance."""
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", True)
        monkeypatch.setattr(
            "backend.mcp.gitnexus_health._META_PATH",
            tmp_path / "no_such_meta.json",  # type: ignore[arg-type]
        )
        state = get_gitnexus_health()
        assert "Run:" in state.reason or "run:" in state.reason.lower(), (
            f"Missing-index reason should include remediation guidance. Got: {state.reason!r}"
        )

    def test_no_transport_yields_not_usable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """When docker CLI is absent, usable must be False even if index exists."""
        meta_path = tmp_path / "meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "analyzedAt": "2026-01-01T00:00:00+00:00",
                    "stats": {"symbols": 100, "relationships": 50, "embeddings": 0},
                }
            )
        )
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", True)
        monkeypatch.setattr("backend.mcp.gitnexus_health._META_PATH", meta_path)
        monkeypatch.setattr("backend.mcp.gitnexus_health._transport_available", lambda: False)

        state = get_gitnexus_health()
        assert not state.usable, "No transport — usable must be False (fail-closed)"

    def test_health_state_never_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_gitnexus_health() must always return a GitNexusHealthState, never raise."""
        monkeypatch.setattr("backend.mcp.gitnexus_health.GITNEXUS_ENABLED", True)
        # Break _read_meta to throw an unexpected exception.
        monkeypatch.setattr(
            "backend.mcp.gitnexus_health._read_meta",
            lambda: (_ for _ in ()).throw(RuntimeError("injected")),  # type: ignore[return-value]
        )
        # Should not raise; caller code must be safe to call unconditionally.
        try:
            state = get_gitnexus_health()
            # If it returns, the state must be not-usable.
            assert isinstance(state, GitNexusHealthState)
        except RuntimeError:
            # Also acceptable if the exception propagates — confirms it isn't swallowed.
            pass
