use std::fmt;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::{Arc, LazyLock};

use crate::width;

#[derive(Clone)]
pub struct Doc(pub Arc<Node>);

pub struct Node {
    pub kind: Kind,
    pub forced: bool,
    pub flat_width: i32,
}

pub struct HostError(pub Box<dyn std::error::Error + Send + Sync>);

impl HostError {
    pub fn new(error: impl std::error::Error + Send + Sync + 'static) -> Self {
        Self(Box::new(error))
    }
}

impl fmt::Display for HostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl fmt::Debug for HostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Debug::fmt(&self.0, formatter)
    }
}

pub type ColumnFn = Arc<dyn Fn(u32) -> Result<String, HostError> + Send + Sync>;
pub type RenderFn = Arc<dyn Fn() -> Result<(), HostError> + Send + Sync>;

pub enum Kind {
    Text {
        s: Box<str>,
        width: i32,
    },
    Concat(Box<[Doc]>),
    Group {
        contents: Doc,
        id: Option<GroupId>,
        should_break: bool,
    },
    Indent {
        contents: Doc,
        n: i32,
    },
    Align(Doc),
    Line(LineKind),
    Fill {
        parts: Box<[Doc]>,
        lazy: bool,
    },
    IfBreak {
        broken: Doc,
        flat: Doc,
        group_id: Option<GroupId>,
    },
    LineSuffix(Doc),
    TrailingComment(Box<str>),
    BreakParent,
    ConditionalGroup {
        alts: Box<[Doc]>,
        check: Check,
    },
    Verbatim {
        s: Box<str>,
        bol: bool,
    },
    ColumnText(ColumnFn),
    SuffixBreak,
    OnRender(RenderFn),
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum LineKind {
    Line,
    Soft,
    Hard,
    Literal,
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Check {
    FirstLine,
    AllLines,
}

static NEXT_GROUP_ID: AtomicU32 = AtomicU32::new(1);

#[derive(Clone, Debug)]
pub struct GroupId {
    pub id: u32,
    pub name: Arc<str>,
}

impl GroupId {
    pub fn new(name: &str) -> Self {
        Self {
            id: NEXT_GROUP_ID.fetch_add(1, Ordering::Relaxed),
            name: Arc::from(name),
        }
    }
}

impl PartialEq for GroupId {
    fn eq(&self, other: &Self) -> bool {
        self.id == other.id
    }
}

impl Eq for GroupId {}

impl std::hash::Hash for GroupId {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.id.hash(state);
    }
}

fn children(kind: Kind, stack: &mut Vec<Doc>) {
    match kind {
        Kind::Concat(parts)
        | Kind::Fill { parts, .. }
        | Kind::ConditionalGroup { alts: parts, .. } => stack.extend(parts),
        Kind::Group { contents, .. }
        | Kind::Indent { contents, .. }
        | Kind::Align(contents)
        | Kind::LineSuffix(contents) => stack.push(contents),
        Kind::IfBreak { broken, flat, .. } => {
            stack.push(broken);
            stack.push(flat);
        }
        _ => {}
    }
}

impl Drop for Node {
    fn drop(&mut self) {
        let mut stack = Vec::new();
        children(
            std::mem::replace(&mut self.kind, Kind::SuffixBreak),
            &mut stack,
        );
        while let Some(doc) = stack.pop() {
            if let Some(mut node) = Arc::into_inner(doc.0) {
                children(
                    std::mem::replace(&mut node.kind, Kind::SuffixBreak),
                    &mut stack,
                );
            }
        }
    }
}

fn sum_width(parts: &[Doc]) -> i32 {
    parts
        .iter()
        .try_fold(0i32, |total, part| {
            (part.0.flat_width >= 0)
                .then(|| total.checked_add(part.0.flat_width))
                .flatten()
        })
        .unwrap_or(-1)
}

static EMPTY: LazyLock<Doc> = LazyLock::new(|| {
    Doc::new(
        Kind::Text {
            s: "".into(),
            width: 0,
        },
        false,
        0,
    )
});

// A fixed-size cache, not an interner that grows with successive input files.
static ASCII_TEXT: LazyLock<[Doc; 95]> = LazyLock::new(|| {
    std::array::from_fn(|index| {
        Doc::new(
            Kind::Text {
                s: char::from(index as u8 + b' ').to_string().into(),
                width: 1,
            },
            false,
            1,
        )
    })
});

impl Doc {
    fn new(kind: Kind, forced: bool, flat_width: i32) -> Self {
        Self(Arc::new(Node {
            kind,
            forced,
            flat_width: if forced { -1 } else { flat_width },
        }))
    }

