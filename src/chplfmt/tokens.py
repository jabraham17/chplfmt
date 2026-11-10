"""Map dyno AST nodes to tokens: spans, ownership, and brackets (design section 7.4).

All knowledge of dyno's span quirks lives here. A node's span is a pair of
inclusive token indices `(first, last)`, computed from its location, fixed
for the quirks below, and widened to cover its children.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator, Sequence
from functools import cache
from typing import cast

from chplfmt._chapel import chapel
from chplfmt.lexer import OPEN_BRACKETS, Token, TokenKind, tokenize
from chplfmt.source import Pos, SourceText

Span = tuple[int, int]
Node = chapel.AstNode

_LEAVES = (chapel.Identifier, chapel.Literal)
# Their body Block reports neither its own braces nor a sane location.
_BODY_OWNERS = (chapel.Function, chapel.When, chapel.Loop)
_FIRST_PAREN = (
    chapel.Tuple,
    chapel.TupleDecl,
    chapel.Zip,
    chapel.WithClause,
    chapel.PrimCall,
    chapel.Attribute,
    chapel.FunctionSignature,
)

_LEAF, _BLOCK, _ATTR_GROUP, _ARRAY_ROW, _MODULE, _FORMAL = range(6)
_SIGNATURE, _ATTRIBUTE, _NEW, _OTHER = range(6, 10)
_CATEGORIES: tuple[tuple[int, type | tuple[type, ...]], ...] = (
    (_LEAF, _LEAVES),
    (_BLOCK, chapel.Block),
    (_ATTR_GROUP, chapel.AttributeGroup),
    (_ARRAY_ROW, chapel.ArrayRow),
    (_MODULE, chapel.Module),
    (_FORMAL, chapel.Formal),
    (_SIGNATURE, chapel.FunctionSignature),
    (_ATTRIBUTE, chapel.Attribute),
    (_NEW, chapel.New),
)


@cache
def _category(cls: type) -> int:
    """Which `_base_span` case applies to nodes of class `cls`."""
    return next((k for k, c in _CATEGORIES if issubclass(cls, c)), _OTHER)


def opaque_ranges(source: SourceText, asts: Iterable[Node]) -> list[tuple[int, int]]:
    """Offsets of every `ExternBlock` (`extern { ... }`), for the lexer."""
    return _opaque_ranges(source, _walk(asts)[0])


def _opaque_ranges(
    source: SourceText, order: list[tuple[Node, Node | None]]
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for node, _ in order:
        if isinstance(node, chapel.ExternBlock):
            loc = node.location()
            ranges.append((source.offset(loc.start()), source.offset(loc.end())))
    return ranges


def children(node: Node) -> list[Node]:
    """The node's children without `Comment` nodes (which have no location)."""
    return [c for c in node if not isinstance(c, chapel.Comment)]


_Walk = tuple[list[tuple[Node, Node | None]], dict[Node, list[Node]]]


def _walk(roots: Iterable[Node]) -> _Walk:
    """`(node, parent)` in preorder, and each node's `children`."""
    comment = chapel.Comment
    order: list[tuple[Node, Node | None]] = []
    kids: dict[Node, list[Node]] = {}
    stack: list[tuple[Node, Node | None]] = [(r, None) for r in reversed(list(roots))]
    while stack:
        item = stack.pop()
        order.append(item)
        node = item[0]
        ks = [c for c in node if not isinstance(c, comment)]
        kids[node] = ks
        stack.extend([(c, node) for c in reversed(ks)])
    return order, kids


