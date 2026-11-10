mod extract;

use std::collections::HashMap;
use std::hash::{Hash, Hasher};

use chplfmt_core::index::{NodeId, TokenIndex as CoreIndex};
use chplfmt_core::lexer::scan::{self, LexErrorKind};
use chplfmt_core::lexer::token::{Token as CoreToken, TokenKind as CoreKind, NO_MATCH};
use pyo3::class::basic::CompareOp;
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError, PyZeroDivisionError};
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::{PyDict, PyString, PyTuple};

create_exception!(chplfmt._native, NativeLexError, PyException);

const KIND_NAMES: [&str; 8] = [
    "IDENT",
    "NUMBER",
    "STRING",
    "LINE_COMMENT",
    "BLOCK_COMMENT",
    "PUNCT",
    "OPAQUE",
    "EOF",
];

#[pyclass(frozen, name = "TokenKind")]
struct PyTokenKind {
    value: CoreKind,
}

static KINDS: GILOnceCell<[Py<PyTokenKind>; 8]> = GILOnceCell::new();

fn kinds(py: Python<'_>) -> &[Py<PyTokenKind>; 8] {
    KINDS.get_or_init(py, || {
        std::array::from_fn(|index| {
            let value = match index {
                0 => CoreKind::Ident,
                1 => CoreKind::Number,
                2 => CoreKind::String,
                3 => CoreKind::LineComment,
                4 => CoreKind::BlockComment,
                5 => CoreKind::Punct,
                6 => CoreKind::Opaque,
                _ => CoreKind::Eof,
            };
            Py::new(py, PyTokenKind { value }).unwrap()
        })
    })
}

#[pymethods]
#[allow(non_snake_case)]
impl PyTokenKind {
    #[classattr]
    fn IDENT(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[0].clone_ref(py)
    }
    #[classattr]
    fn NUMBER(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[1].clone_ref(py)
    }
    #[classattr]
    fn STRING(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[2].clone_ref(py)
    }
    #[classattr]
    fn LINE_COMMENT(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[3].clone_ref(py)
    }
    #[classattr]
    fn BLOCK_COMMENT(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[4].clone_ref(py)
    }
    #[classattr]
    fn PUNCT(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[5].clone_ref(py)
    }
    #[classattr]
    fn OPAQUE(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[6].clone_ref(py)
    }
    #[classattr]
    fn EOF(py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[7].clone_ref(py)
    }

    fn __str__(&self) -> &'static str {
        KIND_NAMES[self.value as usize]
    }
    fn __format__(&self, spec: &str) -> PyResult<String> {
        if spec.is_empty() {
            Ok(self.__str__().to_owned())
        } else {
            Err(PyValueError::new_err(
                "unsupported format string for TokenKind",
            ))
        }
    }
    fn __repr__(&self) -> String {
        format!("<TokenKind.{}: '{}'>", self.__str__(), self.__str__())
    }
    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<bool> {
        let equal = if let Ok(other) = other.extract::<PyRef<'_, PyTokenKind>>() {
            self.value == other.value
        } else if let Ok(other) = other.extract::<&str>() {
            self.__str__() == other
        } else {
            false
        };
        Ok(match op {
            CompareOp::Eq => equal,
            CompareOp::Ne => !equal,
            _ => false,
        })
    }
    fn __hash__(&self, py: Python<'_>) -> PyResult<isize> {
        PyString::new(py, self.__str__()).hash()
    }
}

#[pyclass(frozen, name = "Token")]
struct PyToken {
    value: CoreToken,
    text: Py<PyString>,
}

