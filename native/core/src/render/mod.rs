use std::collections::HashMap;

use crate::doc::{Check, Doc, HostError, Kind, LineKind};
use crate::width;

#[derive(Clone, Copy)]
pub struct RenderOptions {
    pub line_length: u32,
    pub tab_size: u32,
}

#[derive(Debug, PartialEq, Eq)]
pub struct LineRecord {
    pub code: String,
    pub trailing_comment: Option<String>,
    pub verbatim: bool,
}

#[derive(Default, Debug)]
pub struct RenderStats {
    pub fits_scans: u64,
    pub all_lines_dry_runs: u64,
    pub memo_hits: u64,
}

pub struct RenderOutput {
    pub text: String,
    pub lines: Vec<LineRecord>,
    pub stats: RenderStats,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Mode {
    Flat,
    Break,
}

#[derive(Clone, Copy)]
enum Item<'d> {
    Doc(&'d Doc),
    FillAt {
        parts: &'d [Doc],
        lazy: bool,
        start: usize,
        at_sep: bool,
    },
    LiteralLine,
    HardLine,
}

#[derive(Clone, Copy)]
struct Cmd<'d> {
    ind: i64,
    mode: Mode,
    item: Item<'d>,
}

impl<'d> Cmd<'d> {
    fn doc(ind: i64, mode: Mode, doc: &'d Doc) -> Self {
        Self {
            ind,
            mode,
            item: Item::Doc(doc),
        }
    }
}

struct Shared<'d> {
    opts: RenderOptions,
    limit: i64,
    modes: HashMap<u32, Mode>,
    undo: Vec<(u32, Option<Mode>)>,
    recording: usize,
    memo: HashMap<(usize, i64, i64, i64), usize>,
    scan_stack: Vec<Cmd<'d>>,
    stats: RenderStats,
}

impl Shared<'_> {
    fn set_mode(&mut self, id: u32, mode: Mode) {
        let previous = self.modes.insert(id, mode);
        if self.recording > 0 {
            self.undo.push((id, previous));
        }
    }

    fn rollback(&mut self, mark: usize) {
        for (id, previous) in self.undo.drain(mark..).rev() {
            match previous {
                Some(mode) => {
                    self.modes.insert(id, mode);
                }
                None => {
                    self.modes.remove(&id);
                }
            }
        }
    }
}

struct Rests<'r, 'd> {
    top: &'r [Cmd<'d>],
    outer: Option<&'r Rests<'r, 'd>>,
}

struct Printer<'s, 'r, 'd> {
    shared: &'s mut Shared<'d>,
    rests: Option<&'r Rests<'r, 'd>>,
    measure: bool,
    pos: i64,
    line: String,
    protect: usize,
    comment: Option<String>,
    line_verbatim: bool,
    records: Vec<LineRecord>,
    suffixes: Vec<Cmd<'d>>,
    remeasure: bool,
}

impl<'s, 'r, 'd> Printer<'s, 'r, 'd> {
    fn new(
        shared: &'s mut Shared<'d>,
        rests: Option<&'r Rests<'r, 'd>>,
        measure: bool,
        pos: i64,
    ) -> Self {
        Self {
            shared,
            rests,
            measure,
            pos,
            line: String::new(),
            protect: 0,
            comment: None,
            line_verbatim: false,
            records: Vec::new(),
            suffixes: Vec::new(),
            remeasure: false,
        }
    }

    fn finish(&mut self) {
        if !self.measure {
            let code = self.line[..self.protect].to_owned()
                + self.line[self.protect..].trim_end_matches([' ', '\t']);
            self.records.push(LineRecord {
                code,
                trailing_comment: self.comment.take(),
                verbatim: self.line_verbatim,
            });
            self.line.clear();
            self.protect = 0;
        }
        self.line_verbatim = false;
    }

    fn newline(&mut self, ind: i64) {
        self.finish();
        if !self.measure {
            self.line.push_str(&" ".repeat(ind.max(0) as usize));
        }
        self.pos = ind;
    }