class TokenIndex:
    """Tokens of one file joined to its AST."""

    def __init__(
        self,
        source: SourceText,
        tokens: Sequence[Token],
        asts: Iterable[Node],
        *,
        walk: _Walk | None = None,
    ):
        self.source = source
        self.tokens: list[Token] = list(tokens)
        self.roots: list[Node] = list(asts)
        self._order, self._ast_kids = walk or _walk(self.roots)
        self.by_start: dict[Pos, int] = {t.start: i for i, t in enumerate(self.tokens)}
        self.by_end: dict[Pos, int] = {}
        for i, t in enumerate(self.tokens):
            if t.kind is not TokenKind.EOF:
                self.by_end[t.end] = i
        self._starts = [t.start for t in self.tokens]
        self._ends = [t.end for t in self.tokens]
        self._spans: dict[Node, Span | None] = {}
        self._from_curly: set[Node] = set()
        self._sig_ends: set[Pos] = set()
        self._parent: dict[Node, Node | None] = {}
        self._kids: dict[Node, list[Node]] = {}
        self._own: dict[Node, list[int]] = {}
        self._owner: list[Node | None] = [None] * len(self.tokens)
        self._structural: dict[Node, list[int]] = {}
        self._user_parens: dict[Node, list[tuple[int, int, Node]]] = {}
        self._parens_around: dict[Node, list[tuple[int, int]]] = {}
        # Spans that couldn't be reconciled (overlapping siblings); empty normally.
        self.problems: list[str] = []
        self._compute_spans()
        self._compute_ownership()

    @classmethod
    def build(cls, source: SourceText, asts: Sequence[Node]) -> TokenIndex:
        """Tokenize `source` (with its extern blocks opaque) and index it."""
        walk = _walk(asts)
        tokens = tokenize(source, _opaque_ranges(source, walk[0]))
        return cls(source, tokens, asts, walk=walk)

    # Location lookup

    def span(self, loc: chapel.Location | tuple[Pos, Pos]) -> Span | None:
        """Tokens covered by a location: exact lookup, else the tokens inside it."""
        start, end = (
            (loc.start(), loc.end()) if isinstance(loc, chapel.Location) else loc
        )
        if start[0] < 1 or start >= end:
            return None
        first = self.by_start.get(start)
        if first is None:
            first = bisect_left(self._starts, start)
        last = self.by_end.get(end)
        if last is None:
            last = bisect_right(self._ends, end) - 1
        if first > last or self.tokens[first].kind is TokenKind.EOF:
            return None
        return first, last

    def _token_at(self, pos: Pos) -> int:
        i = self.by_start.get(pos)
        return bisect_left(self._starts, pos) if i is None else i

    def next_code(self, i: int) -> int:
        """Index of the first non-comment token after `i` (EOF at the end)."""
        i += 1
        while self.tokens[i].is_comment:
            i += 1
        return i

    def prev_code(self, i: int) -> int | None:
        """Index of the last non-comment token before `i`."""
        i -= 1
        while i >= 0 and self.tokens[i].is_comment:
            i -= 1
        return i if i >= 0 else None

    # Spans

    def _base_span(
        self, node: Node, parent: Node | None, kid_spans: list[Span]
    ) -> Span | None:
        cat = _category(type(node))
        loc = node.location()
        start = loc.start()
        if cat == _LEAF:
            # A leaf is one token. `owned C?` and `domain(2)` report the called
            # Identifier with the whole call's location.
            if start[0] < 1:
                return None
            i = self._token_at(start)
            return (i, i) if self.tokens[i].kind is not TokenKind.EOF else None
        if cat == _BLOCK:
            return self._block_span(cast(chapel.Block, node), parent, kid_spans)
        if cat in (_ATTR_GROUP, _ARRAY_ROW):
            # AttributeGroup reports the start of the declaration; the first
            # ArrayRow of a multi-dimensional literal reports the whole array.
            if cat == _ATTR_GROUP and parent is not None:
                return self._attribute_group_span(parent, kid_spans)
            return None
        if cat == _MODULE and cast(chapel.Module, node).kind() == "implicit":
            # An implicit module's location is empty; it owns the whole file.
            return (0, len(self.tokens) - 2) if len(self.tokens) > 1 else None
        # An implicit `this` reports the method name's location; an
        # interface's implicit `Self` reports the whole interface.
        if (
            cat == _FORMAL
            and not kid_spans
            and (
                (formal := cast(chapel.Formal, node)).is_this()
                or formal.name_location().start()[0] < 1
            )
        ):
            return None
        end = loc.end()
        sp = self.span((start, end))
        if sp is None:
            return None
        first, last = sp
        if cat == _SIGNATURE or end in self._sig_ends:
            # `proc(): int` reports one token too many (`;`, `,`, `)`, `=`, `{`),
            # and so does a parent ending with it, e.g. a Formal or Variable.
            self._sig_ends.add(end)
            last = self.prev_code(last) or first
        if cat == _ATTRIBUTE:
            # Attribute locations cover only `@name`; add `.part`s and `(...)`.
            while (
                self.tokens[n := self.next_code(last)].text == "."
                and self.tokens[m := self.next_code(n)].kind is TokenKind.IDENT
            ):
                last = m
            if self.tokens[n := self.next_code(last)].text == "(":
                last = self._match(n)
        elif cat == _NEW and kid_spans:
            # `new C(1)` reports New with the whole FnCall's location.
            last = self._close_parens(first, max(s[1] for s in kid_spans))
        return first, last

    def _block_span(
        self, node: chapel.Block, parent: Node | None, kid_spans: list[Span]
    ) -> Span | None:
        # A function, loop, or `when` body Block reports the whole statement;
        # only braces are reliable. A brace-less Block is just its statements.
        curly = node.curly_braces_location()
        if curly is None and isinstance(parent, _BODY_OWNERS):
            curly = parent.curly_braces_location()
        if curly is not None:
            sp = self.span(curly)
        else:
            # Standalone `{ }` statements and lambda bodies report no braces.
            sp = self.span(node.location())
            if sp is not None:
                last = sp[1]
                open_ = self.tokens[last].match
                if self.tokens[last].text != "}" or open_ is None:
                    return None
                if any(s[0] <= open_ <= s[1] for s in kid_spans):
                    return None  # the `}` closes the last statement
                sp = (open_, last)
        if sp is not None:
            self._from_curly.add(node)
        return sp

    def _match(self, i: int) -> int:
        match = self.tokens[i].match
        assert match is not None
        return match

    def _close_parens(self, first: int, last: int) -> int:
        """Extend `last` over `)` tokens whose `(` lies in `first..last`."""
        while True:
            n = self.next_code(last)
            tok = self.tokens[n]
            if tok.text != ")" or tok.match is None or tok.match < first:
                return last
            last = n

    def _compute_spans(self) -> None:
        order = self._order
        for node, parent in order:
            self._parent[node] = parent
        spans = self._spans
        for node, parent in reversed(order):
            kids = self._ast_kids[node]
            if not kids:
                spans[node] = self._base_span(node, parent, [])
                self._kids[node] = []
                continue
            kid_spans = [s for k in kids if (s := spans[k]) is not None]
            base = self._base_span(node, parent, kid_spans)
            if base is not None:
                kid_spans.append(base)
            spans[node] = (
                (min(s[0] for s in kid_spans), max(s[1] for s in kid_spans))
                if kid_spans
                else None
            )
            own_kids = [k for k in kids if spans[k] is not None]
            if len(own_kids) > 1:
                own_kids.sort(key=lambda k: spans[k] or (0, 0))
            self._kids[node] = own_kids

    def _attribute_group_span(self, decl: Node, kid_spans: list[Span]) -> Span | None:
        # Pragmas aren't nodes: walk back from the declaration over
        # `pragma "..."` pairs and the attributes.
        ends = {s[1]: s[0] for s in kid_spans}
        start = self._token_at(decl.location().start())
        first = start
        while (j := self.prev_code(first)) is not None:
            tok = self.tokens[j]
            if j in ends:
                first = ends[j]
            elif tok.kind is TokenKind.STRING and (p := self.prev_code(j)) is not None:
                if self.tokens[p].text != "pragma":
                    break
                first = p
            else:
                break
        if first == start:
            return None
        last = self.prev_code(start)
        assert last is not None
        return first, last

    def node_span(self, node: Node) -> Span | None:
        """Every token of the node, including its children and attributes."""
        return self._spans.get(node)

    def header_span(self, node: Node) -> Span | None:
        """The declaration or statement header (no `where`/`with` clauses, no body)."""
        if isinstance(node, chapel.BracketLoop):
            # header_location() is the inside of `[...]`; include the brackets.
            opens = self.structural_brackets(node)
            if opens:
                close = self.tokens[opens[0]].match
                assert close is not None
                return opens[0], close
        loc: chapel.Location | None = None
        if isinstance(node, (chapel.NamedDecl, chapel.Loop)):
            loc = node.header_location()
        if loc is None:
            loc = node.block_header()
        if loc is None or (sp := self.span(loc)) is None:
            return None
        if loc.end() in self._sig_ends:
            # `proc f(): proc(): int {` ends at the `{` (see FunctionSignature).
            return sp[0], self.prev_code(sp[1]) or sp[0]
        return sp

    def body_span(self, node: Node) -> Span | None:
        """The body: `{ ... }` when braced, else its statements (after `do`/`then`)."""
        body: Node | None = None
        if isinstance(node, chapel.Block):
            body = node
        elif isinstance(
            node, (chapel.Function, chapel.When, chapel.Catch, chapel.Try, chapel.Loop)
        ):
            body = node.body()
        if body is not None:
            return self.node_span(body)
        curly = node.curly_braces_location()
        if curly is not None:
            return self.span(curly)
        if isinstance(node, chapel.SimpleBlockLike):
            spans = [s for s in map(self.node_span, node.stmts()) if s is not None]
            if spans:
                return spans[0][0], spans[-1][1]
        return None

    def stmt_span(self, node: Node) -> Span | None:
        """`node_span` plus the terminating `;` when dyno leaves it out.

        Return/Yield/Break/Continue/Throw/Delete/Init, use/import/require,
        assignments, bodyless functions, and implicit-block statements already
        include it; Variable, MultiDecl, TupleDecl, and FnCall don't.
        """
        sp = self.node_span(node)
        if sp is None:
            return None
        n = self.next_code(sp[1])
        tok = self.tokens[n]
        if (
            tok.kind is TokenKind.PUNCT
            and tok.text == ";"
            and not isinstance(self._owner[n], chapel.EmptyStmt)
        ):
            return sp[0], n
        return sp

    # Ownership

    def _compute_ownership(self) -> None:
        owner = self._owner
        for node, _ in self._order:
            sp = self._spans[node]
            own: list[int] = []
            self._own[node] = own
            if sp is None:
                continue
            i = sp[0]
            prev: tuple[Node, Span] | None = None
            for kid in self._kids[node]:
                ks = self._spans[kid]
                assert ks is not None
                if prev is not None and ks[0] <= prev[1][1]:
                    self.problems.append(
                        f"{kid.tag()} at {kid.location().start()} overlaps "
                        f"{prev[0].tag()} at {prev[0].location().start()}"
                    )
                if i < ks[0]:
                    own.extend(range(i, ks[0]))
                    owner[i : ks[0]] = [node] * (ks[0] - i)
                i = max(i, ks[1] + 1)
                prev = (kid, ks)
            if i <= sp[1]:
                own.extend(range(i, sp[1] + 1))
                owner[i : sp[1] + 1] = [node] * (sp[1] + 1 - i)

    def owner(self, i: int) -> Node | None:
        """The deepest node whose span contains token `i` (None outside every node).

        Comment tokens are owned the same way (so a comment before an explicit
        `module M { }` has no owner); trivia attaches them separately.
        """
        return self._owner[i]

    def own_tokens(self, node: Node) -> list[int]:
        """Tokens of `node` that belong to none of its children."""
        return self._own.get(node, [])

    def children(self, node: Node) -> list[Node]:
        """Children that have tokens, in source order."""
        return self._kids.get(node, [])

    def ast_children(self, node: Node) -> list[Node]:
        """All children except comments, in AST order (cached `children(node)`)."""
        kids = self._ast_kids.get(node)
        return children(node) if kids is None else kids

    def parent(self, node: Node) -> Node | None:
        return self._parent.get(node)

    def nodes(self) -> Iterator[Node]:
        """Every node except comments, in preorder."""
        return iter(self._parent)

    # Brackets

    def _first_own(self, node: Node, texts: str, after: int = -1) -> list[int]:
        for i in self.own_tokens(node):
            tok = self.tokens[i]
            if i > after and tok.kind is TokenKind.PUNCT and tok.text in texts:
                return [i]
        return []

    def structural_brackets(self, node: Node) -> list[int]:
        """Opening brackets that are part of the node's syntax, e.g. call parens."""
        cached = self._structural.get(node)
        if cached is not None:
            return cached
        found: list[int] = []
        if isinstance(node, chapel.FnCall):
            called = self.node_span(node.called_expression())
            if called is not None:
                found = self._first_own(node, "([", called[1])
            if found and self.tokens[found[0]].text == "(":
                # `owned (C)` has no call parens: the parens are C's own.
                i, j = found[0], self._match(found[0])
                inside = [k for k in self.children(node) if i < self._span_of(k)[0] < j]
                if len(inside) == 1:
                    paren = inside[0].paren_location()
                    if paren is not None and self.span(paren) == (i, j):
                        found = []
        elif isinstance(node, _FIRST_PAREN):
            found = self._first_own(node, "(")
        elif isinstance(node, chapel.OpCall) and node.op() == "...":
            found = self._first_own(node, "(")  # tuple expansion `(...t)`
        elif isinstance(node, chapel.Catch):
            if node.has_parens_around_error():
                found = self._first_own(node, "(")
        elif isinstance(node, (chapel.Array, chapel.BracketLoop)):
            found = self._first_own(node, "[")
        elif isinstance(node, chapel.Domain):
            found = self._first_own(node, "{" if node.used_curly_braces() else "[")
        elif isinstance(node, chapel.VisibilityClause):
            found = self._first_own(node, "{")
        elif isinstance(node, chapel.Function):
            if not node.is_parenless():
                name = self.span(node.name_location())
                found = self._first_own(node, "(", (name[0] - 1) if name else -1)
        elif isinstance(node, chapel.Interface) and node.is_formal_list_explicit():
            found = self._first_own(node, "(")
        if isinstance(node, chapel.Block):
            sp = self._spans.get(node)
            if node in self._from_curly and sp is not None:
                found.append(sp[0])
        else:
            curly = node.curly_braces_location()
            sp = None if curly is None else self.span(curly)
            if sp is not None and self._owner[sp[0]] == node:
                found.append(sp[0])
        self._structural[node] = found
        return found

    def user_parens(self, node: Node) -> list[tuple[int, int, Node]]:
        """`(`...`)` pairs owned by `node` around exactly one child: `(open, close, child)`."""
        cached = self._user_parens.get(node)
        if cached is not None:
            return cached
        found: list[tuple[int, int, Node]] = []
        own = self.own_tokens(node)
        tokens = self.tokens
        if not any(tokens[i].text == "(" for i in own):
            self._user_parens[node] = found
            return found
        structural = set(self.structural_brackets(node))
        for i in own:
            tok = self.tokens[i]
            if tok.text != "(" or tok.kind is not TokenKind.PUNCT or i in structural:
                continue
            j = tok.match
            assert j is not None
            inside = [k for k in self.children(node) if i < self._span_of(k)[0] <= j]
            others = [
                t
                for t in own
                if i < t < j
                and not self.tokens[t].is_comment
                and self.tokens[t].text not in ("(", ")")
            ]
            if len(inside) == 1 and self._span_of(inside[0])[1] < j and not others:
                found.append((i, j, self._unwrap_implicit_block(inside[0])))
        self._user_parens[node] = found
        return found

    def _span_of(self, node: Node) -> Span:
        sp = self._spans[node]
        assert sp is not None
        return sp

    def _unwrap_implicit_block(self, node: Node) -> Node:
        # `[i in D] (e)`: the parens belong to `e`, not to the brace-less body Block.
        while isinstance(node, chapel.Block) and node not in self._from_curly:
            kids = self.children(node)
            if len(kids) != 1 or self._spans[kids[0]] != self._spans[node]:
                break
            node = kids[0]
        return node

    def parens_around(self, node: Node) -> list[tuple[int, int]]:
        """User parentheses around `node`, innermost first."""
        cached = self._parens_around.get(node)
        if cached is not None:
            return cached
        parent = self._parent.get(node)
        while isinstance(parent, chapel.Block) and parent not in self._from_curly:
            parent = self._parent.get(parent)
        if parent is None:
            return []
        layers = [(i, j) for i, j, kid in self.user_parens(parent) if kid == node]
        layers.sort(reverse=True)
        self._parens_around[node] = layers
        return layers

    def unexplained_brackets(self, node: Node) -> list[int]:
        """Own brackets that are neither structural nor user parentheses."""
        structural = set(self.structural_brackets(node))
        user = {i for i, _, _ in self.user_parens(node)}
        closes = {self.tokens[i].match for i in structural | user}
        bad: list[int] = []
        for i in self.own_tokens(node):
            tok = self.tokens[i]
            if tok.kind is not TokenKind.PUNCT or tok.match is None:
                continue
            if tok.text in OPEN_BRACKETS:
                if i not in structural and i not in user:
                    bad.append(i)
            elif i not in closes:
                bad.append(i)
        return bad

    def body_delimiters(self, node: Node) -> list[int]:
        """Own `{`/`}` of a body and own statement-level `do`/`then`, in order."""
        found: list[int] = []
        if not isinstance(node, (chapel.Domain, chapel.VisibilityClause)):
            for i in self.structural_brackets(node):
                tok = self.tokens[i]
                if tok.text == "{" and tok.match is not None:
                    found += [i, tok.match]
        if (
            isinstance(node, (chapel.Conditional, chapel.IndexableLoop))
            and node.is_expression_level()
        ):
            return found
        for i in self.own_tokens(node):
            tok = self.tokens[i]
            if tok.kind is TokenKind.IDENT and tok.text in ("do", "then"):
                found.append(i)
        return sorted(found)

    # Invariants

    def check_leaves(self) -> list[str]:
        """Every Identifier and literal is exactly one token with matching text."""
        problems: list[str] = []
        for node in self.nodes():
            if not isinstance(node, _LEAVES):
                continue
            loc = node.location()
            where = f"{node.tag()} at {loc.start()}"
            i = self.by_start.get(loc.start())
            if i is None:
                problems.append(f"{where}: no token starts there")
                continue
            tok = self.tokens[i]
            end = self.by_end.get(loc.end())
            if end != i and (end is None or not self.is_wide_identifier(node)):
                problems.append(
                    f"{where}: ends at {loc.end()}, token {tok.text!r} doesn't"
                )
            expected = _leaf_text(node)
            if isinstance(node, chapel.StringLikeLiteral):
                if tok.kind is not TokenKind.STRING or not _string_matches(
                    node, tok.text
                ):
                    problems.append(f"{where}: token {tok.text!r} doesn't match")
            elif expected is not None and tok.text != expected:
                problems.append(f"{where}: token {tok.text!r} != {expected!r}")
        return problems

    def check_ownership(self) -> list[str]:
        """Every code token is owned; brackets are owned in pairs and explained."""
        problems = list(self.problems)
        for i, tok in enumerate(self.tokens):
            if (
                self._owner[i] is None
                and not tok.is_comment
                and tok.kind is not TokenKind.EOF
            ):
                problems.append(f"token {tok.text!r} at {tok.start} has no owner")
            if tok.match is not None and self._owner[i] != self._owner[tok.match]:
                problems.append(
                    f"bracket {tok.text!r} at {tok.start} split across owners"
                )
        for node in self.nodes():
            for i in self.unexplained_brackets(node):
                tok = self.tokens[i]
                problems.append(
                    f"{node.tag()}: unexplained {tok.text!r} at {tok.start}"
                )
        return problems

    def is_wide_identifier(self, node: Node) -> bool:
        """Whether `node` is an Identifier whose location covers its whole call."""
        # Dyno quirk: in `owned C?`, `domain(2)`, `implements hashable(R)`, ...
        # the called Identifier has the whole call's location.
        parent = self.parent(node)
        if not isinstance(node, chapel.Identifier) or not isinstance(
            parent, chapel.FnCall
        ):
            return False
        loc, ploc = node.location(), parent.location()
        return parent.called_expression() == node and (loc.start(), loc.end()) == (
            ploc.start(),
            ploc.end(),
        )


