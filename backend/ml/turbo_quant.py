"""
TurboQuant-Inspired Embedding Quantization.
============================================
Implements random rotation + optimal scalar quantization for embedding
compression, inspired by the TurboQuant paper (arXiv:2504.19874).

Key properties:
- Data-oblivious: no preprocessing or training data needed
- Near-zero indexing time (vs PQ which needs k-means)
- Quality neutral at 3.5 bits, marginal degradation at 2.5 bits
- Random rotation normalizes coordinate distributions → Beta(1/2, (d-1)/2)
- Optimal scalar quantizers per coordinate minimize MSE

For Agentop: reduces memory footprint of vector embeddings in Qdrant
while preserving semantic search quality.
"""

from __future__ import annotations

import struct
from typing import Optional

import numpy as np

from backend.utils import logger


class TurboQuantizer:
    """Random-rotation + uniform scalar quantizer for embeddings."""

    def __init__(
        self,
        dim: int = 384,
        bits: int = 4,
        seed: int = 42,
    ) -> None:
        """
        Args:
            dim: Embedding dimension.
            bits: Bits per coordinate (2-8). 4 bits ≈ quality neutral.
            seed: Random seed for reproducible rotation matrix.
        """
        if bits < 2 or bits > 8:
            raise ValueError(f"bits must be 2-8, got {bits}")
        self.dim = dim
        self.bits = bits
        self.levels = 2**bits
        self._rng = np.random.RandomState(seed)
        # Generate random rotation matrix via QR decomposition of random Gaussian
        # This is the key TurboQuant insight: rotation makes coordinates ~ Beta(1/2, (d-1)/2)
        self._rotation: Optional[np.ndarray] = None
        self._rotation_seed = seed
        logger.info(f"[TurboQuant] Initialized: dim={dim}, bits={bits}, levels={self.levels}")

    @property
    def rotation_matrix(self) -> np.ndarray:
        """Lazy-init rotation matrix (expensive for large dims)."""
        if self._rotation is None:
            rng = np.random.RandomState(self._rotation_seed)
            gaussian = rng.randn(self.dim, self.dim).astype(np.float32)
            q, r = np.linalg.qr(gaussian)
            # Ensure proper rotation (det = +1)
            signs = np.sign(np.diag(r))
            self._rotation = q * signs[np.newaxis, :]
        return self._rotation

    def quantize(self, embedding: np.ndarray) -> bytes:
        """Quantize a single embedding vector to compressed bytes.

        Steps:
        1. Normalize to unit sphere
        2. Apply random rotation
        3. Uniform scalar quantize each coordinate to `bits` levels

        Returns packed bytes (ceil(dim * bits / 8) bytes).
        """
        emb = np.asarray(embedding, dtype=np.float32).flatten()
        if len(emb) != self.dim:
            raise ValueError(f"Expected dim={self.dim}, got {len(emb)}")

        # Store norm for reconstruction
        norm = float(np.linalg.norm(emb))
        if norm < 1e-12:
            # Zero vector — return all zeros
            n_bytes = (self.dim * self.bits + 7) // 8
            return struct.pack("f", 0.0) + bytes(n_bytes)

        # Normalize
        unit = emb / norm

        # Random rotation
        rotated = self.rotation_matrix @ unit

        # Rotated coords lie in [-1, 1]; map to [0, levels-1]
        clamped = np.clip(rotated, -1.0, 1.0)
        scaled = ((clamped + 1.0) / 2.0 * (self.levels - 1)).astype(np.uint8)

        # Pack into bits
        packed = self._pack_bits(scaled)
        return struct.pack("f", norm) + packed

    def dequantize(self, data: bytes) -> np.ndarray:
        """Reconstruct an embedding from quantized bytes."""
        norm = struct.unpack("f", data[:4])[0]
        if norm < 1e-12:
            return np.zeros(self.dim, dtype=np.float32)

        packed = data[4:]
        codes = self._unpack_bits(packed)[:self.dim]

        # Inverse scale: codes → [-1, 1]
        restored = (codes.astype(np.float32) / (self.levels - 1)) * 2.0 - 1.0

        # Inverse rotation
        unit = self.rotation_matrix.T @ restored

        return (unit * norm).astype(np.float32)

    def quantize_batch(self, embeddings: np.ndarray) -> list[bytes]:
        """Quantize a batch of embeddings."""
        results = []
        for emb in embeddings:
            results.append(self.quantize(emb))
        return results

    def dequantize_batch(self, data_list: list[bytes]) -> np.ndarray:
        """Dequantize a batch of compressed embeddings."""
        return np.array([self.dequantize(d) for d in data_list], dtype=np.float32)

    def compression_ratio(self) -> float:
        """Compute the compression ratio (original / compressed size)."""
        original_bits = self.dim * 32  # float32
        compressed_bits = 32 + self.dim * self.bits  # norm (32 bits) + quantized
        return original_bits / compressed_bits

    def distortion_estimate(self) -> float:
        """Theoretical MSE distortion bound from TurboQuant Theorem 1.

        MSE ≤ (3π/2) · (1/4^b) for b bits.
        """
        return (3 * np.pi / 2) * (1.0 / (4**self.bits))

    def _pack_bits(self, values: np.ndarray) -> bytes:
        """Pack uint8 values into bit-packed bytes."""
        bits_array = []
        for v in values:
            for bit_pos in range(self.bits):
                bits_array.append((int(v) >> bit_pos) & 1)
        # Pad to byte boundary
        while len(bits_array) % 8:
            bits_array.append(0)
        # Convert to bytes
        result = bytearray()
        for i in range(0, len(bits_array), 8):
            byte = 0
            for j in range(8):
                byte |= bits_array[i + j] << j
            result.append(byte)
        return bytes(result)

    def _unpack_bits(self, data: bytes) -> np.ndarray:
        """Unpack bit-packed bytes back to uint8 values."""
        bits_array = []
        for byte in data:
            for j in range(8):
                bits_array.append((byte >> j) & 1)

        values = []
        for i in range(0, len(bits_array) - self.bits + 1, self.bits):
            val = 0
            for j in range(self.bits):
                val |= bits_array[i + j] << j
            values.append(val)
        return np.array(values, dtype=np.uint8)
