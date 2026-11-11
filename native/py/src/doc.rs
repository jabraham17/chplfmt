use std::sync::{Arc, LazyLock};

use chplfmt_core::doc::{
    Check as CoreCheck, Doc as CoreDoc, GroupId as CoreGroupId, HostError, Kind, LineKind,
};
use pyo3::class::basic::CompareOp;
use pyo3::conversion::IntoPyObjectExt;
use pyo3::exceptions::{PyRuntimeError, PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::{PyAny, PyModule, PyTuple};

#[pyclass(frozen, name = "Doc")]
pub struct PyDoc {
    value: CoreDoc,
    callback: Option<Py<PyAny>>,
}

#[pyclass(frozen, name = "GroupId")]
pub struct PyGroupId {
    value: CoreGroupId,
}

#[pymethods]
impl PyGroupId {
    #[new]
    #[pyo3(signature = (name="g"))]
    fn new(name: &str) -> Self {
        Self {
            value: CoreGroupId::new(name),
        }
    }

    #[getter]
    fn name(&self) -> &str {
        &self.value.name
    }

    fn __repr__(&self, py: Python<'_>) -> PyResult<String> {
        Ok(format!(
            "GroupId({})",
            self.value.name.as_ref().into_py_any(py)?.bind(py).repr()?
        ))
    }

    fn __hash__(&self) -> u32 {
        self.value.id
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> bool {
        let equal = other
            .extract::<PyRef<'_, Self>>()
            .is_ok_and(|other| self.value == other.value);
        match op {
            CompareOp::Eq => equal,
            CompareOp::Ne => !equal,
            _ => false,
        }
    }
}

#[pyclass(frozen, name = "Check")]
pub struct PyCheck {
    value: CoreCheck,
}

static CHECKS: GILOnceCell<[Py<PyCheck>; 2]> = GILOnceCell::new();

fn checks(py: Python<'_>) -> &[Py<PyCheck>; 2] {
    CHECKS.get_or_init(py, || {
        [
            Py::new(
                py,
                PyCheck {
                    value: CoreCheck::FirstLine,
                },
            )
            .unwrap(),
            Py::new(
                py,
                PyCheck {
                    value: CoreCheck::AllLines,
                },
            )
            .unwrap(),
        ]
    })
}

#[pymethods]
#[allow(non_snake_case)]
impl PyCheck {
    #[classattr]
    fn FIRST_LINE(py: Python<'_>) -> Py<PyCheck> {
        checks(py)[0].clone_ref(py)
    }
    #[classattr]
    fn ALL_LINES(py: Python<'_>) -> Py<PyCheck> {
        checks(py)[1].clone_ref(py)
    }
    fn __repr__(&self) -> &'static str {
        match self.value {
            CoreCheck::FirstLine => "Check.FIRST_LINE",
            CoreCheck::AllLines => "Check.ALL_LINES",
        }
    }
}

const KIND_NAMES: [&str; 16] = [
    "TEXT",
    "CONCAT",
    "GROUP",
    "INDENT",
    "ALIGN",
    "LINE",
    "FILL",
    "IF_BREAK",
    "LINE_SUFFIX",
    "TRAILING_COMMENT",
    "BREAK_PARENT",
    "CONDITIONAL_GROUP",
    "VERBATIM",
    "COLUMN_TEXT",
    "SUFFIX_BREAK",
    "ON_RENDER",
];

#[pyclass(frozen, name = "DocKind")]
pub struct PyDocKind {
    index: usize,
}

static KINDS: GILOnceCell<Vec<Py<PyDocKind>>> = GILOnceCell::new();

fn kinds(py: Python<'_>) -> &[Py<PyDocKind>] {
    KINDS.get_or_init(py, || {
        (0..KIND_NAMES.len())
            .map(|index| Py::new(py, PyDocKind { index }).unwrap())
            .collect()
    })
}

#[pymethods]
#[allow(non_snake_case)]
impl PyDocKind {
    #[classattr]
    fn TEXT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[0].clone_ref(py)
    }
    #[classattr]
    fn CONCAT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[1].clone_ref(py)
    }
    #[classattr]
    fn GROUP(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[2].clone_ref(py)
    }
    #[classattr]
    fn INDENT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[3].clone_ref(py)
    }
    #[classattr]
    fn ALIGN(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[4].clone_ref(py)
    }
    #[classattr]
    fn LINE(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[5].clone_ref(py)
    }
    #[classattr]
    fn FILL(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[6].clone_ref(py)
    }
    #[classattr]
    fn IF_BREAK(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[7].clone_ref(py)
    }
    #[classattr]
    fn LINE_SUFFIX(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[8].clone_ref(py)
    }
    #[classattr]
    fn TRAILING_COMMENT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[9].clone_ref(py)
    }
    #[classattr]
    fn BREAK_PARENT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[10].clone_ref(py)
    }
    #[classattr]
    fn CONDITIONAL_GROUP(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[11].clone_ref(py)
    }
    #[classattr]
    fn VERBATIM(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[12].clone_ref(py)
    }
    #[classattr]
    fn COLUMN_TEXT(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[13].clone_ref(py)
    }
    #[classattr]
    fn SUFFIX_BREAK(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[14].clone_ref(py)
    }
    #[classattr]
    fn ON_RENDER(py: Python<'_>) -> Py<PyDocKind> {
        kinds(py)[15].clone_ref(py)
    }
    fn __repr__(&self) -> String {
        format!("DocKind.{}", KIND_NAMES[self.index])
    }
}

