"""Benchmark Python TurboQuant for comparison with Rust port."""

import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from backend.ml.turbo_quant import TurboQuantizer


def bench(label: str, fn, iterations: int = 100):
    # warmup
    fn()
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        times.append(t1 - t0)
    median = sorted(times)[len(times) // 2]
    mean = sum(times) / len(times)
    print(f"{label:40s}  median={fmt(median):>12s}  mean={fmt(mean):>12s}")
    return median


def fmt(ns: float) -> str:
    if ns < 1_000:
        return f"{ns:.0f} ns"
    elif ns < 1_000_000:
        return f"{ns / 1_000:.2f} µs"
    elif ns < 1_000_000_000:
        return f"{ns / 1_000_000:.2f} ms"
    else:
        return f"{ns / 1_000_000_000:.2f} s"


print("=" * 72)
print("Python TurboQuant Benchmark (compare with: cargo bench)")
print("=" * 72)

results = {}

for dim in [16, 128, 384, 768]:
    q = TurboQuantizer(dim=dim, bits=4, seed=42)
    vec = np.random.default_rng(123).standard_normal(dim).astype(np.float32)

    # Force rotation matrix init
    _ = q.quantize(vec)

    # Quantize (rotation already cached)
    py_q = bench(f"quantize/4bit/{dim}", lambda: q.quantize(vec))
    results[f"quantize_{dim}"] = py_q

    packed = q.quantize(vec)
    py_d = bench(f"dequantize/4bit/{dim}", lambda: q.dequantize(packed))
    results[f"dequantize_{dim}"] = py_d

print()

# Batch benchmark
for batch_size in [10, 100, 1000]:
    dim = 384
    q = TurboQuantizer(dim=dim, bits=4, seed=42)
    rng = np.random.default_rng(456)
    batch = rng.standard_normal((batch_size, dim)).astype(np.float32)
    _ = q.quantize(batch[0])  # warm rotation

    py_b = bench(
        f"batch_roundtrip/384d_4bit/{batch_size}",
        lambda: q.dequantize_batch(q.quantize_batch(batch)),
        iterations=10 if batch_size >= 1000 else 50,
    )
    results[f"batch_{batch_size}"] = py_b

print()

# Rotation init
for dim in [16, 128, 384, 768]:
    py_r = bench(
        f"rotation_init/qr_decomp/{dim}",
        lambda: TurboQuantizer(dim=dim, bits=4, seed=42).quantize(np.ones(dim, dtype=np.float32)),
        iterations=20,
    )
    results[f"rotation_{dim}"] = py_r

# Rust numbers (from cargo bench run)
rust = {
    "quantize_16": 213,  # 213 ns
    "quantize_128": 3_333,  # 3.33 µs
    "quantize_384": 24_309,  # 24.3 µs
    "quantize_768": 221_630,  # 222 µs
    "dequantize_16": 232,  # 232 ns
    "dequantize_128": 8_720,  # 8.72 µs
    "dequantize_384": 103_370,  # 103 µs
    "dequantize_768": 722_130,  # 722 µs
}

print()
print("=" * 72)
print(f"{'Operation':<35s} {'Python':>12s} {'Rust':>12s} {'Speedup':>8s}")
print("-" * 72)
for key in [
    "quantize_16",
    "quantize_128",
    "quantize_384",
    "quantize_768",
    "dequantize_16",
    "dequantize_128",
    "dequantize_384",
    "dequantize_768",
]:
    if key in results and key in rust:
        py_ns = results[key]
        rs_ns = rust[key]
        speedup = py_ns / rs_ns if rs_ns > 0 else 0
        print(f"{key:<35s} {fmt(py_ns):>12s} {fmt(rs_ns):>12s} {speedup:>7.1f}x")
print("=" * 72)