    fn run(&mut self, cmds: &mut Vec<Cmd<'d>>) -> Result<bool, HostError> {
        loop {
            let Some(Cmd { ind, mode, item }) = cmds.pop() else {
                if self.suffixes.is_empty() {
                    return Ok(true);
                }
                cmds.extend(self.suffixes.drain(..).rev());
                continue;
            };
            let doc = match item {
                Item::Doc(doc) => doc,
                Item::FillAt {
                    parts,
                    lazy,
                    start,
                    at_sep,
                } => {
                    if at_sep {
                        self.fill_sep(parts, lazy, start, ind, mode, cmds)?;
                    } else {
                        self.fill(parts, lazy, start, ind, mode, cmds)?;
                    }
                    continue;
                }
                Item::LiteralLine => {
                    if self.flush_suffixes(cmds, Cmd { ind, mode, item }) {
                        continue;
                    }
                    self.newline(0);
                    continue;
                }
                Item::HardLine => {
                    if mode == Mode::Flat {
                        self.remeasure = true;
                    }
                    if self.flush_suffixes(cmds, Cmd { ind, mode, item }) {
                        continue;
                    }
                    self.newline(ind);
                    continue;
                }
            };
            match &doc.0.kind {
                Kind::Text { s, width } => {
                    if !self.measure {
                        self.line.push_str(s);
                    }
                    self.pos = if *width >= 0 {
                        self.pos + *width as i64
                    } else {
                        width::display_width(s, self.pos, self.shared.opts.tab_size as i64)
                            .map_err(width_error)?
                    };
                    if self.measure && self.pos > self.shared.limit && !self.line_verbatim {
                        return Ok(false);
                    }
                }
                Kind::Concat(parts) => {
                    cmds.extend(parts.iter().rev().map(|part| Cmd::doc(ind, mode, part)))
                }
                Kind::Line(kind) => {
                    if mode == Mode::Flat && !matches!(kind, LineKind::Hard | LineKind::Literal) {
                        if *kind == LineKind::Line {
                            if !self.measure {
                                self.line.push(' ');
                            }
                            self.pos += 1;
                        }
                        continue;
                    }
                    if mode == Mode::Flat {
                        self.remeasure = true;
                    }
                    if self.flush_suffixes(cmds, Cmd { ind, mode, item }) {
                        continue;
                    }
                    self.newline(if *kind == LineKind::Literal { 0 } else { ind });
                }
                Kind::Group { contents, id, .. } => {
                    let broken = doc.0.forced;
                    let next = if mode == Mode::Flat && !self.remeasure {
                        if broken {
                            Mode::Break
                        } else {
                            Mode::Flat
                        }
                    } else {
                        self.remeasure = false;
                        if broken
                            || !self.fits(
                                vec![Cmd::doc(ind, Mode::Flat, contents)],
                                cmds,
                                self.pos,
                                false,
                            )?
                        {
                            Mode::Break
                        } else {
                            Mode::Flat
                        }
                    };
                    if let Some(id) = id {
                        self.shared.set_mode(id.id, next);
                    }
                    cmds.push(Cmd::doc(ind, next, contents));
                }
                Kind::Indent { contents, n } => {
                    cmds.push(Cmd::doc(ind + *n as i64, mode, contents))
                }
                Kind::Align(contents) => cmds.push(Cmd::doc(self.pos, mode, contents)),
                Kind::Fill { parts, lazy } => self.fill(parts, *lazy, 0, ind, mode, cmds)?,
                Kind::IfBreak {
                    broken,
                    flat,
                    group_id,
                } => {
                    let group_mode = group_id.as_ref().map_or(mode, |id| {
                        self.shared.modes.get(&id.id).copied().unwrap_or(Mode::Flat)
                    });
                    cmds.push(Cmd::doc(
                        ind,
                        mode,
                        if group_mode == Mode::Break {
                            broken
                        } else {
                            flat
                        },
                    ));
                }
                Kind::ConditionalGroup { alts, check } => {
                    if mode == Mode::Flat && !self.remeasure && !doc.0.forced {
                        cmds.push(Cmd::doc(ind, Mode::Flat, &alts[0]));
                    } else {
                        self.remeasure = false;
                        cmds.push(self.select(doc, alts, *check, ind, cmds)?);
                    }
                }
                Kind::LineSuffix(contents) => {
                    if !self.measure {
                        self.suffixes.push(Cmd::doc(ind, mode, contents));
                    }
                }
                Kind::TrailingComment(text) => {
                    if !self.measure {
                        match &mut self.comment {
                            Some(comment) => {
                                comment.push(' ');
                                comment.push_str(text);
                            }
                            None => self.comment = Some(text.to_string()),
                        }
                    }
                }
                Kind::Verbatim { s, bol } => {
                    if *bol {
                        if !self.measure
                            && (!self.suffixes.is_empty()
                                || !self.line.trim_matches(' ').is_empty())
                        {
                            cmds.push(Cmd { ind, mode, item });
                            cmds.push(Cmd {
                                ind,
                                mode,
                                item: Item::LiteralLine,
                            });
                            continue;
                        }
                        self.line.clear();
                        self.protect = 0;
                        self.pos = 0;
                    }
                    for (index, segment) in s.split('\n').enumerate() {
                        if index > 0 {
                            self.finish();
                            self.pos = 0;
                        }
                        if segment.is_empty() {
                            continue;
                        }
                        if !self.measure {
                            self.line.push_str(segment);
                            self.protect = self.line.len();
                        }
                        self.pos = width::display_width(
                            segment,
                            self.pos,
                            self.shared.opts.tab_size as i64,
                        )
                        .map_err(width_error)?;
                        if self.measure
                            && index == 0
                            && self.pos > self.shared.limit
                            && !self.line_verbatim
                        {
                            return Ok(false);
                        }
                        self.line_verbatim = true;
                    }
                }
                Kind::ColumnText(make) => {
                    for (index, segment) in make(self.pos as u32)?.split('\n').enumerate() {
                        if index > 0 {
                            self.finish();
                            self.pos = 0;
                        }
                        if !self.measure {
                            self.line.push_str(segment);
                        }
                        self.pos = width::display_width(
                            segment,
                            self.pos,
                            self.shared.opts.tab_size as i64,
                        )
                        .map_err(width_error)?;
                    }
                }
                Kind::SuffixBreak => {
                    if !self.suffixes.is_empty() {
                        cmds.push(Cmd {
                            ind,
                            mode,
                            item: Item::HardLine,
                        });
                    }
                }
                Kind::OnRender(fn_) => {
                    if !self.measure {
                        fn_()?;
                    }
                }
                Kind::BreakParent => {}
            }
        }
    }

    fn flush_suffixes(&mut self, cmds: &mut Vec<Cmd<'d>>, line: Cmd<'d>) -> bool {
        if self.suffixes.is_empty() {
            return false;
        }
        cmds.push(line);
        cmds.extend(self.suffixes.drain(..).rev());
        true
    }

