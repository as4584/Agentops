//! PyO3 bindings for TurboQuant.
//!
//! Exposes TurboQuantizer to Python as a native extension module.
//! Build with: maturin develop --features python
//! Usage from Python:
//!   from turbo_quant import PyTurboQuantizer
//!   q = PyTurboQuantizer(384, 4, 42)
//!   packed = q.quantize(list_of_floats)
//!   reconstructed = q.dequantize(packed)

use pyo3::prelude::*;
use pyo3::types::PyBytes;
use crate::TurboQuantizer;

/// Python-exposed TurboQuantizer wrapper.
#[pyclass(name = "TurboQuantizer")]
pub struct PyTurboQuantizer {
    inner: TurboQuantizer,
}

#[pymethods]
impl PyTurboQuantizer {
    #[new]
    #[pyo3(signature = (dim=384, bits=4, seed=42))]
    fn new(dim: usize, bits: u8, seed: u64) -> PyResult<Self> {
        if !(2..=8).contains(&bits) {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("bits must be 2-8, got {bits}"),
            ));
        }
        Ok(PyTurboQuantizer {
            inner: TurboQuantizer::new(dim, bits, seed),
        })
    }

    /// Quantize a list of f32 values into bytes.
    fn quantize(&mut self, py: Python<'_>, embedding: Vec<f32>) -> PyResult<PyObject> {
        if embedding.len() != self.inner.dim() {
            return Err(pyo3::exceptions::PyValueError::new_err(
                format!("Expected dim={}, got {}", self.inner.dim(), embedding.len()),
            ));
        }
        let packed = self.inner.quantize(&embedding);
        Ok(PyBytes::new_bound(py, &packed).into())
    }

    /// Dequantize bytes back into a list of f32 values.
    fn dequantize(&mut self, data: &[u8]) -> PyResult<Vec<f32>> {
        if data.len() < 4 {
            return Err(pyo3::exceptions::PyValueError::new_err("Data too short"));
        }
        Ok(self.inner.dequantize(data))
    }

    /// Quantize a batch of embeddings.
    fn quantize_batch(&mut self, py: Python<'_>, embeddings: Vec<Vec<f32>>) -> PyResult<Vec<PyObject>> {
        let mut results = Vec::with_capacity(embeddings.len());
        for emb in &embeddings {
            if emb.len() != self.inner.dim() {
                return Err(pyo3::exceptions::PyValueError::new_err(
                    format!("Expected dim={}, got {}", self.inner.dim(), emb.len()),
                ));
            }
            let packed = self.inner.quantize(emb);
            results.push(PyBytes::new_bound(py, &packed).into());
        }
        Ok(results)
    }

    /// Dequantize a batch of compressed embeddings.
    fn dequantize_batch(&mut self, data_list: Vec<Vec<u8>>) -> PyResult<Vec<Vec<f32>>> {
        let mut results = Vec::with_capacity(data_list.len());
        for d in &data_list {
            results.push(self.inner.dequantize(d));
        }
        Ok(results)
    }

    /// Compression ratio.
    fn compression_ratio(&self) -> f64 {
        self.inner.compression_ratio()
    }

    /// Theoretical MSE distortion bound.
    fn distortion_estimate(&self) -> f64 {
        self.inner.distortion_estimate()
    }

    /// Dimension.
    #[getter]
    fn dim(&self) -> usize {
        self.inner.dim()
    }

    /// Bits per coordinate.
    #[getter]
    fn bits(&self) -> u8 {
        self.inner.bits()
    }
}

/// Register the Python module.
#[pymodule]
pub fn turbo_quant_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyTurboQuantizer>()?;
    Ok(())
}
