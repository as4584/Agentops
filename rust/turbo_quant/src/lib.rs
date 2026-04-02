//! TurboQuant: Random rotation + optimal scalar quantization for embedding compression.
//!
//! Rust port of `backend/ml/turbo_quant.py`. Implements the TurboQuant paper
//! algorithm (arXiv:2504.19874) for data-oblivious embedding quantization.
//!
//! Key properties:
//! - Deterministic: same seed → same rotation → same quantized bytes
//! - Cross-language compatible: Python quantize ↔ Rust dequantize (and vice versa)
//! - Zero-copy bit packing for minimal memory overhead

#[cfg(feature = "python")]
pub mod python;

use nalgebra::{DMatrix, DVector};
use rand::SeedableRng;
use rand_chacha::ChaCha8Rng;
use rand::distributions::{Distribution, Standard};

/// TurboQuant quantizer: random rotation + uniform scalar quantization.
pub struct TurboQuantizer {
    dim: usize,
    bits: u8,
    levels: u32,
    seed: u64,
    rotation: Option<DMatrix<f32>>,
}

impl TurboQuantizer {
    /// Create a new quantizer.
    ///
    /// # Arguments
    /// * `dim` - Embedding dimension
    /// * `bits` - Bits per coordinate (2–8). 4 bits ≈ quality neutral.
    /// * `seed` - Random seed for reproducible rotation matrix.
    ///
    /// # Panics
    /// Panics if `bits` is not in [2, 8].
    pub fn new(dim: usize, bits: u8, seed: u64) -> Self {
        assert!((2..=8).contains(&bits), "bits must be 2-8, got {bits}");
        TurboQuantizer {
            dim,
            bits,
            levels: 1u32 << bits,
            seed,
            rotation: None,
        }
    }

    /// Lazily compute and cache the rotation matrix via QR decomposition.
    ///
    /// Generates a random Gaussian matrix, then extracts Q from QR decomp.
    /// Signs are corrected so the rotation is deterministic for a given seed.
    fn rotation_matrix(&mut self) -> &DMatrix<f32> {
        if self.rotation.is_none() {
            let gauss = generate_gaussian_matrix(self.dim, self.seed);

            // QR decomposition
            let qr = gauss.qr();
            let q = qr.q();
            let r = qr.r();

            // Correct signs: multiply columns of Q by sign(diag(R))
            let mut q_corrected = q;
            for j in 0..self.dim {
                let sign = if r[(j, j)] >= 0.0 { 1.0f32 } else { -1.0f32 };
                for i in 0..self.dim {
                    q_corrected[(i, j)] *= sign;
                }
            }

            self.rotation = Some(q_corrected);
        }
        self.rotation.as_ref().unwrap()
    }

    /// Quantize a single embedding vector to compressed bytes.
    ///
    /// Format: `[f32 norm (4 bytes LE)] [packed quantized codes]`
    pub fn quantize(&mut self, embedding: &[f32]) -> Vec<u8> {
        assert_eq!(
            embedding.len(),
            self.dim,
            "Expected dim={}, got {}",
            self.dim,
            embedding.len()
        );

        let emb = DVector::from_column_slice(embedding);
        let norm = emb.norm();

        // Zero vector: return norm=0 + zero packed bytes
        if norm < 1e-12 {
            let n_bytes = (self.dim * self.bits as usize + 7) / 8;
            let mut result = norm.to_le_bytes().to_vec();
            result.extend(std::iter::repeat(0u8).take(n_bytes));
            return result;
        }

        // Normalize to unit sphere
        let unit = &emb / norm;

        // Apply random rotation
        let rot = self.rotation_matrix().clone();
        let rotated = &rot * &unit;

        // Clamp to [-1, 1], scale to [0, levels-1], cast to u8
        let levels_minus_1 = (self.levels - 1) as f32;
        let codes: Vec<u8> = rotated
            .iter()
            .map(|&v| {
                let clamped = v.clamp(-1.0, 1.0);
                let scaled = (clamped + 1.0) / 2.0 * levels_minus_1;
                scaled.round() as u8
            })
            .collect();

        // Pack into bits
        let packed = pack_bits(&codes, self.bits);

        let mut result = norm.to_le_bytes().to_vec();
        result.extend(packed);
        result
    }