    fn fill(
        &mut self,
        parts: &'d [Doc],
        lazy: bool,
        index: usize,
        ind: i64,
        mode: Mode,
        cmds: &mut Vec<Cmd<'d>>,
    ) -> Result<(), HostError> {
        let remaining = parts.len() - index;
        if remaining == 0 {
            return Ok(());
        }
        let content = &parts[index];
        let fits = !(lazy && content.0.forced)
            && self.fits(
                vec![Cmd::doc(ind, Mode::Flat, content)],
                if remaining == 1 { cmds } else { &[] },
                self.pos,
                true,
            )?;
        if remaining == 1 {
            cmds.push(Cmd::doc(
                ind,
                if fits { Mode::Flat } else { Mode::Break },
                content,
            ));
            return Ok(());
        }
        let separator = &parts[index + 1];
        if remaining == 2 {
            let next = if fits { Mode::Flat } else { Mode::Break };
            cmds.push(Cmd::doc(ind, next, separator));
            cmds.push(Cmd::doc(ind, next, content));
            return Ok(());
        }
        if lazy && !fits {
            cmds.push(Cmd {
                ind,
                mode,
                item: Item::FillAt {
                    parts,
                    lazy,
                    start: index + 1,
                    at_sep: true,
                },
            });
            cmds.push(Cmd::doc(ind, Mode::Break, content));
            return Ok(());
        }
        let pair_fits = fits
            && self.fits(
                vec![
                    Cmd::doc(ind, Mode::Flat, &parts[index + 2]),
                    Cmd::doc(ind, Mode::Flat, separator),
                    Cmd::doc(ind, Mode::Flat, content),
                ],
                if remaining == 3 { cmds } else { &[] },
                self.pos,
                true,
            )?;
        cmds.push(Cmd {
            ind,
            mode,
            item: Item::FillAt {
                parts,
                lazy,
                start: index + 2,
                at_sep: false,
            },
        });
        cmds.push(Cmd::doc(
            ind,
            if pair_fits { Mode::Flat } else { Mode::Break },
            separator,
        ));
        cmds.push(Cmd::doc(
            ind,
            if fits { Mode::Flat } else { Mode::Break },
            content,
        ));
        Ok(())
    }

    fn fill_sep(
        &mut self,
        parts: &'d [Doc],
        lazy: bool,
        index: usize,
        ind: i64,
        mode: Mode,
        cmds: &mut Vec<Cmd<'d>>,
    ) -> Result<(), HostError> {
        let fits = self.suffixes.is_empty()
            && self.fits(
                vec![
                    Cmd::doc(ind, Mode::Flat, &parts[index + 1]),
                    Cmd::doc(ind, Mode::Flat, &parts[index]),
                ],
                if index + 2 == parts.len() { cmds } else { &[] },
                self.pos,
                true,
            )?;
        cmds.push(Cmd {
            ind,
            mode,
            item: Item::FillAt {
                parts,
                lazy,
                start: index + 1,
                at_sep: false,
            },
        });
        cmds.push(Cmd::doc(
            ind,
            if fits { Mode::Flat } else { Mode::Break },
            &parts[index],
        ));
        Ok(())
    }

    fn select(
        &mut self,
        doc: &'d Doc,
        alts: &'d [Doc],
        check: Check,
        ind: i64,
        cmds: &[Cmd<'d>],
    ) -> Result<Cmd<'d>, HostError> {
        let first = &alts[0];
        if !first.0.forced
            && self.fits(
                vec![Cmd::doc(ind, Mode::Flat, first)],
                cmds,
                self.pos,
                false,
            )?
        {
            return Ok(Cmd::doc(ind, Mode::Flat, first));
        }
        if check == Check::FirstLine {
            for alt in &alts[..alts.len() - 1] {
                if self.fits(vec![Cmd::doc(ind, Mode::Break, alt)], cmds, self.pos, false)? {
                    return Ok(Cmd::doc(ind, Mode::Break, alt));
                }
            }
            return Ok(Cmd::doc(ind, Mode::Break, alts.last().unwrap()));
        }
        let rest_width = self.scan(Vec::new(), cmds, 0, false)?;
        let rest_width = if rest_width < 0 {
            self.shared.limit.saturating_add(1)
        } else {
            rest_width
        };
        let key = (
            std::sync::Arc::as_ptr(&doc.0) as usize,
            self.pos,
            ind,
            rest_width,
        );
        let selected = if let Some(index) = self.shared.memo.get(&key) {
            self.shared.stats.memo_hits += 1;
            *index
        } else {
            let mut selected = alts.len() - 1;
            for (index, alt) in alts[..selected].iter().enumerate() {
                if self.all_lines_fit(alt, ind, cmds, rest_width)? {
                    selected = index;
                    break;
                }
            }
            self.shared.memo.insert(key, selected);
            selected
        };
        Ok(Cmd::doc(ind, Mode::Break, &alts[selected]))
    }

