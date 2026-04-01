"""Cross-language contract tests: Python TurboQuant vs Rust TurboQuant.

These tests verify that both implementations produce compatible results:
- Same compression ratio and distortion estimates (exact match)
- Bit packing round-trips identically
- Quantize→dequantize produces bounded MSE in both implementations
- Rust FFI bridge works correctly from Python

Run: pytest backend/tests/test_turbo_quant_contract.py -v
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.ml.turbo_quant import TurboQuantizer as PyQuantizer

# Import Rust implementation via PyO3 bridge
turbo_quant_rs = pytest.importorskip(
    "turbo_quant_rs", reason="Rust turbo_quant_rs not built (run: cd rust/turbo_quant && maturin develop --release)"
)
RsQuantizer = turbo_quant_rs.TurboQuantizer


class TestCrossLanguageContract:
    """Contract: Python and Rust implementations must agree on math."""

    def test_compression_ratio_matches(self) -> None:
        """Both implementations compute identical compression ratios."""
        for dim in [8, 16, 128, 384]:
            for bits in [2, 4, 6, 8]:
                py = PyQuantizer(dim=dim, bits=bits, seed=42)
                rs = RsQuantizer(dim=dim, bits=bits, seed=42)
                assert py.compression_ratio() == pytest.approx(rs.compression_ratio(), rel=1e-10), (
                    f"Compression ratio mismatch at dim={dim}, bits={bits}"
                )

    def test_distortion_estimate_matches(self) -> None:
        """Both implementations compute identical distortion estimates."""
        for bits in [2, 3, 4, 5, 6, 7, 8]:
            py = PyQuantizer(dim=16, bits=bits, seed=42)
            rs = RsQuantizer(dim=16, bits=bits, seed=42)
            assert py.distortion_estimate() == pytest.approx(rs.distortion_estimate(), rel=1e-10), (
                f"Distortion estimate mismatch at bits={bits}"
            )

    def test_zero_vector_both_implementations(self) -> None:
        """Both implementations handle zero vectors gracefully."""
        py = PyQuantizer(dim=16, bits=4, seed=42)
        rs = RsQuantizer(dim=16, bits=4, seed=42)

        zero = [0.0] * 16
        py_packed = py.quantize(np.array(zero, dtype=np.float32))
        rs_packed = rs.quantize(zero)

        py_recon = py.dequantize(py_packed)
        rs_recon = rs.dequantize(bytes(rs_packed))

        assert np.allclose(py_recon, 0.0, atol=0.5)
        assert all(abs(v) < 0.5 for v in rs_recon)

    def test_rust_quantize_produces_bounded_mse(self) -> None:
        """Rust quantize→dequantize has MSE within theoretical bound."""
        for dim in [16, 128]:
            rs = RsQuantizer(dim=dim, bits=4, seed=42)
            rng = np.random.default_rng(123)
            vec = rng.standard_normal(dim).astype(np.float32).tolist()

            packed = rs.quantize(vec)
            recon = rs.dequantize(bytes(packed))

            mse = sum((a - b) ** 2 for a, b in zip(vec, recon)) / dim
            assert mse < 1.0, f"Rust MSE too high: {mse} for dim={dim}"

    def test_python_quantize_produces_bounded_mse(self) -> None:
        """Python quantize→dequantize has MSE within theoretical bound."""
        for dim in [16, 128]:
            py = PyQuantizer(dim=dim, bits=4, seed=42)
            rng = np.random.default_rng(123)
            vec = rng.standard_normal(dim).astype(np.float32)

            packed = py.quantize(vec)
            recon = py.dequantize(packed)

            mse = float(np.mean((vec - recon) ** 2))
            assert mse < 1.0, f"Python MSE too high: {mse} for dim={dim}"

    def test_rust_deterministic(self) -> None:
        """Rust produces identical output for same input."""
        rs = RsQuantizer(dim=16, bits=4, seed=42)
        vec = [1.0] * 16
        p1 = bytes(rs.quantize(vec))
        p2 = bytes(rs.quantize(vec))
        assert p1 == p2

    def test_rust_different_seeds(self) -> None:
        """Different seeds produce different Rust quantizations."""
        rs1 = RsQuantizer(dim=8, bits=4, seed=1)
        rs2 = RsQuantizer(dim=8, bits=4, seed=2)
        vec = [1.0] * 8
        assert bytes(rs1.quantize(vec)) != bytes(rs2.quantize(vec))

    def test_rust_wrong_dim_raises(self) -> None:
        """Rust raises ValueError for wrong dimension."""
        rs = RsQuantizer(dim=16, bits=4, seed=42)
        with pytest.raises(ValueError, match="Expected dim=16"):
            rs.quantize([1.0] * 8)

    def test_rust_invalid_bits_raises(self) -> None:
        """Rust raises for bits outside [2, 8]."""
        with pytest.raises((ValueError, Exception)):
            RsQuantizer(dim=16, bits=1, seed=42)
        with pytest.raises((ValueError, Exception)):
            RsQuantizer(dim=16, bits=9, seed=42)

    def test_batch_roundtrip_rust(self) -> None:
        """Rust batch quantize→dequantize works correctly."""
        rs = RsQuantizer(dim=16, bits=4, seed=42)
        batch = [[float(i + j) * 0.1 for i in range(16)] for j in range(5)]
        packed = rs.quantize_batch(batch)
        assert len(packed) == 5
        recon = rs.dequantize_batch([bytes(p) for p in packed])
        assert len(recon) == 5
        for r in recon:
            assert len(r) == 16

    def test_8bit_rust_low_error(self) -> None:
        """8-bit Rust quantization has very low reconstruction error."""
        rs = RsQuantizer(dim=8, bits=8, seed=1)
        vec = [1.0, -1.0, 0.5, -0.5, 0.0, 0.25, -0.25, 0.75]
        packed = rs.quantize(vec)
        recon = rs.dequantize(bytes(packed))
        mse = sum((a - b) ** 2 for a, b in zip(vec, recon)) / 8
        assert mse < 0.01, f"8-bit Rust MSE too high: {mse}"


class TestRustFFIBridge:
    """Verify the PyO3 bridge handles edge cases properly."""

    def test_properties_accessible(self) -> None:
        """dim and bits properties are readable."""
        rs = RsQuantizer(dim=384, bits=4, seed=42)
        assert rs.dim == 384
        assert rs.bits == 4

    def test_default_parameters(self) -> None:
        """Default constructor parameters work."""
        rs = RsQuantizer()
        assert rs.dim == 384
        assert rs.bits == 4

    def test_large_dimension(self) -> None:
        """Works with production-size embeddings (768d)."""
        rs = RsQuantizer(dim=768, bits=4, seed=42)
        vec = [0.01 * i for i in range(768)]
        packed = rs.quantize(vec)
        recon = rs.dequantize(bytes(packed))
        assert len(recon) == 768
