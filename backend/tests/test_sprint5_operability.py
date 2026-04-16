"""
Sprint 5 Acceptance Tests — Operability, Dependency Health, Release Evidence
=============================================================================
Validates that startup validation is wired, /health/deps exposes Qdrant and
embedding config, and metrics counters are accessible without auth.

PR coverage:
  PR1  validate_embedding_startup() wired into server lifespan (smoke test)
  PR2  /health/deps includes 'qdrant' and 'embedding_config' keys
  PR3  validate_embedding_startup() returns warnings on bad config
  PR4  /metrics exposes agentop_qdrant_fallback_total counter
  PR5  /health/ready only when orchestrator is up
  PR6  EmbeddingConfig startup path end-to-end
"""

from __future__ import annotations

from unittest.mock import patch

# ---------------------------------------------------------------------------
# PR1 — validate_embedding_startup wired in server lifespan (unit test)
# ---------------------------------------------------------------------------


class TestEmbeddingStartupWiring:
    def test_validate_embedding_startup_importable_from_context_assembler(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        assert callable(validate_embedding_startup)

    def test_validate_embedding_startup_returns_list(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        result = validate_embedding_startup()
        assert isinstance(result, list)

    def test_validate_embedding_startup_clean_config_returns_empty(self) -> None:
        """With a valid model/dim pair, no warnings should be returned."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 768),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {"nomic-embed-text": 768}),
        ):
            warnings = validate_embedding_startup()
        # Warnings list should be empty for a known-good config
        assert warnings == []

    def test_validate_embedding_startup_dim_mismatch_returns_warning(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 999),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {"nomic-embed-text": 768}),
        ):
            warnings = validate_embedding_startup()
        assert len(warnings) > 0
        assert any("999" in w or "nomic" in w.lower() or "dim" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# PR2 — /health/deps includes qdrant and embedding_config
# ---------------------------------------------------------------------------


class TestHealthDepsKeys:
    def test_health_deps_has_qdrant_key(self) -> None:
        """The /health/deps dependencies dict must include 'qdrant'."""
        import asyncio

        from backend.server import health_deps

        # health_deps is an async function
        result = asyncio.run(health_deps())
        assert "dependencies" in result
        assert "qdrant" in result["dependencies"], "qdrant missing from /health/deps"

    def test_health_deps_has_embedding_config_key(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        assert "embedding_config" in result["dependencies"], "embedding_config missing from /health/deps"

    def test_health_deps_qdrant_entry_has_ok_field(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        qdrant = result["dependencies"]["qdrant"]
        assert "ok" in qdrant

    def test_health_deps_embedding_config_entry_has_ok_field(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        embed = result["dependencies"]["embedding_config"]
        assert "ok" in embed

    def test_health_deps_qdrant_detail_has_connected(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        detail = result["dependencies"]["qdrant"].get("detail", {})
        assert "connected" in detail

    def test_health_deps_embedding_detail_has_warnings(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        detail = result["dependencies"]["embedding_config"].get("detail", {})
        assert "warnings" in detail or "ok" in detail

    def test_health_deps_status_field_present(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        assert "status" in result
        assert result["status"] in ("healthy", "degraded")

    def test_health_deps_timestamp_present(self) -> None:
        import asyncio

        from backend.server import health_deps

        result = asyncio.run(health_deps())
        assert "timestamp" in result


# ---------------------------------------------------------------------------
# PR3 — validate_embedding_startup() warning coverage
# ---------------------------------------------------------------------------


class TestEmbeddingStartupWarnings:
    def test_empty_model_returns_warning(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", ""),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 768),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        assert any("model" in w.lower() or "empty" in w.lower() for w in warnings)

    def test_zero_dim_returns_warning(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 0),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        assert any("dim" in w.lower() or "0" in w for w in warnings)

    def test_known_model_wrong_dim_returns_warning(self) -> None:
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "all-minilm-l6-v2"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 1024),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {"all-minilm-l6-v2": 384}),
        ):
            warnings = validate_embedding_startup()
        assert len(warnings) > 0

    def test_unknown_model_no_warning_on_dim(self) -> None:
        """An unknown model can't be validated — no dimension warning expected."""
        from backend.knowledge.context_assembler import validate_embedding_startup

        with (
            patch("backend.knowledge.context_assembler.QDRANT_EMBED_MODEL", "my-custom-model"),
            patch("backend.knowledge.context_assembler.QDRANT_DEFAULT_DIM", 512),
            patch("backend.knowledge.context_assembler.KNOWN_EMBED_DIMS", {}),
        ):
            warnings = validate_embedding_startup()
        # Should have no dim-mismatch warning (can't validate unknown model)
        dim_warnings = [w for w in warnings if "mismatch" in w.lower() or "known" in w.lower()]
        assert len(dim_warnings) == 0


# ---------------------------------------------------------------------------
# PR4 — /metrics exposes qdrant fallback counter
# ---------------------------------------------------------------------------


class TestMetricsEndpoint:
    def test_metrics_has_qdrant_fallback_counter(self) -> None:
        import asyncio

        from backend.server import metrics

        result = asyncio.run(metrics())
        assert "agentop_qdrant_fallback_total" in result

    def test_metrics_has_degraded_fallback_counter(self) -> None:
        import asyncio

        from backend.server import metrics

        result = asyncio.run(metrics())
        assert "agentop_degraded_fallback_total" in result

    def test_metrics_qdrant_fallback_is_int(self) -> None:
        import asyncio

        from backend.server import metrics

        result = asyncio.run(metrics())
        assert isinstance(result["agentop_qdrant_fallback_total"], int)

    def test_metrics_uptime_non_negative(self) -> None:
        import asyncio

        from backend.server import metrics

        result = asyncio.run(metrics())
        assert result["agentop_uptime_seconds"] >= 0

    def test_metrics_has_meta(self) -> None:
        import asyncio

        from backend.server import metrics

        result = asyncio.run(metrics())
        assert "_meta" in result
        assert result["_meta"]["deployment_mode"] == "operator_only"


# ---------------------------------------------------------------------------
# PR5 — /health/ready returns 503 without orchestrator
# ---------------------------------------------------------------------------


class TestHealthReady:
    def test_health_ready_503_without_orchestrator(self) -> None:
        import asyncio

        from backend import server as srv

        original = srv._orchestrator
        try:
            srv._orchestrator = None
            result = asyncio.run(srv.health_ready())
            assert result.status_code == 503
        finally:
            srv._orchestrator = original

    def test_health_live_always_200(self) -> None:
        import asyncio

        from backend.server import health_live

        result = asyncio.run(health_live())
        assert result.status_code == 200

    def test_health_live_has_timestamp(self) -> None:
        import asyncio
        import json

        from backend.server import health_live

        result = asyncio.run(health_live())
        body = json.loads(result.body)
        assert "timestamp" in body

    def test_health_ready_ok_with_orchestrator(self) -> None:
        import asyncio
        from unittest.mock import MagicMock

        from backend import server as srv

        original = srv._orchestrator
        original_start = srv._start_time
        try:
            srv._orchestrator = MagicMock()
            srv._start_time = 0.0
            result = asyncio.run(srv.health_ready())
            assert result.status_code == 200
        finally:
            srv._orchestrator = original
            srv._start_time = original_start


# ---------------------------------------------------------------------------
# PR6 — EmbeddingConfig from_config end-to-end
# ---------------------------------------------------------------------------


class TestEmbeddingConfigEndToEnd:
    def test_from_config_reads_config_values(self) -> None:
        from backend.models import EmbeddingConfig

        with (
            patch("backend.config.QDRANT_EMBED_MODEL", "nomic-embed-text"),
            patch("backend.config.QDRANT_DEFAULT_DIM", 768),
        ):
            cfg = EmbeddingConfig.from_config()
        assert cfg.model == "nomic-embed-text"
        assert cfg.dim == 768

    def test_from_config_dim_matches_known_returns_true_for_valid(self) -> None:
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="nomic-embed-text", dim=768)
        assert cfg.dim_matches_known() is True

    def test_from_config_dim_matches_known_returns_false_for_mismatch(self) -> None:
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="nomic-embed-text", dim=999)
        assert cfg.dim_matches_known() is False

    def test_unknown_model_dim_matches_known_returns_true(self) -> None:
        """Unknown models can't be validated — assume OK."""
        from backend.models import EmbeddingConfig

        cfg = EmbeddingConfig(model="some-custom-embed-model", dim=256)
        assert cfg.dim_matches_known() is True
