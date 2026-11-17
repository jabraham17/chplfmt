use std::collections::HashMap;

use chplfmt_core::index::{AstFacts, BaseRule, BracketRule, Extra, NodeClass, NodeId, NO_NODE};
use chplfmt_core::lexer::token::Pos;
use pyo3::prelude::*;
use pyo3::types::PyDict;

pub struct Extracted {
    pub facts: AstFacts,
    pub nodes: Vec<Py<PyAny>>,
    pub id_of: Py<PyDict>,
    pub opaque: Vec<(usize, usize)>,
}

fn pos(value: &Bound<'_, PyAny>) -> PyResult<Pos> {
    let (line, col): (i64, i64) = value.extract()?;
    Ok(Pos {
        line: line.max(0) as u32,
        col: col.max(0) as u32,
    })
}

pub fn location(value: &Bound<'_, PyAny>) -> PyResult<(Pos, Pos)> {
    Ok((
        pos(&value.call_method0("start")?)?,
        pos(&value.call_method0("end")?)?,
    ))
}

fn rule(value: u8) -> PyResult<BaseRule> {
    match value {
        0 => Ok(BaseRule::Leaf),
        1 => Ok(BaseRule::Block),
        2 => Ok(BaseRule::AttrGroup),
        3 => Ok(BaseRule::ArrayRow),
        4 => Ok(BaseRule::Module),
        5 => Ok(BaseRule::Formal),
        6 => Ok(BaseRule::Signature),
        7 => Ok(BaseRule::Attribute),
        8 => Ok(BaseRule::New),
        9 => Ok(BaseRule::Other),
        _ => Err(pyo3::exceptions::PyValueError::new_err(
            "invalid AST base rule",
        )),
    }
}

fn bracket_rule(value: u8) -> PyResult<BracketRule> {
    match value {
        0 => Ok(BracketRule::None),
        1 => Ok(BracketRule::FnCall),
        2 => Ok(BracketRule::FirstParen),
        3 => Ok(BracketRule::OpCall),
        4 => Ok(BracketRule::Catch),
        5 => Ok(BracketRule::Square),
        6 => Ok(BracketRule::Domain),
        7 => Ok(BracketRule::Visibility),
        8 => Ok(BracketRule::Function),
        9 => Ok(BracketRule::Interface),
        _ => Err(pyo3::exceptions::PyValueError::new_err(
            "invalid bracket rule",
        )),
    }
}

fn optional_location(node: &Bound<'_, PyAny>, method: &str) -> PyResult<Option<(Pos, Pos)>> {
    let value = node.call_method0(method)?;
    (!value.is_none()).then(|| location(&value)).transpose()
}

