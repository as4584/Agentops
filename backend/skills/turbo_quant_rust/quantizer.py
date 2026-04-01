"""TurboQuant skill: auto-selects Rust (fast) or Python (fallback) implementation.

Usage by agents:
    from backend.skills.turbo_quant_rust.quantizer import get_quantizer
    q = get_quantizer(dim=384, bits=4, seed=42)
    packed = q.quantize(embedding)
    recon = q.dequantize(packed)
"""

from __future__ import annotations

import numpy as np

from backend.utils import logger

_USE_RUST: bool | None = None


def _check_rust() -> bool:
    global _USE_RUST
    if _USE_RUST is not None:
        return _USE_RUST
    try:
        import turbo_quant_rs  # noqa: F401

        _USE_RUST = True
        logger.info("[TurboQuant] Using Rust-accelerated backend (turbo_quant_rs)")
    except ImportError:
        _USE_RUST = False
        logger.info("[TurboQuant] Rust backend not available, falling back to Python")
    return _USE_RUST


class UnifiedQuantizer:
    """Unified interface — delegates to Rust or Python TurboQuantizer."""

    def __init__(self, dim: int = 384, bits: int = 4, seed: int = 42) -> None:
        self.dim = dim
        self.bits = bits
        self.seed = seed
        self._backend = "rust" if _check_rust() else "python"

        if self._backend == "rust":
            import turbo_quant_rs

            self._rs = turbo_quant_rs.TurboQuantizer(dim=dim, bits=bits, seed=seed)  # type: ignore[attr-defined]
            self._py = None
        else:
            from backend.ml.turbo_quant import TurboQuantizer

            self._py = TurboQuantizer(dim=dim, bits=bits, seed=seed)
            self._rs = None

    @property
    def backend(self) -> str:
        return self._backend

    def quantize(self, embedding: np.ndarray | list[float]) -> bytes:
        if self._rs is not None:
            vec = list(embedding) if isinstance(embedding, np.ndarray) else embedding
            return bytes(self._rs.quantize(vec))
        assert self._py is not None
        emb = np.asarray(embedding, dtype=np.float32)
        return self._py.quantize(emb)

    def dequantize(self, data: bytes) -> np.ndarray:
        if self._rs is not None:
            result = self._rs.dequantize(data)
            return np.array(result, dtype=np.float32)
        assert self._py is not None
        return self._py.dequantize(data)

    def quantize_batch(self, embeddings: np.ndarray | list) -> list[bytes]:
        if self._rs is not None:
            vecs = [list(e) for e in embeddings]
            return [bytes(p) for p in self._rs.quantize_batch(vecs)]
        assert self._py is not None
        return self._py.quantize_batch(np.asarray(embeddings, dtype=np.float32))

    def dequantize_batch(self, data_list: list[bytes]) -> np.ndarray:
        if self._rs is not None:
            results = self._rs.dequantize_batch([list(d) for d in data_list])
            return np.array(results, dtype=np.float32)
        assert self._py is not None
        return self._py.dequantize_batch(data_list)

    def compression_ratio(self) -> float:
        if self._rs is not None:
            return self._rs.compression_ratio()
        assert self._py is not None
        return self._py.compression_ratio()

    def distortion_estimate(self) -> float:
        if self._rs is not None:
            return self._rs.distortion_estimate()
        assert self._py is not None
        return self._py.distortion_estimate()


def get_quantizer(dim: int = 384, bits: int = 4, seed: int = 42) -> UnifiedQuantizer:
    """Factory: returns the fastest available TurboQuantizer."""
    return UnifiedQuantizer(dim=dim, bits=bits, seed=seed)