static CONSTANTS: LazyLock<[CoreDoc; 7]> = LazyLock::new(|| {
    [
        CoreDoc::text("").unwrap(),
        CoreDoc::line(LineKind::Line),
        CoreDoc::line(LineKind::Soft),
        CoreDoc::line(LineKind::Hard),
        CoreDoc::line(LineKind::Literal),
        CoreDoc::break_parent(),
        CoreDoc::suffix_break(),
    ]
});

static HANDLES: GILOnceCell<[Py<PyDoc>; 7]> = GILOnceCell::new();

fn handles(py: Python<'_>) -> &[Py<PyDoc>; 7] {
    HANDLES.get_or_init(py, || {
        std::array::from_fn(|index| {
            Py::new(
                py,
                PyDoc {
                    value: CONSTANTS[index].clone(),
                    callback: None,
                },
            )
            .unwrap()
        })
    })
}

fn wrap(py: Python<'_>, value: CoreDoc) -> PyResult<Py<PyDoc>> {
    for (index, constant) in CONSTANTS.iter().enumerate() {
        if Arc::ptr_eq(&value.0, &constant.0) {
            return Ok(handles(py)[index].clone_ref(py));
        }
    }
    Py::new(
        py,
        PyDoc {
            value,
            callback: None,
        },
    )
}

fn doclike(value: &Bound<'_, PyAny>) -> PyResult<CoreDoc> {
    if let Ok(doc) = value.extract::<PyRef<'_, PyDoc>>() {
        return Ok(doc.value.clone());
    }
    CoreDoc::text(value.extract::<&str>()?).map_err(PyValueError::new_err)
}

fn doclikes(values: &Bound<'_, PyAny>) -> PyResult<Vec<CoreDoc>> {
    values.try_iter()?.map(|value| doclike(&value?)).collect()
}

fn optional_id(id: Option<PyRef<'_, PyGroupId>>) -> Option<CoreGroupId> {
    id.map(|id| id.value.clone())
}

fn py_id(py: Python<'_>, id: &Option<CoreGroupId>) -> PyResult<Py<PyAny>> {
    id.as_ref().map_or_else(
        || Ok(py.None()),
        |id| Ok(Py::new(py, PyGroupId { value: id.clone() })?.into_any()),
    )
}

#[pymethods]
impl PyDoc {
    #[getter]
    fn forced(&self) -> bool {
        self.value.0.forced
    }

    #[getter]
    fn flat_width(&self) -> i32 {
        self.value.0.flat_width
    }

    #[getter]
    fn kind(&self, py: Python<'_>) -> Py<PyDocKind> {
        let index = match self.value.0.kind {
            Kind::Text { .. } => 0,
            Kind::Concat(_) => 1,
            Kind::Group { .. } => 2,
            Kind::Indent { .. } => 3,
            Kind::Align(_) => 4,
            Kind::Line(_) => 5,
            Kind::Fill { .. } => 6,
            Kind::IfBreak { .. } => 7,
            Kind::LineSuffix(_) => 8,
            Kind::TrailingComment(_) => 9,
            Kind::BreakParent => 10,
            Kind::ConditionalGroup { .. } => 11,
            Kind::Verbatim { .. } => 12,
            Kind::ColumnText(_) => 13,
            Kind::SuffixBreak => 14,
            Kind::OnRender(_) => 15,
        };
        kinds(py)[index].clone_ref(py)
    }

    #[getter]
    fn parts(&self, py: Python<'_>) -> PyResult<Py<PyTuple>> {
        match &self.value.0.kind {
            Kind::Concat(parts) | Kind::Fill { parts, .. } => Ok(PyTuple::new(
                py,
                parts
                    .iter()
                    .map(|part| wrap(py, part.clone()))
                    .collect::<PyResult<Vec<_>>>()?,
            )?
            .unbind()),
            _ => Err(PyTypeError::new_err(
                "parts is only available for concat and fill",
            )),
        }
    }

