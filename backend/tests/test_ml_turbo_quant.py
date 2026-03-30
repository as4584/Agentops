"""Tests for TurboQuant-inspired Quantization."""

from __future__ import annotations

import pytest
import numpy as np

from backend.ml.turbo_quant import TurboQuantizer


@pytest.fixture
def quantizer() -> TurboQuantizer:
    return TurboQuantizer(dim=16, bits=4, seed=42)


class TestTurboQuantizer:
    def test_quantize_dequantize_roundtrip(self, quantizer: TurboQuantizer) -> None:
        rng = np.random.default_rng(123)
        vec = rng.standard_normal(16).astype(np.float32)
        packed = quantizer.quantize(vec)
        assert isinstance(packed, bytes)
        reconstructed = quantizer.dequantize(packed)
        assert reconstructed.shape == vec.shape
        # Reconstruction error should be bounded
        mse = np.mean((vec - reconstructed) ** 2)
        assert mse < 1.0  # Reasonable for 4-bit quantization

    def test_batch_quantize_dequantize(self, quantizer: TurboQuantizer) -> None:
        rng = np.random.default_rng(456)
        vecs = rng.standard_normal((5, 16)).astype(np.float32)
        packed_list = quantizer.quantize_batch(vecs)
        assert len(packed_list) == 5
        reconstructed = quantizer.dequantize_batch(packed_list)
        assert reconstructed.shape == vecs.shape

    def test_compression_ratio(self, quantizer: TurboQuantizer) -> None:
        ratio = quantizer.compression_ratio()
        # original = dim*32, compressed = 32 (norm) + dim*bits
        # dim=16, bits=4 → 512 / (32 + 64) = 5.333
        assert ratio > 1.0
        expected = (16 * 32) / (32 + 16 * 4)
        assert ratio == pytest.approx(expected)

    def test_distortion_estimate(self, quantizer: TurboQuantizer) -> None:
        est = quantizer.distortion_estimate()
        assert est > 0.0
        # Theorem 1: MSE ≤ (3π/2) · 1/4^b for unit vectors
        # For 4-bit: (3π/2) · 1/256 ≈ 0.0184
        assert est < 0.1

    def test_2bit_quantization(self) -> None:
        q = TurboQuantizer(dim=8, bits=2, seed=1)
        vec = np.ones(8, dtype=np.float32)
        packed = q.quantize(vec)
        reconstructed = q.dequantize(packed)
        assert reconstructed.shape == (8,)

    def test_8bit_quantization(self) -> None:
        q = TurboQuantizer(dim=8, bits=8, seed=1)
        vec = np.array([1.0, -1.0, 0.5, -0.5, 0.0, 0.25, -0.25, 0.75], dtype=np.float32)
        packed = q.quantize(vec)
        reconstructed = q.dequantize(packed)
        mse = np.mean((vec - reconstructed) ** 2)
        # 8-bit should have very low error
        assert mse < 0.01

    def test_zero_vector(self, quantizer: TurboQuantizer) -> None:
        vec = np.zeros(16, dtype=np.float32)
        packed = quantizer.quantize(vec)
        reconstructed = quantizer.dequantize(packed)
        assert np.allclose(reconstructed, 0.0, atol=0.5)

    def test_deterministic(self, quantizer: TurboQuantizer) -> None:
        vec = np.array([1.0] * 16, dtype=np.float32)
        packed1 = quantizer.quantize(vec)
        packed2 = quantizer.quantize(vec)
        assert packed1 == packed2

    def test_different_seeds_different_rotations(self) -> None:
        q1 = TurboQuantizer(dim=8, bits=4, seed=1)
        q2 = TurboQuantizer(dim=8, bits=4, seed=2)
        vec = np.ones(8, dtype=np.float32)
        p1 = q1.quantize(vec)
        p2 = q2.quantize(vec)
        # Different seeds → different random rotations → different packed bytes
        # (could be same by extreme coincidence, but very unlikely)
        assert p1 != p2

    def test_wrong_dimension_raises(self, quantizer: TurboQuantizer) -> None:
        with pytest.raises((ValueError, IndexError)):
            quantizer.quantize(np.ones(8, dtype=np.float32))

    def test_compression_ratio_by_bits(self) -> None:
        dim = 16
        for bits in [2, 3, 4, 5, 6, 7, 8]:
            q = TurboQuantizer(dim=dim, bits=bits)
            expected = (dim * 32) / (32 + dim * bits)
            assert q.compression_ratio() == pytest.approx(expected)