    fn all_lines_fit(
        &mut self,
        alt: &'d Doc,
        ind: i64,
        cmds: &[Cmd<'d>],
        rest_width: i64,
    ) -> Result<bool, HostError> {
        self.shared.stats.all_lines_dry_runs += 1;
        let mark = self.shared.undo.len();
        self.shared.recording += 1;
        let result = {
            let rests = Rests {
                top: cmds,
                outer: self.rests,
            };
            let mut sub = Printer::new(self.shared, Some(&rests), true, self.pos);
            sub.line_verbatim = self.line_verbatim;
            sub.run(&mut vec![Cmd::doc(ind, Mode::Break, alt)])
                .map(|fits| {
                    fits && (sub.line_verbatim
                        || sub.pos.saturating_add(rest_width) <= sub.shared.limit)
                })
        };
        self.shared.rollback(mark);
        self.shared.recording -= 1;
        result
    }

    fn fits(
        &mut self,
        next: Vec<Cmd<'d>>,
        cmds: &[Cmd<'d>],
        col: i64,
        must_be_flat: bool,
    ) -> Result<bool, HostError> {
        Ok(self.scan(next, cmds, col, must_be_flat)? >= 0)
    }

    fn scan(
        &mut self,
        next: Vec<Cmd<'d>>,
        cmds: &[Cmd<'d>],
        mut col: i64,
        mut must_be_flat: bool,
    ) -> Result<i64, HostError> {
        self.shared.stats.fits_scans += 1;
        let mut stack = std::mem::take(&mut self.shared.scan_stack);
        stack.clear();
        stack.extend(next);
        let result = (|| {
            let mut current = cmds;
            let mut outer = self.rests;
            let mut rest_offset = cmds.len();
            loop {
                if stack.is_empty() {
                    while rest_offset == 0 {
                        current = match outer {
                            Some(rest) => {
                                outer = rest.outer;
                                rest.top
                            }
                            None => return Ok(col),
                        };
                        rest_offset = current.len();
                    }
                    rest_offset -= 1;
                    stack.push(current[rest_offset]);
                    must_be_flat = false;
                }
                let Cmd { mode, item, .. } = stack.pop().unwrap();
                let (doc, kind) = match item {
                    Item::Doc(doc) => (doc, &doc.0.kind),
                    Item::FillAt { parts, start, .. } => {
                        stack.extend(
                            parts[start..]
                                .iter()
                                .rev()
                                .map(|part| Cmd::doc(0, mode, part)),
                        );
                        continue;
                    }
                    Item::LiteralLine | Item::HardLine => return Ok(col),
                };
                if mode == Mode::Flat
                    && matches!(
                        kind,
                        Kind::Concat(_)
                            | Kind::Fill { .. }
                            | Kind::Group { .. }
                            | Kind::ConditionalGroup { .. }
                            | Kind::Indent { .. }
                            | Kind::Align(_)
                            | Kind::IfBreak { .. }
                    )
                    && doc.0.flat_width >= 0
                {
                    col += doc.0.flat_width as i64;
                    if col > self.shared.limit {
                        return Ok(-1);
                    }
                    continue;
                }
                match kind {
                    Kind::Text { s, width } => {
                        col = if *width >= 0 {
                            col + *width as i64
                        } else {
                            width::display_width(s, col, self.shared.opts.tab_size as i64)
                                .map_err(width_error)?
                        };
                        if col > self.shared.limit {
                            return Ok(-1);
                        }
                    }
                    Kind::Concat(parts) => {
                        stack.extend(parts.iter().rev().map(|part| Cmd::doc(0, mode, part)))
                    }
                    Kind::Line(kind) => {
                        if mode == Mode::Break || matches!(kind, LineKind::Hard | LineKind::Literal)
                        {
                            return Ok(col);
                        }
                        if *kind == LineKind::Line {
                            col += 1;
                            if col > self.shared.limit {
                                return Ok(-1);
                            }
                        }
                    }
                    Kind::Group { contents, .. } => {
                        if must_be_flat && doc.0.forced {
                            return Ok(-1);
                        }
                        stack.push(Cmd::doc(
                            0,
                            if doc.0.forced { Mode::Break } else { mode },
                            contents,
                        ));
                    }
                    Kind::ConditionalGroup { alts, .. } => {
                        if must_be_flat && doc.0.forced {
                            return Ok(-1);
                        }
                        let broken = doc.0.forced || mode == Mode::Break;
                        stack.push(Cmd::doc(
                            0,
                            if broken { Mode::Break } else { Mode::Flat },
                            if broken {
                                alts.last().unwrap()
                            } else {
                                &alts[0]
                            },
                        ));
                    }
                    Kind::Indent { contents, .. } | Kind::Align(contents) => {
                        stack.push(Cmd::doc(0, mode, contents))
                    }
                    Kind::Fill { parts, .. } => {
                        stack.extend(parts.iter().rev().map(|part| Cmd::doc(0, mode, part)))
                    }
                    Kind::IfBreak {
                        broken,
                        flat,
                        group_id,
                    } => {
                        let group_mode = group_id.as_ref().map_or(mode, |id| {
                            self.shared.modes.get(&id.id).copied().unwrap_or(Mode::Flat)
                        });
                        stack.push(Cmd::doc(
                            0,
                            mode,
                            if group_mode == Mode::Break {
                                broken
                            } else {
                                flat
                            },
                        ));
                    }
                    Kind::Verbatim { s, bol } => {
                        let (head, has_newline) = s
                            .split_once('\n')
                            .map_or((s.as_ref(), false), |(head, _)| (head, true));
                        col = width::display_width(
                            head,
                            if *bol { 0 } else { col },
                            self.shared.opts.tab_size as i64,
                        )
                        .map_err(width_error)?;
                        if col > self.shared.limit {
                            return Ok(-1);
                        }
                        if has_newline {
                            return Ok(col);
                        }
                    }
                    Kind::ColumnText(make) => {
                        let text = make(col as u32)?;
                        let head = text.split('\n').next().unwrap();
                        return width::display_width(head, col, self.shared.opts.tab_size as i64)
                            .map_err(width_error);
                    }
                    Kind::LineSuffix(_)
                    | Kind::TrailingComment(_)
                    | Kind::BreakParent
                    | Kind::SuffixBreak
                    | Kind::OnRender(_) => {}
                }
            }
        })();
        self.shared.scan_stack = stack;
        result
    }
}

pub fn render(doc: &Doc, opts: RenderOptions, base_indent: u32) -> Result<RenderOutput, HostError> {
    let mut shared = Shared {
        opts,
        limit: if opts.line_length == 0 {
            i64::MAX
        } else {
            opts.line_length as i64
        },
        modes: HashMap::new(),
        undo: Vec::new(),
        recording: 0,
        memo: HashMap::new(),
        scan_stack: Vec::new(),
        stats: RenderStats::default(),
    };
    let mut printer = Printer::new(&mut shared, None, false, base_indent as i64);
    printer.line.push_str(&" ".repeat(base_indent as usize));
    printer.run(&mut vec![Cmd::doc(base_indent as i64, Mode::Break, doc)])?;
    printer.finish();
    let lines = printer.records;
    let text = align_trailing_comments(&lines, opts.line_length, opts.tab_size).join("\n");
    Ok(RenderOutput {
        text,
        lines,
        stats: shared.stats,
    })
}

pub fn flat_width(doc: &Doc, tab_size: u32) -> Result<Option<u32>, HostError> {
    if doc.0.forced {
        return Ok(None);
    }
    if doc.0.flat_width >= 0 {
        return Ok(Some(doc.0.flat_width as u32));
    }
    let opts = RenderOptions {
        line_length: 0,
        tab_size,
    };
    let mut shared = Shared {
        opts,
        limit: i64::MAX,
        modes: HashMap::new(),
        undo: Vec::new(),
        recording: 0,
        memo: HashMap::new(),
        scan_stack: Vec::new(),
        stats: RenderStats::default(),
    };
    let mut printer = Printer::new(&mut shared, None, true, 0);
    printer.run(&mut vec![Cmd::doc(0, Mode::Flat, doc)])?;
    Ok(Some(printer.pos as u32))
}

pub fn align_trailing_comments(
    lines: &[LineRecord],
    line_length: u32,
    tab_size: u32,
) -> Vec<String> {
    let limit = if line_length == 0 {
        i64::MAX
    } else {
        line_length as i64
    };
    let mut out = Vec::with_capacity(lines.len());
    let mut run: Vec<(&str, i64, &str)> = Vec::new();
    let mut col = 0;
    let mut allowed = i64::MAX;
    for rec in lines {
        let Some(comment) = rec.trailing_comment.as_deref() else {
            flush(&mut run, col, &mut out);
            out.push(rec.code.clone());
            continue;
        };
        if rec.verbatim || rec.code.is_empty() {
            flush(&mut run, col, &mut out);
            out.push(if rec.code.is_empty() {
                comment.to_owned()
            } else {
                format!("{} {comment}", rec.code)
            });
            continue;
        }
        let width =
            width::display_width(&rec.code, 0, tab_size as i64).unwrap_or(rec.code.len() as i64);
        let comment_width =
            width::display_width(comment, 0, tab_size as i64).unwrap_or(comment.len() as i64);
        let own = if width + 1 + comment_width <= limit {
            limit - comment_width
        } else {
            i64::MAX
        };
        if !run.is_empty() && col.max(width) + 1 > allowed.min(own) {
            flush(&mut run, col, &mut out);
        }
        if run.is_empty() {
            col = width;
            allowed = own;
        } else {
            col = col.max(width);
            allowed = allowed.min(own);
        }
        run.push((&rec.code, width, comment));
    }
    flush(&mut run, col, &mut out);
    out
}

fn flush(run: &mut Vec<(&str, i64, &str)>, col: i64, out: &mut Vec<String>) {
    for (code, width, comment) in run.drain(..) {
        out.push(format!(
            "{code}{}{comment}",
            " ".repeat((col + 1 - width) as usize)
        ));
    }
}

fn width_error(message: &'static str) -> HostError {
    HostError::new(std::io::Error::new(
        std::io::ErrorKind::InvalidInput,
        message,
    ))
}

#[cfg(test)]
mod tests {
    use super::{align_trailing_comments, flat_width, render, LineRecord, RenderOptions};
    use crate::doc::{Check, Doc, GroupId, HostError, Kind, LineKind};
    use proptest::prelude::*;
    use std::fmt;
    use std::sync::{Arc, Mutex};

    #[derive(Clone)]
    struct TestDoc(Doc);

    impl fmt::Debug for TestDoc {
        fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
            self.0.dump().unwrap().fmt(formatter)
        }
    }

    fn measured_flat_width(doc: &Doc, tab_size: u32) -> Option<i64> {
        match &doc.0.kind {
            Kind::Text { s, .. } => crate::width::display_width(s, 0, tab_size as i64).ok(),
            Kind::Concat(parts) | Kind::Fill { parts, .. } => {
                parts.iter().try_fold(0i64, |sum, part| {
                    Some(sum + measured_flat_width(part, tab_size)?)
                })
            }
            Kind::Group { contents, .. }
            | Kind::Indent { contents, .. }
            | Kind::Align(contents) => measured_flat_width(contents, tab_size),
            Kind::Line(LineKind::Line) => Some(1),
            Kind::Line(LineKind::Soft) => Some(0),
            Kind::IfBreak { flat, .. } => measured_flat_width(flat, tab_size),
            Kind::ConditionalGroup { alts, .. } => measured_flat_width(&alts[0], tab_size),
            Kind::LineSuffix(_)
            | Kind::TrailingComment(_)
            | Kind::SuffixBreak
            | Kind::OnRender(_) => Some(0),
            _ => None,
        }
    }

    fn doc_tree() -> impl Strategy<Value = TestDoc> {
        let leaf = prop_oneof![
            prop::sample::select(vec!["", "x", "wide", "中", "x  ", "\t"])
                .prop_map(|value| TestDoc(Doc::text(value).unwrap())),
            prop::sample::select(vec![
                LineKind::Line,
                LineKind::Soft,
                LineKind::Hard,
                LineKind::Literal,
            ])
            .prop_map(|kind| TestDoc(Doc::line(kind))),
            Just(TestDoc(Doc::verbatim("raw  \n  raw\t", false))),
            Just(TestDoc(Doc::break_parent())),
            Just(TestDoc(Doc::suffix_break())),
        ];
        leaf.prop_recursive(4, 64, 4, |inner| {
            prop_oneof![
                proptest::collection::vec(inner.clone(), 0..5).prop_map(|parts| TestDoc(
                    Doc::concat(parts.into_iter().map(|part| part.0).collect())
                )),
                (
                    proptest::collection::vec(inner.clone(), 0..5),
                    any::<bool>()
                )
                    .prop_map(|(parts, lazy)| TestDoc(Doc::fill(
                        parts.into_iter().map(|part| part.0).collect(),
                        lazy
                    ))),
                (inner.clone(), any::<bool>()).prop_map(|(doc, should_break)| TestDoc(Doc::group(
                    doc.0,
                    None,
                    should_break
                ))),
                (inner.clone(), 0..5i32)
                    .prop_map(|(doc, depth)| TestDoc(Doc::indent(doc.0, depth))),
                inner.clone().prop_map(|doc| TestDoc(Doc::align(doc.0))),
                (inner.clone(), inner.clone())
                    .prop_map(|(broken, flat)| TestDoc(Doc::if_break(broken.0, flat.0, None))),
                proptest::collection::vec(inner.clone(), 1..4).prop_map(|alts| TestDoc(
                    Doc::conditional_group(
                        alts.into_iter().map(|alt| alt.0).collect(),
                        Check::FirstLine
                    )
                    .unwrap()
                )),
                inner.prop_map(|doc| TestDoc(Doc::line_suffix(doc.0))),
            ]
        })
    }

    proptest! {
        #![proptest_config(ProptestConfig::with_cases(128))]

        #[test]
        fn random_doc_render_and_flat_width(doc in doc_tree(), length in 1..100u32, tab_size in 1..9u32) {
            let doc = doc.0;
            let opts = RenderOptions { line_length: length, tab_size };
            let result = render(&doc, opts, 0).unwrap();
            for line in &result.lines {
                if !line.verbatim {
                    prop_assert!(!line.code.ends_with([' ', '\t']));
                }
            }
            if doc.0.flat_width >= 0 {
                let width = measured_flat_width(&doc, tab_size).unwrap();
                prop_assert_eq!(doc.0.flat_width as i64, width);
                prop_assert_eq!(flat_width(&doc, tab_size).unwrap(), Some(width as u32));
            }
        }
    }

    fn text(s: &str) -> Doc {
        Doc::text(s).unwrap()
    }
    fn line() -> Doc {
        Doc::line(LineKind::Line)
    }
    fn concat(parts: Vec<Doc>) -> Doc {
        Doc::concat(parts)
    }
    fn group(parts: Vec<Doc>) -> Doc {
        Doc::group(concat(parts), None, false)
    }
    fn output(doc: &Doc, length: u32) -> super::RenderOutput {
        render(
            doc,
            RenderOptions {
                line_length: length,
                tab_size: 2,
            },
            0,
        )
        .unwrap()
    }

    #[test]
    fn command_order_and_line_trim() {
        let doc = Doc::concat(vec![
            Doc::text("a  ").unwrap(),
            Doc::line(LineKind::Hard),
            Doc::text("b ").unwrap(),
        ]);
        let result = render(
            &doc,
            RenderOptions {
                line_length: 80,
                tab_size: 2,
            },
            2,
        )
        .unwrap();
        assert_eq!(result.text, "  a\n  b");
        assert_eq!(result.lines.len(), 2);
    }

    #[test]
    fn groups_indent_align_and_widths() {
        let doc = group(vec![text("aaaa"), line(), text("bbbb")]);
        assert_eq!(output(&doc, 9).text, "aaaa bbbb");
        assert_eq!(output(&doc, 8).text, "aaaa\nbbbb");
        assert_eq!(flat_width(&doc, 2).unwrap(), Some(9));
        let nested = concat(vec![
            text("ab"),
            Doc::align(concat(vec![
                text("c"),
                Doc::indent(concat(vec![Doc::line(LineKind::Hard), text("e")]), 2),
                Doc::line(LineKind::Hard),
                text("f"),
            ])),
        ]);
        assert_eq!(output(&nested, 80).text, "abc\n    e\n  f");
        let literal = Doc::indent(
            concat(vec![
                text("a"),
                Doc::line(LineKind::Hard),
                text("b"),
                Doc::line(LineKind::Literal),
                text("c"),
            ]),
            4,
        );
        assert_eq!(output(&literal, 80).text, "a\n    b\nc");
        assert_eq!(flat_width(&literal, 2).unwrap(), None);
        assert_eq!(
            render(
                &doc,
                RenderOptions {
                    line_length: 12,
                    tab_size: 2
                },
                4
            )
            .unwrap()
            .text,
            "    aaaa\n    bbbb"
        );
        assert_eq!(
            output(&group(vec![text("中\t"), line(), text("x")]), 6).text,
            "中\t x"
        );
    }

    #[test]
    fn multiline_verbatim_first_line_counts_toward_fit() {
        let doc = group(vec![
            text("f("),
            line(),
            Doc::verbatim("abcdefghijk\nsecond", false),
            text(")"),
        ]);
        assert_eq!(output(&doc, 13).text, "f(\nabcdefghijk\nsecond)");
        assert_eq!(output(&doc, 14).text, "f( abcdefghijk\nsecond)");
        let alternatives = Doc::conditional_group(
            vec![
                concat(vec![
                    text("f("),
                    Doc::verbatim("abcdefghijk\nsecond", false),
                ]),
                concat(vec![
                    text("f("),
                    Doc::line(LineKind::Hard),
                    Doc::verbatim("abcdefghijk\nsecond", false),
                ]),
            ],
            Check::AllLines,
        )
        .unwrap();
        assert_eq!(output(&alternatives, 12).text, "f(\nabcdefghijk\nsecond");
    }

    #[test]
    fn hardline_in_flat_mode_remeasures_next_group() {
        let alt = Doc::conditional_group(
            vec![
                concat(vec![text("a"), Doc::line(LineKind::Hard)]),
                text("x"),
            ],
            Check::FirstLine,
        )
        .unwrap();
        let doc = group(vec![alt, group(vec![text("aa"), line(), text("bb")])]);
        assert_eq!(output(&doc, 4).text, "a\naa\nbb");
    }

    #[test]
    fn suffixes_comments_and_group_ids() {
        let id = GroupId::new("g");
        let doc = concat(vec![
            Doc::group(
                concat(vec![text("aaaa"), line(), text("bbbb")]),
                Some(id.clone()),
                false,
            ),
            Doc::if_break(text(" broken"), text(" flat"), Some(id)),
        ]);
        assert_eq!(output(&doc, 20).text, "aaaa bbbb flat");
        assert_eq!(output(&doc, 9).text, "aaaa\nbbbb broken");
        let doc = concat(vec![
            text("a"),
            Doc::line_suffix(text(";")),
            text("b"),
            Doc::line(LineKind::Hard),
            text("c"),
            Doc::line_suffix(text("!")),
        ]);
        assert_eq!(output(&doc, 80).text, "ab;\nc!");
        let doc = Doc::indent(
            concat(vec![
                text("a"),
                Doc::trailing_comment("// c").unwrap(),
                Doc::suffix_break(),
                text("b"),
            ]),
            2,
        );
        assert_eq!(output(&doc, 80).text, "a // c\n  b");
        let doc = concat(vec![
            text("a;"),
            Doc::trailing_comment("// x").unwrap(),
            Doc::line(LineKind::Hard),
            text("longer;"),
            Doc::trailing_comment("// y").unwrap(),
        ]);
        let result = output(&doc, 80);
        assert_eq!(result.lines[0].trailing_comment.as_deref(), Some("// x"));
        assert_eq!(result.text, "a;      // x\nlonger; // y");
    }

    #[test]
    fn fill_pair_packing_and_lazy_separator() {
        for lazy in [false, true] {
            let doc = Doc::fill(
                vec![
                    text("aa"),
                    line(),
                    text("bb"),
                    line(),
                    text("cc"),
                    line(),
                    text("dd"),
                ],
                lazy,
            );
            assert_eq!(output(&doc, 8).text, "aa bb cc\ndd");
            assert_eq!(output(&doc, 5).text, "aa bb\ncc dd");
        }
        let broken = group(vec![text("aaaaaa"), Doc::line(LineKind::Soft), text("b")]);
        let parts = vec![broken, line(), text("cc"), line(), text("dd")];
        assert_eq!(
            output(&Doc::fill(parts.clone(), false), 5).text,
            "aaaaaa\nb\ncc dd"
        );
        assert_eq!(output(&Doc::fill(parts, true), 5).text, "aaaaaa\nb cc\ndd");
        let doc = concat(vec![
            text("f("),
            Doc::align(Doc::fill(
                vec![text("a,"), line(), text("b,"), line(), text("c")],
                false,
            )),
            text("): real throws {"),
        ]);
        assert_eq!(output(&doc, 24).text, "f(a, b,\n  c): real throws {");
    }

    #[test]
    fn conditional_checks_all_lines_and_following_text() {
        let alts = vec![
            concat(vec![
                text("aaa"),
                Doc::line(LineKind::Hard),
                text(&"b".repeat(30)),
            ]),
            concat(vec![text("ccc"), Doc::line(LineKind::Hard), text("dd")]),
        ];
        let first = Doc::conditional_group(alts.clone(), Check::FirstLine).unwrap();
        let all = Doc::conditional_group(alts, Check::AllLines).unwrap();
        assert_eq!(output(&first, 20).text, format!("aaa\n{}", "b".repeat(30)));
        let result = output(&all, 20);
        assert_eq!(result.text, "ccc\ndd");
        assert_eq!(result.stats.all_lines_dry_runs, 1);
        let following = concat(vec![
            Doc::conditional_group(
                vec![
                    concat(vec![text("a"), Doc::line(LineKind::Hard), text("bbbb")]),
                    concat(vec![text("c"), Doc::line(LineKind::Hard), text("d")]),
                ],
                Check::AllLines,
            )
            .unwrap(),
            text("zzzz"),
        ]);
        assert_eq!(output(&following, 5).text, "c\ndzzzz");
    }

    #[test]
    fn verbatim_bol_protected_whitespace_and_callbacks() {
        let doc = concat(vec![
            text("a = "),
            Doc::verbatim("x  \t\r\n\t y \n", false),
            text("z  "),
            Doc::line(LineKind::Hard),
            text("w "),
        ]);
        let result = output(&doc, 80);
        assert_eq!(result.text, "a = x  \t\r\n\t y \nz\nw");
        assert_eq!(
            result
                .lines
                .iter()
                .map(|line| line.verbatim)
                .collect::<Vec<_>>(),
            vec![true, true, false, false]
        );
        let bol = concat(vec![
            text("a;"),
            Doc::trailing_comment("// c").unwrap(),
            Doc::verbatim("  x  ;\n\ty;", true),
        ]);
        assert_eq!(output(&bol, 80).text, "a; // c\n  x  ;\n\ty;");
        let calls = Arc::new(Mutex::new(Vec::new()));
        let recorder = |label: &'static str| {
            let calls = Arc::clone(&calls);
            Doc::on_render(Arc::new(move || {
                calls.lock().unwrap().push(label);
                Ok(())
            }))
        };
        let conditional = Doc::conditional_group(
            vec![
                concat(vec![text("a"), recorder("flat")]),
                concat(vec![text("b"), recorder("broken")]),
            ],
            Check::AllLines,
        )
        .unwrap();
        assert_eq!(output(&conditional, 80).text, "a");
        assert_eq!(*calls.lock().unwrap(), vec!["flat"]);
        let column = Doc::column_text(Arc::new(|col| {
            Ok(format!("/* at {col}\n{}*/", " ".repeat(col as usize)))
        }));
        assert_eq!(
            output(&concat(vec![text("ab"), column]), 80).text,
            "ab/* at 2\n  */"
        );
        assert!(output(
            &group(vec![
                text("a"),
                line(),
                Doc::column_text(Arc::new(|col| Ok(col.to_string())))
            ]),
            80
        )
        .text
        .starts_with("a\n"));
        let failing = Doc::column_text(Arc::new(|_| {
            Err(HostError::new(std::io::Error::other("callback failed")))
        }));
        assert_eq!(
            render(
                &failing,
                RenderOptions {
                    line_length: 80,
                    tab_size: 2
                },
                0
            )
            .err()
            .unwrap()
            .to_string(),
            "callback failed"
        );
        assert_eq!(flat_width(&failing, 2).unwrap(), None);
    }

    #[test]
    fn comment_alignment_and_run_splits() {
        let records = vec![
            LineRecord {
                code: "x;".into(),
                trailing_comment: Some("// first comment".into()),
                verbatim: false,
            },
            LineRecord {
                code: "longer_name = 1;".into(),
                trailing_comment: Some("// c2".into()),
                verbatim: false,
            },
            LineRecord {
                code: "y = 2;".into(),
                trailing_comment: Some("// c3".into()),
                verbatim: false,
            },
            LineRecord {
                code: "".into(),
                trailing_comment: None,
                verbatim: false,
            },
            LineRecord {
                code: "z;".into(),
                trailing_comment: Some("// v".into()),
                verbatim: true,
            },
        ];
        assert_eq!(
            align_trailing_comments(&records, 24, 2),
            vec![
                "x; // first comment",
                "longer_name = 1; // c2",
                "y = 2;           // c3",
                "",
                "z; // v"
            ]
        );
    }

    #[test]
    fn memo_reused_without_leaking_dry_run_group_modes() {
        let id = GroupId::new("inner");
        let first = concat(vec![
            Doc::group(
                concat(vec![text("aa"), line(), text("bb")]),
                Some(id.clone()),
                false,
            ),
            Doc::line(LineKind::Hard),
            text("long last line"),
        ]);
        let second = concat(vec![
            text("c"),
            Doc::line(LineKind::Hard),
            Doc::if_break(text("wrong"), text("ok"), Some(id)),
        ]);
        let conditional = Doc::conditional_group(vec![first, second], Check::AllLines).unwrap();
        let doc = concat(vec![
            conditional.clone(),
            Doc::line(LineKind::Hard),
            conditional,
        ]);
        let result = output(&doc, 8);
        assert_eq!(result.text, "c\nok\nc\nok");
        assert_eq!(result.stats.memo_hits, 1);
        assert_eq!(result.stats.all_lines_dry_runs, 1);
    }

    #[test]
    fn probe_callbacks_return_errors_and_on_render_is_not_probed() {
        let fail = Doc::column_text(Arc::new(|_| {
            Err(HostError::new(std::io::Error::other("probe failed")))
        }));
        for check in [Check::FirstLine, Check::AllLines] {
            let doc = Doc::conditional_group(vec![fail.clone(), text("fallback")], check).unwrap();
            assert_eq!(
                render(
                    &doc,
                    RenderOptions {
                        line_length: 5,
                        tab_size: 2
                    },
                    0
                )
                .err()
                .unwrap()
                .to_string(),
                "probe failed"
            );
        }
        let callback = Doc::on_render(Arc::new(|| {
            Err(HostError::new(std::io::Error::other("render failed")))
        }));
        assert_eq!(
            render(
                &callback,
                RenderOptions {
                    line_length: 80,
                    tab_size: 2
                },
                0
            )
            .err()
            .unwrap()
            .to_string(),
            "render failed"
        );
        let doc = group(vec![
            text("f(a,"),
            Doc::trailing_comment("// c").unwrap(),
            line(),
            Doc::suffix_break(),
            text("b)"),
        ]);
        assert_eq!(output(&doc, 80).text, "f(a, // c\nb)");
        assert_eq!(
            flat_width(&concat(vec![text("\tq"), line(), text("x")]), 4).unwrap(),
            Some(7)
        );
    }
}