    fn unpack(&self, py: Python<'_>) -> PyResult<Py<PyTuple>> {
        let child =
            |doc: &CoreDoc| -> PyResult<Py<PyAny>> { Ok(wrap(py, doc.clone())?.into_any()) };
        let items: Vec<Py<PyAny>> = match &self.value.0.kind {
            Kind::Text { s, .. } | Kind::TrailingComment(s) => vec![s.as_ref().into_py_any(py)?],
            Kind::Concat(parts) => {
                vec![
                    PyTuple::new(py, parts.iter().map(child).collect::<PyResult<Vec<_>>>()?)?
                        .into_any()
                        .unbind(),
                ]
            }
            Kind::Group {
                contents,
                id,
                should_break,
            } => vec![
                child(contents)?,
                py_id(py, id)?,
                should_break.into_py_any(py)?,
            ],
            Kind::Indent { contents, n } => vec![child(contents)?, n.into_py_any(py)?],
            Kind::Align(contents) | Kind::LineSuffix(contents) => vec![child(contents)?],
            Kind::Line(kind) => vec![
                matches!(kind, LineKind::Hard | LineKind::Literal).into_py_any(py)?,
                (*kind == LineKind::Soft).into_py_any(py)?,
                (*kind == LineKind::Literal).into_py_any(py)?,
            ],
            Kind::Fill { parts, lazy } => vec![
                PyTuple::new(py, parts.iter().map(child).collect::<PyResult<Vec<_>>>()?)?
                    .into_any()
                    .unbind(),
                lazy.into_py_any(py)?,
            ],
            Kind::IfBreak {
                broken,
                flat,
                group_id,
            } => vec![child(broken)?, child(flat)?, py_id(py, group_id)?],
            Kind::ConditionalGroup { alts, check } => vec![
                PyTuple::new(py, alts.iter().map(child).collect::<PyResult<Vec<_>>>()?)?
                    .into_any()
                    .unbind(),
                checks(py)[if *check == CoreCheck::FirstLine { 0 } else { 1 }]
                    .clone_ref(py)
                    .into_any(),
            ],
            Kind::Verbatim { s, bol } => vec![s.as_ref().into_py_any(py)?, bol.into_py_any(py)?],
            Kind::ColumnText(_) | Kind::OnRender(_) => vec![self
                .callback
                .as_ref()
                .map_or_else(|| py.None(), |cb| cb.clone_ref(py))],
            Kind::BreakParent | Kind::SuffixBreak => vec![],
        };
        Ok(PyTuple::new(py, items)?.unbind())
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> bool {
        let equal = other
            .extract::<PyRef<'_, Self>>()
            .is_ok_and(|other| Arc::ptr_eq(&self.value.0, &other.value.0));
        match op {
            CompareOp::Eq => equal,
            CompareOp::Ne => !equal,
            _ => false,
        }
    }

    fn __hash__(&self) -> usize {
        Arc::as_ptr(&self.value.0) as usize
    }
}

#[pyfunction]
fn text(py: Python<'_>, s: &str) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::text(s).map_err(PyValueError::new_err)?)
}

#[pyfunction(signature = (*docs))]
fn concat(py: Python<'_>, docs: &Bound<'_, PyTuple>) -> PyResult<Py<PyDoc>> {
    if docs.len() == 1 {
        let only = docs.get_item(0)?;
        if let Ok(doc) = only.extract::<Py<PyDoc>>() {
            return Ok(doc);
        }
        return text(py, only.extract()?);
    }
    wrap(py, CoreDoc::concat(doclikes(docs.as_any())?))
}

#[pyfunction(signature = (doc, id=None, should_break=false))]
fn group(
    py: Python<'_>,
    doc: &Bound<'_, PyAny>,
    id: Option<PyRef<'_, PyGroupId>>,
    should_break: bool,
) -> PyResult<Py<PyDoc>> {
    wrap(
        py,
        CoreDoc::group(doclike(doc)?, optional_id(id), should_break),
    )
}

#[pyfunction]
fn indent(py: Python<'_>, doc: &Bound<'_, PyAny>, n: i32) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::indent(doclike(doc)?, n))
}

#[pyfunction]
fn align(py: Python<'_>, doc: &Bound<'_, PyAny>) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::align(doclike(doc)?))
}

#[pyfunction(signature = (parts, *, lazy=false))]
fn fill(py: Python<'_>, parts: &Bound<'_, PyAny>, lazy: bool) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::fill(doclikes(parts)?, lazy))
}

#[pyfunction(signature = (broken, flat=None, group_id=None))]
fn if_break(
    py: Python<'_>,
    broken: &Bound<'_, PyAny>,
    flat: Option<&Bound<'_, PyAny>>,
    group_id: Option<PyRef<'_, PyGroupId>>,
) -> PyResult<Py<PyDoc>> {
    let flat = flat.map_or_else(|| CoreDoc::text("").map_err(PyValueError::new_err), doclike)?;
    wrap(
        py,
        CoreDoc::if_break(doclike(broken)?, flat, optional_id(group_id)),
    )
}