    /// Reconstruct an embedding from quantized bytes.
    pub fn dequantize(&mut self, data: &[u8]) -> Vec<f32> {
        assert!(data.len() >= 4, "Data too short for norm header");

        let norm = f32::from_le_bytes([data[0], data[1], data[2], data[3]]);

        if norm < 1e-12 {
            return vec![0.0f32; self.dim];
        }

        let packed = &data[4..];
        let codes = unpack_bits(packed, self.bits, self.dim);

        // Inverse scale: codes → [-1, 1]
        let levels_minus_1 = (self.levels - 1) as f32;
        let restored: Vec<f32> = codes
            .iter()
            .map(|&c| (c as f32 / levels_minus_1) * 2.0 - 1.0)
            .collect();

        let restored_vec = DVector::from_vec(restored);

        // Inverse rotation (Q^T)
        let rot = self.rotation_matrix().clone();
        let unit = rot.transpose() * &restored_vec;

        // Scale back by norm
        unit.iter().map(|&v| v * norm).collect()
    }

    /// Quantize a batch of embeddings.
    pub fn quantize_batch(&mut self, embeddings: &[Vec<f32>]) -> Vec<Vec<u8>> {
        embeddings.iter().map(|e| self.quantize(e)).collect()
    }

    /// Dequantize a batch of compressed embeddings.
    pub fn dequantize_batch(&mut self, data_list: &[Vec<u8>]) -> Vec<Vec<f32>> {
        data_list.iter().map(|d| self.dequantize(d)).collect()
    }

    /// Compression ratio: original_bits / compressed_bits.
    pub fn compression_ratio(&self) -> f64 {
        let original = self.dim as f64 * 32.0;
        let compressed = 32.0 + self.dim as f64 * self.bits as f64;
        original / compressed
    }

    /// Theoretical MSE distortion bound (TurboQuant Theorem 1).
    /// MSE ≤ (3π/2) · (1/4^b) for b bits.
    pub fn distortion_estimate(&self) -> f64 {
        (3.0 * std::f64::consts::PI / 2.0) * (1.0 / 4.0f64.powi(self.bits as i32))
    }

    /// Get dimension.
    pub fn dim(&self) -> usize {
        self.dim
    }

    /// Get bits per coordinate.
    pub fn bits(&self) -> u8 {
        self.bits
    }
}

/// Generate a Gaussian random matrix using Box-Muller transform.
fn generate_gaussian_matrix(dim: usize, seed: u64) -> DMatrix<f32> {
    let mut rng = ChaCha8Rng::seed_from_u64(seed);
    let n = dim * dim;
    let mut values = Vec::with_capacity(n);
    let mut count = 0;
    while count < n {
        let u1: f64 = loop {
            let v: f64 = Standard.sample(&mut rng);
            let u = v.abs().fract();
            if u > 1e-15 {
                break u;
            }
        };
        let u2: f64 = Standard.sample(&mut rng);
        let u2_frac = u2.abs().fract();

        let r = (-2.0 * u1.ln()).sqrt();
        let theta = 2.0 * std::f64::consts::PI * u2_frac;
        values.push((r * theta.cos()) as f32);
        count += 1;
        if count < n {
            values.push((r * theta.sin()) as f32);
            count += 1;
        }
    }
    values.truncate(n);
    DMatrix::from_vec(dim, dim, values)
}

/// Pack u8 code values into a bit-packed byte vector.
/// Each value uses `bits` least-significant bits, packed LSB-first.
pub fn pack_bits(values: &[u8], bits: u8) -> Vec<u8> {
    let total_bits = values.len() * bits as usize;
    let n_bytes = (total_bits + 7) / 8;
    let mut result = vec![0u8; n_bytes];

    let mut bit_offset = 0usize;
    for &val in values {
        for b in 0..bits {
            if (val >> b) & 1 == 1 {
                let byte_idx = bit_offset / 8;
                let bit_idx = bit_offset % 8;
                result[byte_idx] |= 1 << bit_idx;
            }
            bit_offset += 1;
        }
    }
    result
}