pub fn walk(
    py: Python<'_>,
    source: &Bound<'_, PyAny>,
    roots: &Bound<'_, PyAny>,
    classify: &Bound<'_, PyAny>,
    comment: &Bound<'_, PyAny>,
    extern_block: &Bound<'_, PyAny>,
) -> PyResult<Extracted> {
    let mut facts = AstFacts::default();
    let mut nodes = Vec::new();
    let id_of = PyDict::new(py);
    let mut opaque = Vec::new();
    let mut classes: HashMap<usize, NodeClass> = HashMap::new();
    let mut stack: Vec<(Py<PyAny>, NodeId)> = roots
        .try_iter()?
        .map(|node| node.map(|node| (node.unbind(), NO_NODE)))
        .collect::<PyResult<_>>()?;
    stack.reverse();
    while let Some((owned, parent)) = stack.pop() {
        let node = owned.bind(py);
        let id = nodes.len() as NodeId;
        let ty = node.get_type();
        let class = if let Some(&class) = classes.get(&(ty.as_ptr() as usize)) {
            class
        } else {
            let (base, body_owner, brackets, expression_kind, flags): (u8, bool, u8, bool, u16) =
                classify.call1((ty.clone(),))?.extract()?;
            let class = NodeClass {
                base: rule(base)?,
                body_owner,
                brackets: bracket_rule(brackets)?,
                expression_kind,
                flags,
            };
            classes.insert(ty.as_ptr() as usize, class);
            class
        };
        let loc = node.call_method0("location")?;
        let positions = location(&loc)?;
        let kids: Vec<Py<PyAny>> = node
            .try_iter()?
            .filter_map(|result| match result {
                Ok(child) => match child.is_instance(comment) {
                    Ok(true) => None,
                    Ok(false) => Some(Ok(child.unbind())),
                    Err(error) => Some(Err(error)),
                },
                Err(error) => Some(Err(error)),
            })
            .collect::<PyResult<_>>()?;
        let curly = if class.flags & (1 << 6) != 0 {
            optional_location(node, "curly_braces_location")?
        } else {
            None
        };
        let extra = Extra {
            implicit_module: class.base == BaseRule::Module
                && node.call_method0("kind")?.eq("implicit")?,
            implicit_formal: if class.base == BaseRule::Formal && kids.is_empty() {
                node.call_method0("is_this")?.is_truthy()?
                    || location(&node.call_method0("name_location")?)?.0.line == 0
            } else {
                false
            },
            name: if class.brackets == BracketRule::Function {
                optional_location(node, "name_location")?
            } else {
                None
            },
            tuple_expansion: class.brackets == BracketRule::OpCall
                && node.call_method0("op")?.eq("...")?,
            catch_parens: class.brackets == BracketRule::Catch
                && node.call_method0("has_parens_around_error")?.is_truthy()?,
            domain_curly: class.brackets == BracketRule::Domain
                && node.call_method0("used_curly_braces")?.is_truthy()?,
            formal_list: class.brackets == BracketRule::Interface
                && node.call_method0("is_formal_list_explicit")?.is_truthy()?,
            parenless: class.brackets == BracketRule::Function
                && node.call_method0("is_parenless")?.is_truthy()?,
            expression_level: class.expression_kind
                && node.call_method0("is_expression_level")?.is_truthy()?,
            ..Extra::default()
        };
        if node.is_instance(extern_block)? {
            let start = loc.call_method0("start")?;
            let end = loc.call_method0("end")?;
            opaque.push((
                source.call_method1("offset", (start,))?.extract()?,
                source.call_method1("offset", (end,))?.extract()?,
            ));
        }
        id_of.set_item(node, id)?;
        nodes.push(owned);
        facts.class.push(class);
        facts.parent.push(parent);
        facts.loc.push(positions);
        if let Some(curly) = curly {
            facts.curly.insert(id, curly);
        }
        if extra != Extra::default() {
            facts.extra.insert(id, extra);
        }
        let begin = facts.kids.len() as u32;
        facts.kids.resize(facts.kids.len() + kids.len(), NO_NODE);
        facts.kid_range.push((begin, facts.kids.len() as u32));
        for child in kids.into_iter().rev() {
            stack.push((child, id));
        }
    }
    let mut next_slot: Vec<u32> = facts.kid_range.iter().map(|range| range.0).collect();
    for (id, &parent) in facts.parent.iter().enumerate() {
        if parent == NO_NODE {
            continue;
        }
        facts.kids[next_slot[parent as usize] as usize] = id as NodeId;
        next_slot[parent as usize] += 1;
    }
    for (id, node) in nodes.iter().enumerate() {
        let node = node.bind(py);
        if facts.class[id].brackets == BracketRule::FnCall {
            let called = node.call_method0("called_expression")?;
            facts.extra.entry(id as NodeId).or_default().called = id_of
                .get_item(called)?
                .map(|value| value.extract())
                .transpose()?;
        }
        if facts.parent[id] != NO_NODE
            && facts.class[facts.parent[id] as usize].brackets == BracketRule::FnCall
        {
            if let Some(paren) = optional_location(node, "paren_location")? {
                facts.extra.entry(id as NodeId).or_default().paren = Some(paren);
            }
        }
    }
    opaque.sort_unstable();
    Ok(Extracted {
        facts,
        nodes,
        id_of: id_of.unbind(),
        opaque,
    })
}

pub fn position(value: &Bound<'_, PyAny>) -> PyResult<Pos> {
    pos(value)
}