#[pymethods]
impl PyToken {
    #[getter]
    fn kind(&self, py: Python<'_>) -> Py<PyTokenKind> {
        kinds(py)[self.value.kind as usize].clone_ref(py)
    }
    #[getter]
    fn text(&self, py: Python<'_>) -> Py<PyString> {
        self.text.clone_ref(py)
    }
    #[getter]
    fn start_offset(&self) -> u32 {
        self.value.start_cp
    }
    #[getter]
    fn end_offset(&self) -> u32 {
        self.value.end_cp
    }
    #[getter]
    fn start(&self) -> (u32, u32) {
        (self.value.start.line, self.value.start.col)
    }
    #[getter]
    fn end(&self) -> (u32, u32) {
        (self.value.end.line, self.value.end.col)
    }
    #[getter]
    fn nl_before(&self) -> u32 {
        self.value.nl_before
    }
    #[getter]
    fn ws_before(&self) -> bool {
        self.value.ws_before
    }
    #[getter]
    fn r#match(&self) -> Option<u32> {
        (self.value.partner != NO_MATCH).then_some(self.value.partner)
    }
    #[getter]
    fn is_comment(&self) -> bool {
        matches!(
            self.value.kind,
            CoreKind::LineComment | CoreKind::BlockComment
        )
    }
    fn __richcmp__(
        &self,
        other: &Bound<'_, PyAny>,
        op: CompareOp,
        py: Python<'_>,
    ) -> PyResult<bool> {
        let equal = if let Ok(other) = other.extract::<PyRef<'_, PyToken>>() {
            self.value == other.value
                && self.text.bind(py).to_str()? == other.text.bind(py).to_str()?
        } else {
            false
        };
        Ok(match op {
            CompareOp::Eq => equal,
            CompareOp::Ne => !equal,
            _ => false,
        })
    }
    fn __hash__(&self, py: Python<'_>) -> PyResult<u64> {
        let mut hasher = std::collections::hash_map::DefaultHasher::new();
        (self.value.kind as u8).hash(&mut hasher);
        self.text.bind(py).to_str()?.hash(&mut hasher);
        self.value.start_cp.hash(&mut hasher);
        self.value.end_cp.hash(&mut hasher);
        self.value.start.hash(&mut hasher);
        self.value.end.hash(&mut hasher);
        self.value.nl_before.hash(&mut hasher);
        self.value.ws_before.hash(&mut hasher);
        self.value.partner.hash(&mut hasher);
        Ok(hasher.finish())
    }
}

#[pyfunction]
fn lex(py: Python<'_>, text: &str, opaque: Vec<(usize, usize)>) -> PyResult<Vec<Py<PyToken>>> {
    let tokens = scan::lex(text, &opaque)
        .map_err(|error| {
            if error.reason == LexErrorKind::TooLarge {
                return Ok(PyValueError::new_err("source is at least 4 GiB"));
            }
            let (reason, ch) = match error.reason {
                LexErrorKind::TooLarge => unreachable!(),
                LexErrorKind::UnterminatedString => ("unterminated string literal", None),
                LexErrorKind::UnterminatedBlockComment => ("unterminated block comment", None),
                LexErrorKind::InvalidCharacter(ch) => ("invalid character", Some(ch.to_string())),
                LexErrorKind::OpaqueWhitespace => ("opaque range starts inside whitespace", None),
                LexErrorKind::OpaqueToken => ("opaque range starts inside a token", None),
                LexErrorKind::OpaqueOutside => ("opaque range outside the text", None),
                LexErrorKind::Unmatched(ch) => ("unmatched", Some(ch.to_string())),
            };
            let err = NativeLexError::new_err(reason);
            err.value(py).setattr("offset", error.offset_cp)?;
            err.value(py).setattr("reason", reason)?;
            err.value(py).setattr("char", ch)?;
            Ok::<PyErr, PyErr>(err)
        })
        .map_err(|result| result.unwrap())?;
    let mut interned: HashMap<&str, Py<PyString>> = HashMap::new();
    tokens
        .toks
        .iter()
        .enumerate()
        .map(|(index, token)| {
            let value = tokens.text(index);
            let text = if value.len() <= 16 {
                interned
                    .entry(value)
                    .or_insert_with(|| PyString::new(py, value).unbind())
                    .clone_ref(py)
            } else {
                PyString::new(py, value).unbind()
            };
            Py::new(
                py,
                PyToken {
                    value: *token,
                    text,
                },
            )
        })
        .collect()
}

#[pyclass(name = "NativeIndex")]
struct NativeIndex {
    value: CoreIndex,
    nodes: Vec<Py<PyAny>>,
    id_of: Py<PyDict>,
    tokens: Vec<Py<PyToken>>,
}

impl NativeIndex {
    fn node_id(&self, node: &Bound<'_, PyAny>) -> PyResult<Option<NodeId>> {
        self.id_of
            .bind(node.py())
            .get_item(node)?
            .map(|value| value.extract())
            .transpose()
    }

    fn node(&self, py: Python<'_>, id: NodeId) -> Option<Py<PyAny>> {
        self.nodes.get(id as usize).map(|node| node.clone_ref(py))
    }
}