/// Unpack bit-packed bytes back to u8 code values.
pub fn unpack_bits(data: &[u8], bits: u8, count: usize) -> Vec<u8> {
    let mut values = Vec::with_capacity(count);
    let mut bit_offset = 0usize;

    for _ in 0..count {
        let mut val = 0u8;
        for b in 0..bits {
            let byte_idx = bit_offset / 8;
            let bit_idx = bit_offset % 8;
            if byte_idx < data.len() && (data[byte_idx] >> bit_idx) & 1 == 1 {
                val |= 1 << b;
            }
            bit_offset += 1;
        }
        values.push(val);
    }
    values
}

// ============================================================================
// Tests — TDD: mirrors backend/tests/test_ml_turbo_quant.py exactly
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    fn make_quantizer() -> TurboQuantizer {
        TurboQuantizer::new(16, 4, 42)
    }

    // -- Bit packing ----------------------------------------------------------

    #[test]
    fn test_pack_unpack_roundtrip_4bit() {
        let values: Vec<u8> = vec![0, 5, 10, 15, 3, 7, 12, 1];
        let packed = pack_bits(&values, 4);
        let unpacked = unpack_bits(&packed, 4, values.len());
        assert_eq!(values, unpacked);
    }

    #[test]
    fn test_pack_unpack_roundtrip_2bit() {
        let values: Vec<u8> = vec![0, 1, 2, 3, 1, 0, 3, 2];
        let packed = pack_bits(&values, 2);
        let unpacked = unpack_bits(&packed, 2, values.len());
        assert_eq!(values, unpacked);
    }

    #[test]
    fn test_pack_unpack_roundtrip_8bit() {
        let values: Vec<u8> = vec![0, 128, 255, 42, 100, 200, 1, 77];
        let packed = pack_bits(&values, 8);
        let unpacked = unpack_bits(&packed, 8, values.len());
        assert_eq!(values, unpacked);
    }

    // -- Quantize / Dequantize ------------------------------------------------

    #[test]
    fn test_quantize_dequantize_roundtrip() {
        let mut q = make_quantizer();
        let vec: Vec<f32> = (0..16).map(|i| (i as f32 - 8.0) * 0.1).collect();

        let packed = q.quantize(&vec);
        assert!(!packed.is_empty());

        let reconstructed = q.dequantize(&packed);
        assert_eq!(reconstructed.len(), 16);

        // MSE should be bounded for 4-bit quantization
        let mse: f32 = vec
            .iter()
            .zip(reconstructed.iter())
            .map(|(a, b)| (a - b) * (a - b))
            .sum::<f32>()
            / 16.0;
        assert!(mse < 1.0, "MSE too high: {mse}");
    }

    #[test]
    fn test_batch_quantize_dequantize() {
        let mut q = make_quantizer();
        let batch: Vec<Vec<f32>> = (0..5)
            .map(|s| (0..16).map(|i| (i as f32 + s as f32) * 0.1).collect())
            .collect();

        let packed = q.quantize_batch(&batch);
        assert_eq!(packed.len(), 5);

        let reconstructed = q.dequantize_batch(&packed);
        assert_eq!(reconstructed.len(), 5);
        for r in &reconstructed {
            assert_eq!(r.len(), 16);
        }
    }

    #[test]
    fn test_compression_ratio() {
        let q = make_quantizer();
        let ratio = q.compression_ratio();
        let expected = (16.0 * 32.0) / (32.0 + 16.0 * 4.0);
        assert!((ratio - expected).abs() < 1e-6);
        assert!(ratio > 1.0);
    }

    #[test]
    fn test_distortion_estimate() {
        let q = make_quantizer();
        let est = q.distortion_estimate();
        assert!(est > 0.0);
        assert!(est < 0.1);
        let expected = (3.0 * std::f64::consts::PI / 2.0) * (1.0 / 4.0f64.powi(4));
        assert!((est - expected).abs() < 1e-10);
    }

    #[test]
    fn test_2bit_quantization() {
        let mut q = TurboQuantizer::new(8, 2, 1);
        let vec = vec![1.0f32; 8];
        let packed = q.quantize(&vec);
        let reconstructed = q.dequantize(&packed);
        assert_eq!(reconstructed.len(), 8);
    }

    #[test]
    fn test_8bit_quantization() {
        let mut q = TurboQuantizer::new(8, 8, 1);
        let vec = vec![1.0, -1.0, 0.5, -0.5, 0.0, 0.25, -0.25, 0.75];
        let packed = q.quantize(&vec);
        let reconstructed = q.dequantize(&packed);
        let mse: f32 = vec
            .iter()
            .zip(reconstructed.iter())
            .map(|(a, b)| (a - b) * (a - b))
            .sum::<f32>()
            / 8.0;
        assert!(mse < 0.01, "8-bit MSE too high: {mse}");
    }

    #[test]
    fn test_zero_vector() {
        let mut q = make_quantizer();
        let vec = vec![0.0f32; 16];
        let packed = q.quantize(&vec);
        let reconstructed = q.dequantize(&packed);
        for &v in &reconstructed {
            assert!(v.abs() < 0.5, "Zero vector reconstruction error: {v}");
        }
    }

    #[test]
    fn test_deterministic() {
        let mut q = make_quantizer();
        let vec = vec![1.0f32; 16];
        let packed1 = q.quantize(&vec);
        let packed2 = q.quantize(&vec);
        assert_eq!(packed1, packed2, "Quantization must be deterministic");
    }

    #[test]
    fn test_different_seeds_different_rotations() {
        let mut q1 = TurboQuantizer::new(8, 4, 1);
        let mut q2 = TurboQuantizer::new(8, 4, 2);
        let vec = vec![1.0f32; 8];
        let p1 = q1.quantize(&vec);
        let p2 = q2.quantize(&vec);
        assert_ne!(p1, p2, "Different seeds should produce different results");
    }

    #[test]
    #[should_panic(expected = "Expected dim=16")]
    fn test_wrong_dimension_panics() {
        let mut q = make_quantizer();
        q.quantize(&[1.0f32; 8]);
    }

    #[test]
    fn test_compression_ratio_by_bits() {
        let dim = 16;
        for bits in 2..=8u8 {
            let q = TurboQuantizer::new(dim, bits, 42);
            let expected = (dim as f64 * 32.0) / (32.0 + dim as f64 * bits as f64);
            assert!((q.compression_ratio() - expected).abs() < 1e-10);
        }
    }

    // -- Rotation matrix properties -------------------------------------------

    #[test]
    fn test_rotation_matrix_is_orthogonal() {
        let mut q = TurboQuantizer::new(16, 4, 42);
        let rot = q.rotation_matrix().clone();
        // Q^T * Q should be identity
        let qtq = rot.transpose() * &rot;
        for i in 0..16 {
            for j in 0..16 {
                let expected = if i == j { 1.0 } else { 0.0 };
                assert!(
                    (qtq[(i, j)] - expected).abs() < 1e-4,
                    "Q^T*Q[{i},{j}] = {}, expected {expected}",
                    qtq[(i, j)]
                );
            }
        }
    }

    #[test]
    fn test_rotation_preserves_norm() {
        let mut q = TurboQuantizer::new(16, 4, 42);
        let vec: Vec<f32> = (0..16).map(|i| i as f32 * 0.3).collect();
        let dv = DVector::from_vec(vec);
        let original_norm = dv.norm();

        let rot = q.rotation_matrix().clone();
        let rotated = &rot * &dv;
        let rotated_norm = rotated.norm();

        assert!(
            (original_norm - rotated_norm).abs() < 1e-4,
            "Rotation changed norm: {original_norm} → {rotated_norm}"
        );
    }
}
