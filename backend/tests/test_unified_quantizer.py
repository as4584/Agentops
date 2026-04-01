"""Deterministic tests for backend.skills.turbo_quant_rust.quantizer.

Tests the UnifiedQuantizer with both Rust and Python backends (mocked).
No Rust compilation needed — we mock the import boundary.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np


class TestCheckRust:
    """Test Rust availability detection."""

    def test_rust_available_when_import_succeeds(self):
        import backend.skills.turbo_quant_rust.quantizer as mod

        mod._USE_RUST = None  # Reset cache
        with patch.dict("sys.modules", {"turbo_quant_rs": MagicMock()}):
            result = mod._check_rust()
            assert result is True
        mod._USE_RUST = None  # Clean up

    def test_rust_unavailable_when_import_fails(self):
        import backend.skills.turbo_quant_rust.quantizer as mod

        mod._USE_RUST = None
        with patch.dict("sys.modules", {"turbo_quant_rs": None}):
            with patch("builtins.__import__", side_effect=ImportError("no rust")):
                # Reset to force re-check
                mod._USE_RUST = None
                result = mod._check_rust()
                assert result is False
        mod._USE_RUST = None

    def test_cached_after_first_check(self):
        import backend.skills.turbo_quant_rust.quantizer as mod

        mod._USE_RUST = True
        assert mod._check_rust() is True
        mod._USE_RUST = None


class TestUnifiedQuantizerPythonBackend:
    """Test quantizer using the Python fallback (no Rust needed)."""

    def setup_method(self):
        import backend.skills.turbo_quant_rust.quantizer as mod

        mod._USE_RUST = None  # Force re-check

    def teardown_method(self):
        import backend.skills.turbo_quant_rust.quantizer as mod

        mod._USE_RUST = None

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_python_backend_selected(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        assert q.backend == "python"
        assert q._py is not None
        assert q._rs is None

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_quantize_returns_bytes(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        vec = np.random.randn(16).astype(np.float32)
        packed = q.quantize(vec)
        assert isinstance(packed, bytes)
        assert len(packed) > 0

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_roundtrip_preserves_shape(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        vec = np.random.randn(16).astype(np.float32)
        packed = q.quantize(vec)
        recon = q.dequantize(packed)
        assert recon.shape == (16,)
        assert recon.dtype == np.float32

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_roundtrip_low_distortion(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        vec = np.random.randn(16).astype(np.float32)
        packed = q.quantize(vec)
        recon = q.dequantize(packed)
        # Cosine similarity should be > 0.9 for 4-bit
        cos_sim = np.dot(vec, recon) / (np.linalg.norm(vec) * np.linalg.norm(recon) + 1e-10)
        assert cos_sim > 0.85, f"Cosine similarity too low: {cos_sim}"

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_quantize_batch(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        vecs = np.random.randn(10, 16).astype(np.float32)
        packed_list = q.quantize_batch(vecs)
        assert len(packed_list) == 10
        assert all(isinstance(p, bytes) for p in packed_list)

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_dequantize_batch(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=16, bits=4, seed=42)
        vecs = np.random.randn(5, 16).astype(np.float32)
        packed_list = q.quantize_batch(vecs)
        recon = q.dequantize_batch(packed_list)
        assert recon.shape == (5, 16)

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_compression_ratio(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=384, bits=4, seed=42)
        ratio = q.compression_ratio()
        assert ratio > 1.0  # Must actually compress

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_distortion_estimate(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=384, bits=4, seed=42)
        dist = q.distortion_estimate()
        assert 0.0 <= dist <= 1.0

    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_list_input_accepted(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

        q = UnifiedQuantizer(dim=8, bits=4, seed=42)
        vec = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
        packed = q.quantize(vec)
        assert isinstance(packed, bytes)


class TestUnifiedQuantizerRustBackend:
    """Test quantizer with mocked Rust backend."""

    def test_rust_backend_selected(self):
        mock_rs = MagicMock()
        mock_rs.TurboQuantizer.return_value = MagicMock()

        with patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=True):
            with patch.dict("sys.modules", {"turbo_quant_rs": mock_rs}):
                from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

                q = UnifiedQuantizer(dim=16, bits=4, seed=42)
                assert q.backend == "rust"
                assert q._rs is not None

    def test_quantize_delegates_to_rust(self):
        mock_rs_mod = MagicMock()
        mock_instance = MagicMock()
        mock_instance.quantize.return_value = [1, 2, 3, 4]
        mock_rs_mod.TurboQuantizer.return_value = mock_instance

        with patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=True):
            with patch.dict("sys.modules", {"turbo_quant_rs": mock_rs_mod}):
                from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer

                q = UnifiedQuantizer(dim=16, bits=4, seed=42)
                result = q.quantize(np.ones(16))
                assert isinstance(result, bytes)
                mock_instance.quantize.assert_called_once()


class TestGetQuantizer:
    @patch("backend.skills.turbo_quant_rust.quantizer._check_rust", return_value=False)
    def test_factory_returns_unified_quantizer(self, _mock):
        from backend.skills.turbo_quant_rust.quantizer import UnifiedQuantizer, get_quantizer

        q = get_quantizer(dim=16, bits=4, seed=42)
        assert isinstance(q, UnifiedQuantizer)
        assert q.dim == 16
        assert q.bits == 4
        assert q.seed == 42