#[pyfunction]
fn line_suffix(py: Python<'_>, doc: &Bound<'_, PyAny>) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::line_suffix(doclike(doc)?))
}

#[pyfunction]
fn trailing_comment(py: Python<'_>, comment: &str) -> PyResult<Py<PyDoc>> {
    wrap(
        py,
        CoreDoc::trailing_comment(comment).map_err(PyValueError::new_err)?,
    )
}

#[pyfunction(signature = (alts, check=None))]
fn conditional_group(
    py: Python<'_>,
    alts: &Bound<'_, PyAny>,
    check: Option<PyRef<'_, PyCheck>>,
) -> PyResult<Py<PyDoc>> {
    wrap(
        py,
        CoreDoc::conditional_group(
            doclikes(alts)?,
            check.map_or(CoreCheck::FirstLine, |check| check.value),
        )
        .map_err(PyValueError::new_err)?,
    )
}

#[pyfunction(signature = (s, bol=false))]
fn verbatim(py: Python<'_>, s: &str, bol: bool) -> PyResult<Py<PyDoc>> {
    wrap(py, CoreDoc::verbatim(s, bol))
}

#[pyfunction]
fn column_text(py: Python<'_>, make: Py<PyAny>) -> PyResult<Py<PyDoc>> {
    if !make.bind(py).is_callable() {
        return Err(PyTypeError::new_err("make must be callable"));
    }
    let cb = make.clone_ref(py);
    Py::new(
        py,
        PyDoc {
            value: CoreDoc::column_text(Arc::new(move |col| {
                Python::with_gil(|py| cb.call1(py, (col,))?.extract(py)).map_err(HostError::new)
            })),
            callback: Some(make),
        },
    )
}

#[pyfunction]
fn on_render(py: Python<'_>, fn_: Py<PyAny>) -> PyResult<Py<PyDoc>> {
    if !fn_.bind(py).is_callable() {
        return Err(PyTypeError::new_err("fn must be callable"));
    }
    let cb = fn_.clone_ref(py);
    Py::new(
        py,
        PyDoc {
            value: CoreDoc::on_render(Arc::new(move || {
                Python::with_gil(|py| cb.call0(py).map(|_| ())).map_err(HostError::new)
            })),
            callback: Some(fn_),
        },
    )
}

#[pyfunction]
fn flatten(py: Python<'_>, doc: &Bound<'_, PyAny>) -> PyResult<Option<Py<PyDoc>>> {
    doclike(doc)?
        .flatten()
        .map(|flat| wrap(py, flat))
        .transpose()
}

#[pyfunction]
fn dump(doc: &Bound<'_, PyAny>) -> PyResult<String> {
    doclike(doc)?
        .dump()
        .map_err(|error| match error.0.downcast::<PyErr>() {
            Ok(error) => *error,
            Err(error) => PyRuntimeError::new_err(error.to_string()),
        })
}

pub fn register(module: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = module.py();
    module.add_class::<PyDoc>()?;
    module.add_class::<PyGroupId>()?;
    module.add_class::<PyDocKind>()?;
    module.add_class::<PyCheck>()?;
    module.add("FIRST_LINE", checks(py)[0].clone_ref(py))?;
    module.add("ALL_LINES", checks(py)[1].clone_ref(py))?;
    for (name, value) in [
        "EMPTY",
        "line",
        "softline",
        "hardline",
        "literalline",
        "break_parent",
        "suffix_break",
    ]
    .into_iter()
    .zip(handles(py))
    {
        module.add(name, value.clone_ref(py))?;
    }
    module.add_function(wrap_pyfunction!(text, module)?)?;
    module.add_function(wrap_pyfunction!(concat, module)?)?;
    module.add_function(wrap_pyfunction!(group, module)?)?;
    module.add_function(wrap_pyfunction!(indent, module)?)?;
    module.add_function(wrap_pyfunction!(align, module)?)?;
    module.add_function(wrap_pyfunction!(fill, module)?)?;
    module.add_function(wrap_pyfunction!(if_break, module)?)?;
    module.add_function(wrap_pyfunction!(line_suffix, module)?)?;
    module.add_function(wrap_pyfunction!(trailing_comment, module)?)?;
    module.add_function(wrap_pyfunction!(conditional_group, module)?)?;
    module.add_function(wrap_pyfunction!(verbatim, module)?)?;
    module.add_function(wrap_pyfunction!(column_text, module)?)?;
    module.add_function(wrap_pyfunction!(on_render, module)?)?;
    module.add_function(wrap_pyfunction!(flatten, module)?)?;
    module.add_function(wrap_pyfunction!(dump, module)?)?;
    Ok(())
}