    pub fn text(s: &str) -> Result<Self, String> {
        if s.is_empty() {
            return Ok(EMPTY.clone());
        }
        if s.len() == 1 && (b' '..=b'~').contains(&s.as_bytes()[0]) {
            return Ok(ASCII_TEXT[(s.as_bytes()[0] - b' ') as usize].clone());
        }
        if s.contains('\n') {
            return Err(format!("text() must not contain a newline: {}", repr(s)));
        }
        let width = if s.contains('\t') {
            -1
        } else {
            i32::try_from(width::display_width(s, 0, 2).unwrap()).unwrap_or(-1)
        };
        Ok(Self::new(Kind::Text { s: s.into(), width }, false, width))
    }

    pub fn concat(mut parts: Vec<Doc>) -> Self {
        parts.retain(|part| !matches!(&part.0.kind, Kind::Text { s, .. } if s.is_empty()));
        if parts.is_empty() {
            return EMPTY.clone();
        }
        if parts.len() == 1 {
            return parts.pop().unwrap();
        }
        let forced = parts.iter().any(|part| part.0.forced);
        let flat_width = sum_width(&parts);
        Self::new(Kind::Concat(parts.into()), forced, flat_width)
    }

    pub fn group(contents: Doc, id: Option<GroupId>, should_break: bool) -> Self {
        let forced = should_break || contents.0.forced;
        let width = contents.0.flat_width;
        Self::new(
            Kind::Group {
                contents,
                id,
                should_break,
            },
            forced,
            width,
        )
    }

    pub fn indent(contents: Doc, n: i32) -> Self {
        let forced = contents.0.forced;
        let width = contents.0.flat_width;
        Self::new(Kind::Indent { contents, n }, forced, width)
    }

    pub fn align(contents: Doc) -> Self {
        let forced = contents.0.forced;
        let width = contents.0.flat_width;
        Self::new(Kind::Align(contents), forced, width)
    }

    pub fn line(kind: LineKind) -> Self {
        let width = match kind {
            LineKind::Line => 1,
            LineKind::Soft => 0,
            LineKind::Hard | LineKind::Literal => -1,
        };
        Self::new(Kind::Line(kind), width == -1, width)
    }

    pub fn fill(parts: Vec<Doc>, lazy: bool) -> Self {
        let forced = parts.iter().any(|part| part.0.forced);
        let flat_width = sum_width(&parts);
        Self::new(
            Kind::Fill {
                parts: parts.into(),
                lazy,
            },
            forced,
            flat_width,
        )
    }

    pub fn if_break(broken: Doc, flat: Doc, group_id: Option<GroupId>) -> Self {
        let forced = flat.0.forced;
        let width = if group_id.is_some() {
            -1
        } else {
            flat.0.flat_width
        };
        Self::new(
            Kind::IfBreak {
                broken,
                flat,
                group_id,
            },
            forced,
            width,
        )
    }

    pub fn line_suffix(contents: Doc) -> Self {
        Self::new(Kind::LineSuffix(contents), false, 0)
    }

    pub fn trailing_comment(text: &str) -> Result<Self, String> {
        if text.contains('\n') {
            return Err(format!(
                "trailing comment must not contain a newline: {}",
                repr(text)
            ));
        }
        Ok(Self::line_suffix(Self::new(
            Kind::TrailingComment(text.into()),
            false,
            0,
        )))
    }

    pub fn break_parent() -> Self {
        Self::new(Kind::BreakParent, true, -1)
    }

