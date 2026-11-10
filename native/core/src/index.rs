use std::collections::{HashMap, HashSet};

use crate::lexer::token::{Pos, Token, TokenKind, NO_MATCH};

pub type NodeId = u32;
pub type Span = (u32, u32);
pub const NO_NODE: NodeId = u32::MAX;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BaseRule {
    Leaf,
    Block,
    AttrGroup,
    ArrayRow,
    Module,
    Formal,
    Signature,
    Attribute,
    New,
    #[default]
    Other,
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum BracketRule {
    #[default]
    None,
    FnCall,
    FirstParen,
    OpCall,
    Catch,
    Square,
    Domain,
    Visibility,
    Function,
    Interface,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NodeClass {
    pub base: BaseRule,
    pub body_owner: bool,
    pub brackets: BracketRule,
    pub expression_kind: bool,
    pub flags: u16,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Extra {
    pub implicit_module: bool,
    pub implicit_formal: bool,
    pub called: Option<NodeId>,
    pub name: Option<(Pos, Pos)>,
    pub paren: Option<(Pos, Pos)>,
    pub tuple_expansion: bool,
    pub catch_parens: bool,
    pub domain_curly: bool,
    pub formal_list: bool,
    pub parenless: bool,
    pub expression_level: bool,
}

#[derive(Default)]
pub struct AstFacts {
    pub class: Vec<NodeClass>,
    pub parent: Vec<NodeId>,
    pub kids: Vec<NodeId>,
    pub kid_range: Vec<(u32, u32)>,
    pub loc: Vec<(Pos, Pos)>,
    pub curly: Vec<Option<(Pos, Pos)>>,
    pub extra: Vec<Extra>,
}

pub struct TokenIndex {
    pub tokens: Vec<Token>,
    pub facts: AstFacts,
    spans: Vec<Option<Span>>,
    from_curly: Vec<bool>,
    sig_ends: HashSet<Pos>,
    src_kids: Vec<Vec<NodeId>>,
    owner: Vec<NodeId>,
    own: Vec<Vec<u32>>,
    structural: Vec<Vec<u32>>,
    user_parens: Vec<Vec<(u32, u32, NodeId)>>,
    parens_around: Vec<Vec<Span>>,
    pub problems: Vec<(NodeId, NodeId)>,
}

impl TokenIndex {
    pub fn new(text: &str, tokens: Vec<Token>, facts: AstFacts) -> Self {
        let count = facts.class.len();
        let owner = vec![NO_NODE; tokens.len()];
        let mut index = Self {
            tokens,
            facts,
            spans: vec![None; count],
            from_curly: vec![false; count],
            sig_ends: HashSet::new(),
            src_kids: vec![Vec::new(); count],
            owner,
            own: vec![Vec::new(); count],
            structural: vec![Vec::new(); count],
            user_parens: vec![Vec::new(); count],
            parens_around: vec![Vec::new(); count],
            problems: Vec::new(),
        };
        index.compute_spans(text);
        index.compute_ownership();
        index.compute_brackets(text);
        index
    }

    pub fn find_start(&self, pos: Pos) -> Option<u32> {
        let index = self.tokens.partition_point(|token| token.start < pos);
        self.tokens
            .get(index)
            .filter(|token| token.start == pos)
            .map(|_| index as u32)
    }

    pub fn find_end(&self, pos: Pos) -> Option<u32> {
        let code = &self.tokens[..self.tokens.len().saturating_sub(1)];
        let index = code
            .partition_point(|token| token.end <= pos)
            .checked_sub(1)?;
        (code[index].end == pos).then_some(index as u32)
    }

    pub fn span(&self, start: Pos, end: Pos) -> Option<Span> {
        if start.line == 0 || start >= end {
            return None;
        }
        let first = self
            .find_start(start)
            .unwrap_or_else(|| self.tokens.partition_point(|token| token.start < start) as u32);
        let last = self.find_end(end).or_else(|| {
            self.tokens
                .partition_point(|token| token.end <= end)
                .checked_sub(1)
                .map(|index| index as u32)
        })?;
        (first <= last && self.tokens.get(first as usize)?.kind != TokenKind::Eof)
            .then_some((first, last))
    }

    pub fn next_code(&self, index: u32) -> u32 {
        let mut next = index as usize + 1;
        while matches!(
            self.tokens[next].kind,
            TokenKind::LineComment | TokenKind::BlockComment
        ) {
            next += 1;
        }
        next as u32
    }

    pub fn prev_code(&self, index: u32) -> Option<u32> {
        let mut prev = index as usize;
        while prev > 0 {
            prev -= 1;
            if !matches!(
                self.tokens[prev].kind,
                TokenKind::LineComment | TokenKind::BlockComment
            ) {
                return Some(prev as u32);
            }
        }
        None
    }

    pub fn node_span(&self, node: NodeId) -> Option<Span> {
        self.spans.get(node as usize).copied().flatten()
    }

    pub fn header_span(&self, start: Pos, end: Pos) -> Option<Span> {
        let (first, last) = self.span(start, end)?;
        if self.sig_ends.contains(&end) {
            return Some((first, self.prev_code(last).unwrap_or(first)));
        }
        Some((first, last))
    }

    pub fn stmt_span(&self, text: &str, node: NodeId) -> Option<Span> {
        let (first, last) = self.node_span(node)?;
        let next = self.next_code(last);
        (self.tokens[next as usize].kind == TokenKind::Punct
            && self.text(text, next) == ";"
            && (self.owner(next) == NO_NODE
                || self.facts.class[self.owner(next) as usize].flags & 2 == 0))
            .then_some((first, next))
            .or(Some((first, last)))
    }

    pub fn is_wide_identifier(&self, node: NodeId) -> bool {
        if self.facts.class[node as usize].flags & 1 == 0 {
            return false;
        }
        let parent = self.facts.parent[node as usize];
        parent != NO_NODE
            && self.facts.class[parent as usize].brackets == BracketRule::FnCall
            && self.facts.extra[parent as usize].called == Some(node)
            && self.facts.loc[node as usize] == self.facts.loc[parent as usize]
    }

    pub fn owner(&self, token: u32) -> NodeId {
        self.owner[token as usize]
    }

    pub fn own_tokens(&self, node: NodeId) -> &[u32] {
        &self.own[node as usize]
    }

    pub fn children(&self, node: NodeId) -> &[NodeId] {
        &self.src_kids[node as usize]
    }

    pub fn structural_brackets(&self, node: NodeId) -> &[u32] {
        &self.structural[node as usize]
    }

    pub fn user_parens(&self, node: NodeId) -> &[(u32, u32, NodeId)] {
        &self.user_parens[node as usize]
    }

    pub fn parens_around(&self, node: NodeId) -> &[Span] {
        &self.parens_around[node as usize]
    }

    fn compute_brackets(&mut self, text: &str) {
        for node in 0..self.facts.class.len() {
            self.structural[node] = self.find_structural_brackets(text, node as NodeId);
        }
        for node in 0..self.facts.class.len() {
            self.user_parens[node] = self.find_user_parens(text, node as NodeId);
        }
        for node in 0..self.facts.class.len() {
            for &(open, close, kid) in &self.user_parens[node] {
                let mut parent = self.facts.parent[kid as usize];
                while parent != NO_NODE
                    && self.facts.class[parent as usize].base == BaseRule::Block
                    && !self.from_curly[parent as usize]
                {
                    parent = self.facts.parent[parent as usize];
                }
                if parent == node as NodeId {
                    self.parens_around[kid as usize].push((open, close));
                }
            }
        }
        for layers in &mut self.parens_around {
            layers.sort_unstable_by(|a, b| b.cmp(a));
        }
    }

    fn first_own(&self, text: &str, node: NodeId, chars: &str, after: Option<u32>) -> Vec<u32> {
        self.own_tokens(node)
            .iter()
            .copied()
            .find(|&token| {
                after.is_none_or(|last| token > last)
                    && self.tokens[token as usize].kind == TokenKind::Punct
                    && chars.contains(self.text(text, token))
            })
            .into_iter()
            .collect()
    }

    fn find_structural_brackets(&self, text: &str, node: NodeId) -> Vec<u32> {
        let class = self.facts.class[node as usize];
        let extra = self.facts.extra[node as usize];
        let mut found = match class.brackets {
            BracketRule::FnCall => {
                let called_end = extra
                    .called
                    .and_then(|called| self.node_span(called))
                    .map(|sp| sp.1);
                let mut opens = called_end
                    .map_or_else(Vec::new, |end| self.first_own(text, node, "([", Some(end)));
                if let Some(&open) = opens.first() {
                    if self.text(text, open) == "(" {
                        let close = self.tokens[open as usize].partner;
                        let inside: Vec<_> = self
                            .children(node)
                            .iter()
                            .copied()
                            .filter(|&kid| {
                                let start = self.spans[kid as usize].unwrap().0;
                                open < start && start < close
                            })
                            .collect();
                        if inside.len() == 1
                            && self.facts.extra[inside[0] as usize]
                                .paren
                                .and_then(|(start, end)| self.span(start, end))
                                == Some((open, close))
                        {
                            opens.clear();
                        }
                    }
                }
                opens
            }
            BracketRule::FirstParen => self.first_own(text, node, "(", None),
            BracketRule::OpCall if extra.tuple_expansion => self.first_own(text, node, "(", None),
            BracketRule::Catch if extra.catch_parens => self.first_own(text, node, "(", None),
            BracketRule::Square => self.first_own(text, node, "[", None),
            BracketRule::Domain => {
                self.first_own(text, node, if extra.domain_curly { "{" } else { "[" }, None)
            }
            BracketRule::Visibility => self.first_own(text, node, "{", None),
            BracketRule::Function if !extra.parenless => {
                let after = extra
                    .name
                    .and_then(|(start, end)| self.span(start, end))
                    .and_then(|sp| sp.0.checked_sub(1));
                self.first_own(text, node, "(", after)
            }
            BracketRule::Interface if extra.formal_list => self.first_own(text, node, "(", None),
            _ => Vec::new(),
        };
        if class.base == BaseRule::Block {
            if self.from_curly[node as usize] {
                if let Some((first, _)) = self.node_span(node) {
                    found.push(first);
                }
            }
        } else if let Some((start, end)) = self.facts.curly[node as usize] {
            if let Some((first, _)) = self.span(start, end) {
                if self.owner(first) == node {
                    found.push(first);
                }
            }
        }
        found
    }

    fn unwrap_implicit_block(&self, mut node: NodeId) -> NodeId {
        while self.facts.class[node as usize].base == BaseRule::Block
            && !self.from_curly[node as usize]
        {
            let kids = self.children(node);
            if kids.len() != 1 || self.node_span(kids[0]) != self.node_span(node) {
                break;
            }
            node = kids[0];
        }
        node
    }

    fn find_user_parens(&self, text: &str, node: NodeId) -> Vec<(u32, u32, NodeId)> {
        let own = self.own_tokens(node);
        if !own.iter().any(|&token| self.text(text, token) == "(") {
            return Vec::new();
        }
        let structural = self.structural_brackets(node);
        let mut found = Vec::new();
        for &open in own {
            let tok = &self.tokens[open as usize];
            if tok.kind != TokenKind::Punct
                || self.text(text, open) != "("
                || structural.contains(&open)
            {
                continue;
            }
            let close = tok.partner;
            assert_ne!(close, NO_MATCH);
            let inside: Vec<_> = self
                .children(node)
                .iter()
                .copied()
                .filter(|&kid| {
                    let start = self.spans[kid as usize].unwrap().0;
                    open < start && start <= close
                })
                .collect();
            let others = own.iter().any(|&token| {
                open < token
                    && token < close
                    && !matches!(
                        self.tokens[token as usize].kind,
                        TokenKind::LineComment | TokenKind::BlockComment
                    )
                    && !matches!(self.text(text, token), "(" | ")")
            });
            if inside.len() == 1 && self.spans[inside[0] as usize].unwrap().1 < close && !others {
                found.push((open, close, self.unwrap_implicit_block(inside[0])));
            }
        }
        found
    }

    pub fn unexplained_brackets(&self, text: &str, node: NodeId) -> Vec<u32> {
        let structural = self.structural_brackets(node);
        let user = self.user_parens(node);
        self.own_tokens(node)
            .iter()
            .copied()
            .filter(|&token| {
                let tok = &self.tokens[token as usize];
                if tok.kind != TokenKind::Punct || tok.partner == NO_MATCH {
                    return false;
                }
                match self.text(text, token) {
                    "(" | "[" | "{" => {
                        !structural.contains(&token)
                            && !user.iter().any(|&(open, _, _)| open == token)
                    }
                    _ => !structural
                        .iter()
                        .chain(user.iter().map(|triple| &triple.0))
                        .any(|&open| self.tokens[open as usize].partner == token),
                }
            })
            .collect()
    }

    pub fn body_delimiters(&self, text: &str, node: NodeId) -> Vec<u32> {
        let mut found = Vec::new();
        if !matches!(
            self.facts.class[node as usize].brackets,
            BracketRule::Domain | BracketRule::Visibility
        ) {
            for &open in self.structural_brackets(node) {
                if self.text(text, open) == "{" {
                    let close = self.tokens[open as usize].partner;
                    if close != NO_MATCH {
                        found.extend([open, close]);
                    }
                }
            }
        }
        if self.facts.extra[node as usize].expression_level {
            return found;
        }
        for &token in self.own_tokens(node) {
            if self.tokens[token as usize].kind == TokenKind::Ident
                && matches!(self.text(text, token), "do" | "then")
            {
                found.push(token);
            }
        }
        found.sort_unstable();
        found
    }

    fn token_at(&self, pos: Pos) -> u32 {
        self.find_start(pos)
            .unwrap_or_else(|| self.tokens.partition_point(|token| token.start < pos) as u32)
    }

    fn text<'a>(&self, text: &'a str, index: u32) -> &'a str {
        let token = &self.tokens[index as usize];
        &text[token.start_byte as usize..token.end_byte as usize]
    }

    fn base_span(&mut self, text: &str, node: usize, kid_spans: &[Span]) -> Option<Span> {
        let rule = self.facts.class[node].base;
        let (start, end) = self.facts.loc[node];
        if rule == BaseRule::Leaf {
            if start.line == 0 {
                return None;
            }
            let first = self.token_at(start);
            return (self.tokens.get(first as usize)?.kind != TokenKind::Eof)
                .then_some((first, first));
        }
        if rule == BaseRule::Block {
            let parent = self.facts.parent[node];
            let curly = self.facts.curly[node].or_else(|| {
                (parent != NO_NODE && self.facts.class[parent as usize].body_owner)
                    .then(|| self.facts.curly[parent as usize])
                    .flatten()
            });
            let span = if let Some((open, close)) = curly {
                self.span(open, close)
            } else {
                self.span(start, end).and_then(|(_, last)| {
                    let partner = self.tokens[last as usize].partner;
                    (self.text(text, last) == "}"
                        && partner != NO_MATCH
                        && !kid_spans.iter().any(|&(a, b)| a <= partner && partner <= b))
                    .then_some((partner, last))
                })
            };
            self.from_curly[node] = span.is_some();
            return span;
        }
        if rule == BaseRule::AttrGroup {
            let parent = self.facts.parent[node];
            if parent == NO_NODE {
                return None;
            }
            let ends: HashMap<u32, u32> = kid_spans.iter().map(|&(a, b)| (b, a)).collect();
            let start = self.token_at(self.facts.loc[parent as usize].0);
            let mut first = start;
            while let Some(previous) = self.prev_code(first) {
                let token = &self.tokens[previous as usize];
                if let Some(&begin) = ends.get(&previous) {
                    first = begin;
                } else if token.kind == TokenKind::String {
                    let Some(pragma) = self.prev_code(previous) else {
                        break;
                    };
                    if self.text(text, pragma) != "pragma" {
                        break;
                    }
                    first = pragma;
                } else {
                    break;
                }
            }
            return (first != start).then(|| (first, self.prev_code(start).unwrap()));
        }
        if rule == BaseRule::ArrayRow {
            return None;
        }
        if rule == BaseRule::Module && self.facts.extra[node].implicit_module {
            return (self.tokens.len() > 1).then_some((0, self.tokens.len() as u32 - 2));
        }
        if rule == BaseRule::Formal
            && kid_spans.is_empty()
            && self.facts.extra[node].implicit_formal
        {
            return None;
        }
        let (first, mut last) = self.span(start, end)?;
        if rule == BaseRule::Signature || self.sig_ends.contains(&end) {
            self.sig_ends.insert(end);
            last = self
                .prev_code(last)
                .filter(|&index| index != 0)
                .unwrap_or(first);
        }
        if rule == BaseRule::Attribute {
            loop {
                let dot = self.next_code(last);
                if self.text(text, dot) != "." {
                    break;
                }
                let part = self.next_code(dot);
                if self.tokens[part as usize].kind != TokenKind::Ident {
                    break;
                }
                last = part;
            }
            let open = self.next_code(last);
            if self.text(text, open) == "(" {
                last = self.tokens[open as usize].partner;
                assert_ne!(last, NO_MATCH);
            }
        } else if rule == BaseRule::New && !kid_spans.is_empty() {
            last = kid_spans.iter().map(|span| span.1).max().unwrap();
            loop {
                let close = self.next_code(last);
                let token = &self.tokens[close as usize];
                if self.text(text, close) != ")"
                    || token.partner == NO_MATCH
                    || token.partner < first
                {
                    break;
                }
                last = close;
            }
        }
        Some((first, last))
    }

    fn compute_spans(&mut self, text: &str) {
        for node in (0..self.facts.class.len()).rev() {
            let (start, end) = self.facts.kid_range[node];
            let kids = &self.facts.kids[start as usize..end as usize];
            let kid_spans: Vec<Span> = kids.iter().filter_map(|&kid| self.node_span(kid)).collect();
            let mut own_kids: Vec<NodeId> = kids
                .iter()
                .copied()
                .filter(|&kid| self.node_span(kid).is_some())
                .collect();
            let base = self.base_span(text, node, &kid_spans);
            self.spans[node] = kid_spans
                .iter()
                .copied()
                .chain(base)
                .reduce(|(a, b), (c, d)| (a.min(c), b.max(d)));
            own_kids.sort_by_key(|&kid| self.node_span(kid));
            self.src_kids[node] = own_kids;
        }
    }

    fn compute_ownership(&mut self) {
        for node in 0..self.facts.class.len() {
            let Some((first, last)) = self.spans[node] else {
                continue;
            };
            let mut cursor = first;
            let mut previous: Option<NodeId> = None;
            for &kid in &self.src_kids[node] {
                let (begin, end) = self.spans[kid as usize].unwrap();
                if let Some(prev) = previous {
                    if begin <= self.spans[prev as usize].unwrap().1 {
                        self.problems.push((kid, prev));
                    }
                }
                for token in cursor..begin {
                    self.own[node].push(token);
                    self.owner[token as usize] = node as u32;
                }
                cursor = cursor.max(end + 1);
                previous = Some(kid);
            }
            for token in cursor..=last {
                self.own[node].push(token);
                self.owner[token as usize] = node as u32;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lexer::scan::lex;

    fn pos(col: u32) -> Pos {
        Pos { line: 1, col }
    }

    #[test]
    fn locations_and_ownership() {
        let text = "var x = 1;";
        let tokens = lex(text, &[]).unwrap().toks;
        let facts = AstFacts {
            class: vec![
                NodeClass {
                    base: BaseRule::Module,
                    ..NodeClass::default()
                },
                NodeClass::default(),
                NodeClass {
                    base: BaseRule::Leaf,
                    ..NodeClass::default()
                },
                NodeClass {
                    base: BaseRule::Leaf,
                    ..NodeClass::default()
                },
            ],
            parent: vec![NO_NODE, 0, 1, 1],
            kids: vec![1, 2, 3],
            kid_range: vec![(0, 1), (1, 3), (3, 3), (3, 3)],
            loc: vec![
                (pos(0), pos(0)),
                (pos(1), pos(10)),
                (pos(5), pos(6)),
                (pos(9), pos(10)),
            ],
            curly: vec![None; 4],
            extra: vec![
                Extra {
                    implicit_module: true,
                    ..Extra::default()
                },
                Extra::default(),
                Extra::default(),
                Extra::default(),
            ],
        };
        let index = TokenIndex::new(text, tokens, facts);
        assert_eq!(index.find_start(pos(5)), Some(1));
        assert_eq!(index.find_end(pos(4)), Some(0));
        assert_eq!(index.find_end(pos(12)), None);
        assert_eq!(index.span(pos(2), pos(10)), Some((1, 3)));
        assert_eq!(index.span(pos(1), pos(1)), None);
        assert_eq!(index.node_span(0), Some((0, 4)));
        assert_eq!(index.node_span(1), Some((0, 3)));
        assert_eq!(index.own_tokens(1), &[0, 2]);
        assert_eq!(index.owner(1), 2);
        assert_eq!(index.owner(4), 0);
        assert_eq!(index.owner(5), NO_NODE);
        assert_eq!(index.children(1), &[2, 3]);
        assert!(index.problems.is_empty());
    }
}