#[pymethods]
impl NativeIndex {
    #[getter]
    fn tokens(&self, py: Python<'_>) -> Vec<Py<PyToken>> {
        self.tokens
            .iter()
            .map(|token| token.clone_ref(py))
            .collect()
    }

    #[getter]
    fn problems(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        self.value
            .problems
            .iter()
            .map(|&(kid, prev)| {
                let kid = self.nodes[kid as usize].bind(py);
                let prev = self.nodes[prev as usize].bind(py);
                Ok(format!(
                    "{} at {} overlaps {} at {}",
                    kid.call_method0("tag")?.str()?,
                    kid.call_method0("location")?.call_method0("start")?.str()?,
                    prev.call_method0("tag")?.str()?,
                    prev.call_method0("location")?
                        .call_method0("start")?
                        .str()?,
                ))
            })
            .collect()
    }

    fn nodes(&self, py: Python<'_>) -> Vec<Py<PyAny>> {
        self.id_of
            .bind(py)
            .keys()
            .iter()
            .map(|node| node.unbind())
            .collect()
    }

    fn find_start(&self, position: &Bound<'_, PyAny>) -> PyResult<Option<u32>> {
        Ok(self.value.find_start(extract::position(position)?))
    }

    fn find_end(&self, position: &Bound<'_, PyAny>) -> PyResult<Option<u32>> {
        Ok(self.value.find_end(extract::position(position)?))
    }

    fn span(&self, location: &Bound<'_, PyAny>) -> PyResult<Option<(u32, u32)>> {
        let (start, end) = if let Ok(pair) = location.downcast::<PyTuple>() {
            (
                extract::position(&pair.get_item(0)?)?,
                extract::position(&pair.get_item(1)?)?,
            )
        } else {
            extract::location(location)?
        };
        Ok(self.value.span(start, end))
    }

    fn node_span(&self, node: &Bound<'_, PyAny>) -> PyResult<Option<(u32, u32)>> {
        Ok(self.node_id(node)?.and_then(|id| self.value.node_span(id)))
    }

    fn owner(&self, py: Python<'_>, token: u32) -> Option<Py<PyAny>> {
        self.node(py, self.value.owner(token))
    }

    fn parent(&self, py: Python<'_>, node: &Bound<'_, PyAny>) -> PyResult<Option<Py<PyAny>>> {
        Ok(self
            .node_id(node)?
            .and_then(|id| self.node(py, self.value.facts.parent[id as usize])))
    }

    fn children(&self, py: Python<'_>, node: &Bound<'_, PyAny>) -> PyResult<Vec<Py<PyAny>>> {
        Ok(self.node_id(node)?.map_or_else(Vec::new, |id| {
            self.value
                .children(id)
                .iter()
                .filter_map(|&kid| self.node(py, kid))
                .collect()
        }))
    }

    fn own_tokens(&self, node: &Bound<'_, PyAny>) -> PyResult<Vec<u32>> {
        Ok(self
            .node_id(node)?
            .map_or_else(Vec::new, |id| self.value.own_tokens(id).to_vec()))
    }
}

#[pyfunction]
fn build_index(
    py: Python<'_>,
    source: &Bound<'_, PyAny>,
    roots: &Bound<'_, PyAny>,
    classify: &Bound<'_, PyAny>,
    comment: &Bound<'_, PyAny>,
    extern_block: &Bound<'_, PyAny>,
) -> PyResult<NativeIndex> {
    let extracted = extract::walk(py, source, roots, classify, comment, extern_block)?;
    let text: String = source.getattr("text")?.extract()?;
    let tokens = lex(py, &text, extracted.opaque)?;
    let core_tokens = tokens.iter().map(|token| token.borrow(py).value).collect();
    Ok(NativeIndex {
        value: CoreIndex::new(&text, core_tokens, extracted.facts),
        nodes: extracted.nodes,
        id_of: extracted.id_of,
        tokens,
    })
}

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
    module.add_class::<PyTokenKind>()?;
    module.add_class::<PyToken>()?;
    module.add_class::<NativeIndex>()?;
    module.add("NativeLexError", module.py().get_type::<NativeLexError>())?;
    module.add_function(wrap_pyfunction!(lex, module)?)?;
    module.add_function(wrap_pyfunction!(build_index, module)?)?;
    module.add_function(wrap_pyfunction!(char_width, module)?)?;
    module.add_function(wrap_pyfunction!(display_width, module)?)?;
    Ok(())
}