    pub fn conditional_group(alts: Vec<Doc>, check: Check) -> Result<Self, &'static str> {
        let Some(first) = alts.first() else {
            return Err("conditional_group needs at least one alternative");
        };
        let forced = alts.iter().all(|alt| alt.0.forced);
        let width = first.0.flat_width;
        Ok(Self::new(
            Kind::ConditionalGroup {
                alts: alts.into(),
                check,
            },
            forced,
            width,
        ))
    }

    pub fn verbatim(s: &str, bol: bool) -> Self {
        Self::new(Kind::Verbatim { s: s.into(), bol }, false, -1)
    }

    pub fn column_text(make: ColumnFn) -> Self {
        Self::new(Kind::ColumnText(make), true, -1)
    }

    pub fn suffix_break() -> Self {
        Self::new(Kind::SuffixBreak, false, 0)
    }

    pub fn on_render(fn_: RenderFn) -> Self {
        Self::new(Kind::OnRender(fn_), false, 0)
    }

    pub fn flatten(&self) -> Option<Self> {
        if self.0.forced {
            None
        } else {
            Some(self.flat())
        }
    }

    fn flat(&self) -> Self {
        match &self.0.kind {
            Kind::Group { contents, id, .. } => {
                let flat = contents.flat();
                match id {
                    Some(_) if Arc::ptr_eq(&flat.0, &contents.0) => self.clone(),
                    Some(id) => Self::group(flat, Some(id.clone()), false),
                    None => flat,
                }
            }
            Kind::ConditionalGroup { alts, .. } => alts[0].flat(),
            Kind::IfBreak { flat, .. } => flat.flat(),
            Kind::Line(LineKind::Soft) => Self::text("").unwrap(),
            Kind::Line(_) => Self::text(" ").unwrap(),
            Kind::Concat(parts) => {
                let flattened: Vec<_> = parts.iter().map(Self::flat).collect();
                if parts
                    .iter()
                    .zip(&flattened)
                    .all(|(a, b)| Arc::ptr_eq(&a.0, &b.0))
                {
                    self.clone()
                } else {
                    Self::concat(flattened)
                }
            }
            Kind::Fill { parts, .. } => Self::concat(parts.iter().map(Self::flat).collect()),
            Kind::Indent { contents, .. } | Kind::Align(contents) => contents.flat(),
            _ => self.clone(),
        }
    }

    pub fn dump(&self) -> Result<String, HostError> {
        let mut out = Vec::new();
        self.dump_into(0, &mut out)?;
        Ok(out.join("\n"))
    }

    fn dump_into(&self, depth: usize, out: &mut Vec<String>) -> Result<(), HostError> {
        let pad = "  ".repeat(depth);
        match &self.0.kind {
            Kind::Text { s, .. } => out.push(format!("{pad}text {}", repr(s))),
            Kind::Verbatim { s, bol } => out.push(format!(
                "{pad}verbatim{} {}",
                if *bol { " bol" } else { "" },
                repr(s)
            )),
            Kind::ColumnText(make) => out.push(format!("{pad}column_text {}", repr(&make(0)?))),
            Kind::SuffixBreak => out.push(format!("{pad}suffix_break")),
            Kind::OnRender(_) => out.push(format!("{pad}on_render")),
            Kind::TrailingComment(s) => out.push(format!("{pad}trailing_comment {}", repr(s))),
            Kind::BreakParent => out.push(format!("{pad}break_parent")),
            Kind::Line(kind) => out.push(format!(
                "{pad}{}",
                match kind {
                    LineKind::Line => "line",
                    LineKind::Soft => "softline",
                    LineKind::Hard => "hardline",
                    LineKind::Literal => "literalline",
                }
            )),
            Kind::Concat(parts) | Kind::Fill { parts, .. } => {
                out.push(format!(
                    "{pad}{}",
                    if matches!(self.0.kind, Kind::Concat(_)) {
                        "concat"
                    } else {
                        "fill"
                    }
                ));
                for part in parts {
                    part.dump_into(depth + 1, out)?;
                }
            }
            Kind::Group {
                contents,
                id,
                should_break,
            } => {
                out.push(format!(
                    "{pad}group{}{}",
                    gid(id),
                    if *should_break { " break" } else { "" }
                ));
                contents.dump_into(depth + 1, out)?;
            }
            Kind::Indent { contents, n } => {
                out.push(format!("{pad}indent {n}"));
                contents.dump_into(depth + 1, out)?;
            }
            Kind::Align(contents) | Kind::LineSuffix(contents) => {
                out.push(format!(
                    "{pad}{}",
                    if matches!(self.0.kind, Kind::Align(_)) {
                        "align"
                    } else {
                        "line_suffix"
                    }
                ));
                contents.dump_into(depth + 1, out)?;
            }
            Kind::IfBreak {
                broken,
                flat,
                group_id,
            } => {
                out.push(format!("{pad}if_break{}", gid(group_id)));
                out.push(format!("{pad}  broken:"));
                broken.dump_into(depth + 2, out)?;
                out.push(format!("{pad}  flat:"));
                flat.dump_into(depth + 2, out)?;
            }
            Kind::ConditionalGroup { alts, check } => {
                out.push(format!(
                    "{pad}conditional_group {}",
                    match check {
                        Check::FirstLine => "FIRST_LINE",
                        Check::AllLines => "ALL_LINES",
                    }
                ));
                for alt in alts {
                    alt.dump_into(depth + 1, out)?;
                }
            }
        }
        Ok(())
    }
}

