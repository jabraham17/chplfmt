use chplfmt_core::doc::HostError;
use chplfmt_core::render::{self as core, LineRecord as CoreLineRecord, RenderOptions};
use pyo3::class::basic::CompareOp;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::{PyAny, PyList, PyModule};

use crate::doc::doclike;

fn host_error(error: HostError) -> PyErr {
    match error.0.downcast::<PyErr>() {
        Ok(error) => *error,
        Err(error) => PyRuntimeError::new_err(error.to_string()),
    }
}

#[pyclass(frozen, name = "LineRecord")]
struct PyLineRecord {
    records: Arc<Vec<CoreLineRecord>>,
    index: usize,
}

impl PyLineRecord {
    fn value(&self) -> &CoreLineRecord {
        &self.records[self.index]
    }
}

#[pymethods]
impl PyLineRecord {
    #[new]
    #[pyo3(signature = (code, trailing_comment=None, verbatim=false))]
    fn new(code: String, trailing_comment: Option<String>, verbatim: bool) -> Self {
        Self {
            records: Arc::new(vec![CoreLineRecord {
                code,
                trailing_comment,
                verbatim,
            }]),
            index: 0,
        }
    }

    #[getter]
    fn code(&self) -> &str {
        &self.value().code
    }

    #[getter]
    fn trailing_comment(&self) -> Option<&str> {
        self.value().trailing_comment.as_deref()
    }

    #[getter]
    fn verbatim(&self) -> bool {
        self.value().verbatim
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> bool {
        let equal = other
            .extract::<PyRef<'_, Self>>()
            .is_ok_and(|other| self.value() == other.value());
        match op {
            CompareOp::Eq => equal,
            CompareOp::Ne => !equal,
            _ => false,
        }
    }
}

#[pyclass(frozen, name = "RenderStats")]
struct PyRenderStats {
    fits_scans: u64,
    all_lines_dry_runs: u64,
    memo_hits: u64,
}

#[pymethods]
impl PyRenderStats {
    #[getter]
    fn fits_scans(&self) -> u64 {
        self.fits_scans
    }

    #[getter]
    fn all_lines_dry_runs(&self) -> u64 {
        self.all_lines_dry_runs
    }

    #[getter]
    fn memo_hits(&self) -> u64 {
        self.memo_hits
    }
}

#[pyclass(frozen, name = "RenderResult")]
struct PyRenderResult {
    text: String,
    records: Arc<Vec<CoreLineRecord>>,
    stats: core::RenderStats,
    lines: GILOnceCell<Py<PyList>>,
}

#[pymethods]
impl PyRenderResult {
    #[getter]
    fn text(&self) -> &str {
        &self.text
    }

    #[getter]
    fn lines(&self, py: Python<'_>) -> PyResult<Py<PyList>> {
        Ok(self
            .lines
            .get_or_try_init(py, || {
                let records = (0..self.records.len())
                    .map(|index| {
                        Py::new(
                            py,
                            PyLineRecord {
                                records: self.records.clone(),
                                index,
                            },
                        )
                    })
                    .collect::<PyResult<Vec<_>>>()?;
                Ok::<_, PyErr>(PyList::new(py, records)?.unbind())
            })?
            .clone_ref(py))
    }

    #[getter]
    fn stats(&self, py: Python<'_>) -> PyResult<Py<PyRenderStats>> {
        Py::new(
            py,
            PyRenderStats {
                fits_scans: self.stats.fits_scans,
                all_lines_dry_runs: self.stats.all_lines_dry_runs,
                memo_hits: self.stats.memo_hits,
            },
        )
    }
}

#[pyfunction(signature = (doc, line_length, tab_size, base_indent=0))]
fn render(
    doc: &Bound<'_, PyAny>,
    line_length: u32,
    tab_size: u32,
    base_indent: u32,
) -> PyResult<PyRenderResult> {
    let value = core::render(
        &doclike(doc)?,
        RenderOptions {
            line_length,
            tab_size,
        },
        base_indent,
    )
    .map_err(host_error)?;
    Ok(PyRenderResult {
        text: value.text,
        records: Arc::new(value.lines),
        stats: value.stats,
        lines: GILOnceCell::new(),
    })
}

#[pyfunction(signature = (doc, line_length, tab_size, base_indent=0))]
fn render_text(
    doc: &Bound<'_, PyAny>,
    line_length: u32,
    tab_size: u32,
    base_indent: u32,
) -> PyResult<String> {
    core::render_text(
        &doclike(doc)?,
        RenderOptions {
            line_length,
            tab_size,
        },
        base_indent,
    )
    .map_err(host_error)
}

#[pyfunction]
fn flat_width(doc: &Bound<'_, PyAny>, tab_size: u32) -> PyResult<Option<u32>> {
    core::flat_width(&doclike(doc)?, tab_size).map_err(host_error)
}

#[pyfunction]
fn align_trailing_comments(
    lines: &Bound<'_, PyAny>,
    line_length: u32,
    tab_size: u32,
) -> PyResult<Vec<String>> {
    let records: Vec<Py<PyLineRecord>> = lines
        .try_iter()?
        .map(|line| line?.extract())
        .collect::<PyResult<Vec<_>>>()?;
    let records: Vec<_> = records
        .iter()
        .map(|record| record.borrow(lines.py()))
        .collect();
    Ok(core::align_trailing_comments(
        records.iter().map(|record| record.value()),
        line_length,
        tab_size,
    ))
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_class::<PyLineRecord>()?;
    module.add_class::<PyRenderResult>()?;
    module.add_class::<PyRenderStats>()?;
    module.add_function(wrap_pyfunction!(render, module)?)?;
    module.add_function(wrap_pyfunction!(render_text, module)?)?;
    module.add_function(wrap_pyfunction!(flat_width, module)?)?;
    module.add_function(wrap_pyfunction!(align_trailing_comments, module)?)?;
    Ok(())
}
use std::sync::Arc;
