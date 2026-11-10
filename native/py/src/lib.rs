use pyo3::exceptions::{PyValueError, PyZeroDivisionError};
use pyo3::prelude::*;

#[pyfunction]
fn char_width(ch: &str) -> PyResult<i64> {
    let mut chars = ch.chars();
    match (chars.next(), chars.next()) {
        (Some(ch), None) => Ok(chplfmt_core::width::char_width(ch)),
        (None, _) => Ok(1),
        (Some(_), Some(_)) if ch < "\u{1100}" => Ok(1),
        _ => Err(PyValueError::new_err("char_width expects one code point")),
    }
}

#[pyfunction(signature = (text, start_col=0, tab_size=2))]
fn display_width(text: &str, start_col: i64, tab_size: i64) -> PyResult<i64> {
    chplfmt_core::width::display_width(text, start_col, tab_size)
        .map_err(PyZeroDivisionError::new_err)
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(char_width, module)?)?;
    module.add_function(wrap_pyfunction!(display_width, module)?)?;
    Ok(())
}