fn gid(id: &Option<GroupId>) -> String {
    id.as_ref()
        .map_or_else(String::new, |id| format!(" id={}", id.name))
}

fn repr(s: &str) -> String {
    let quote = if s.contains('\'') && !s.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut result = String::from(quote);
    for ch in s.chars() {
        match ch {
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            ch if ch == quote => {
                result.push('\\');
                result.push(ch);
            }
            ch if ch.is_control() && (ch as u32) < 256 => {
                result.push_str(&format!("\\x{:02x}", ch as u32))
            }
            ch => result.push(ch),
        }
    }
    result.push(quote);
    result
}

#[cfg(test)]
mod tests {
    use super::{Check, Doc, GroupId, Kind, LineKind};

    #[test]
    fn leaf_metadata() {
        assert_eq!(Doc::text("中").unwrap().0.flat_width, 2);
        assert_eq!(Doc::text("\t").unwrap().0.flat_width, -1);
        assert!(Doc::text("a\nb").is_err());
        assert!(Doc::line(LineKind::Hard).0.forced);
        assert_eq!(Doc::line(LineKind::Soft).0.flat_width, 0);
    }

    #[test]
    fn composite_metadata_and_flatten() {
        let id = GroupId::new("x");
        let content = Doc::concat(vec![Doc::text("中").unwrap(), Doc::line(LineKind::Line)]);
        let grouped = Doc::group(content, Some(id.clone()), false);
        assert_eq!(grouped.0.flat_width, 3);
        assert_eq!(
            grouped.flatten().unwrap().dump().unwrap(),
            "group id=x\n  concat\n    text '中'\n    text ' '"
        );
        assert_eq!(
            Doc::if_break(Doc::break_parent(), Doc::text("x").unwrap(), Some(id))
                .0
                .flat_width,
            -1
        );
        assert!(
            Doc::conditional_group(
                vec![Doc::break_parent(), Doc::text("x").unwrap()],
                Check::AllLines
            )
            .unwrap()
            .0
            .flat_width
                == -1
        );
        assert!(
            Doc::conditional_group(vec![Doc::break_parent()], Check::FirstLine)
                .unwrap()
                .0
                .forced
        );
        assert!(Doc::line(LineKind::Literal).flatten().is_none());
    }

    #[test]
    fn deep_drop() {
        let mut doc = Doc::text("x").unwrap();
        for _ in 0..100_000 {
            doc = Doc::indent(doc, 2);
        }
        assert!(matches!(doc.0.kind, Kind::Indent { .. }));
        drop(doc);
    }
}