def _leaf_text(node: Node) -> str | None:
    if isinstance(node, chapel.Identifier):
        return node.name()
    if isinstance(node, chapel.BoolLiteral):
        return "true" if node.value() else "false"
    if isinstance(
        node,
        (chapel.IntLiteral, chapel.UintLiteral, chapel.RealLiteral, chapel.ImagLiteral),
    ):
        return node.text()
    return None


_ESCAPES = {
    "'": "'",
    '"': '"',
    "?": "?",
    "\\": "\\",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\n": "\n",
}


def string_value(token_text: str) -> tuple[str, bytes]:
    """Decode a STRING token as dyno does: its quote style and value bytes."""
    body = token_text[1:] if token_text[0] == "b" else token_text
    quote = body[:3] if body[:3] in ('"""', "'''") else body[0]
    inner = body[len(quote) : -len(quote)]
    if len(quote) == 3:
        return quote, inner.encode("utf-8")
    out = bytearray()
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch != "\\":
            out += ch.encode("utf-8")
            i += 1
            continue
        esc = inner[i + 1]
        i += 2
        if esc == "x":
            digits = ""
            while (
                len(digits) < 2
                and i < len(inner)
                and inner[i] in "0123456789abcdefABCDEF"
            ):
                digits += inner[i]
                i += 1
            out.append(int(digits, 16))
        else:
            out += _ESCAPES[esc].encode("utf-8")
    return quote, bytes(out)


def _string_matches(node: chapel.StringLikeLiteral, text: str) -> bool:
    is_bytes = text[0] == "b"
    if is_bytes != isinstance(node, chapel.BytesLiteral):
        return False
    try:
        quote, value = string_value(text)
    except (KeyError, ValueError, IndexError):
        return False
    if quote != node.quote_style():
        return False
    try:
        return node.value().encode("utf-8") == value
    except UnicodeDecodeError:
        return True  # chapel-py can't return non-UTF-8 bytes values
