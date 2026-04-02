//! Benchmark: TurboQuant quantize/dequantize throughput.
//!
//! Run: cargo bench --bench quantize_bench
//! Compare with Python: python -c "from backend.ml.turbo_quant import TurboQuantizer; ..."

use criterion::{black_box, criterion_group, criterion_main, Criterion, BenchmarkId};
use turbo_quant::TurboQuantizer;

fn bench_quantize(c: &mut Criterion) {
    let mut group = c.benchmark_group("quantize");

    for dim in [16, 128, 384, 768] {
        let embedding: Vec<f32> = (0..dim).map(|i| (i as f32 - dim as f32 / 2.0) * 0.01).collect();

        group.bench_with_input(
            BenchmarkId::new("4bit", dim),
            &embedding,
            |b, emb| {
                let mut q = TurboQuantizer::new(dim, 4, 42);
                // Warm up rotation matrix
                let _ = q.quantize(emb);
                b.iter(|| q.quantize(black_box(emb)));
            },
        );
    }
    group.finish();
}

fn bench_dequantize(c: &mut Criterion) {
    let mut group = c.benchmark_group("dequantize");

    for dim in [16, 128, 384, 768] {
        let embedding: Vec<f32> = (0..dim).map(|i| (i as f32 - dim as f32 / 2.0) * 0.01).collect();
        let mut q = TurboQuantizer::new(dim, 4, 42);
        let packed = q.quantize(&embedding);

        group.bench_with_input(
            BenchmarkId::new("4bit", dim),
            &packed,
            |b, data| {
                b.iter(|| q.dequantize(black_box(data)));
            },
        );
    }
    group.finish();
}

fn bench_roundtrip_batch(c: &mut Criterion) {
    let mut group = c.benchmark_group("batch_roundtrip");

    for batch_size in [10, 100, 1000] {
        let dim = 384;
        let batch: Vec<Vec<f32>> = (0..batch_size)
            .map(|s| (0..dim).map(|i| (i as f32 + s as f32) * 0.001).collect())
            .collect();

        group.bench_with_input(
            BenchmarkId::new("384d_4bit", batch_size),
            &batch,
            |b, embs| {
                let mut q = TurboQuantizer::new(dim, 4, 42);
                // Warm up rotation
                let _ = q.quantize(&embs[0]);
                b.iter(|| {
                    let packed = q.quantize_batch(black_box(embs));
                    q.dequantize_batch(black_box(&packed))
                });
            },
        );
    }
    group.finish();
}

fn bench_rotation_init(c: &mut Criterion) {
    let mut group = c.benchmark_group("rotation_init");

    for dim in [16, 128, 384, 768] {
        group.bench_function(BenchmarkId::new("qr_decomp", dim), |b| {
            b.iter(|| {
                let mut q = TurboQuantizer::new(black_box(dim), 4, 42);
                // Force rotation matrix computation
                let _ = q.quantize(&vec![1.0; dim]);
            });
        });
    }
    group.finish();
}

criterion_group!(benches, bench_quantize, bench_dequantize, bench_roundtrip_batch, bench_rotation_init);
criterion_main!(benches);
