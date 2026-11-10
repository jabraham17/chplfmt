"""Bodies of constructs and the single-statement-body rule (sections 7.8, 8.3)."""

from __future__ import annotations

from typing import Literal

from chplfmt._chapel import chapel
from chplfmt.doc import (
    EMPTY,
    Doc,
    GroupId,
    concat,
    flat_width,
    group,
    hardline,
    if_break,
    indent,
    line,
    text,
)
from chplfmt.printer.common import attach_body, braced, ends_line
from chplfmt.printer.core import Printer
from chplfmt.tokens import Node
from chplfmt.trivia import Comment, Placement

RULE = "single-statement-body"

# Statements that may form a `do`/`then`/bare single-statement body.
SIMPLE = (
    chapel.Return,
    chapel.Yield,
    chapel.Break,
    chapel.Continue,
    chapel.Throw,
    chapel.Delete,
    chapel.Variable,
    chapel.MultiDecl,
    chapel.TupleDecl,
    chapel.Call,
    chapel.Identifier,
    chapel.Dot,
    chapel.New,
    chapel.Literal,
    chapel.EmptyStmt,
)

type Form = Literal["keyword", "bare", "block"]
type Kind = Literal["braces", "keyword", "bare"]


def fits(p: Printer, width: int | None, col: int | None = None) -> bool:
    """Whether `width` columns fit from `col` (default: the statement indentation)."""
    limit = p.options.line_length
    return width is not None and (
        not limit or (p.indent if col is None else col) + width <= limit
    )


def _breaks(cs: list[Comment]) -> bool:
    return bool(cs) and (cs[-1].is_line or cs[-1].placement is Placement.OWN_LINE)


class Body:
    """The body of `owner` after its header, which ends at token `header_last`.

    `block` is the node holding the body statements (a `Block` child, e.g. of
    a Function, When, Catch), or `owner` itself for `begin`/`on`/... (the
    default). `form` is the construct's single-statement form: `keyword`
    (`do S;`, `then S;`), `bare` (`begin S;`), or `block` (braces only, e.g.
    `cobegin`, `try`). `kw_tok` overrides the search for `keyword` among the
    owner's tokens. `mode` overrides the `single-statement-body` option.

    Analysis prints nothing; `kind` may print the statement (once) to measure
    it. Build the header Doc before calling `doc`.
    """

    def __init__(
        self,
        p: Printer,
        owner: Node,
        header_last: int,
        *,
        block: Node | None = None,
        form: Form = "keyword",
        keyword: str = "do",
        kw_tok: int | None = None,
        mode: str | None = None,
    ) -> None:
        self.p = p
        self.owner = owner
        self.block = owner if block is None else block
        self.header_last = header_last
        self.form = form
        self.keyword = keyword
        self.mode = p.options.single_statement_body if mode is None else mode
        tokens = p.tokens
        braces = [
            i
            for i in p.index.structural_brackets(self.block)
            if i > header_last and tokens[i].text == "{"
        ]
        self.open_tok = braces[0] if braces else None
        # dyno merges `{ { ... } }` in a function body into one Block.
        self.nested_braces = self.block is not owner and (
            sum(tokens[i].text == "{" for i in p.index.own_tokens(self.block)) > 1
        )
        if kw_tok is None and form == "keyword":
            kw_tok = next(
                (
                    i
                    for i in p.index.own_tokens(owner)
                    if i > header_last
                    and tokens[i].text == keyword
                    and (self.open_tok is None or i < self.open_tok)
                ),
                None,
            )
        self.kw_tok = kw_tok
        start = max(header_last, kw_tok or -1, self.open_tok or -1)
        self.stmts: list[Node] = []
        for k in p.index.children(self.block):
            sp = p.index.node_span(k)
            if sp is not None and sp[0] > start:
                self.stmts.append(k)
        self.close = None if self.open_tok is None else tokens[self.open_tok].match
        # Statements printed in the single-statement form.
        self.single_stmts = self.stmts
        if self.close is not None and p.options.remove_empty_statements:
            self.single_stmts = [
                s for s in self.stmts if not isinstance(s, chapel.EmptyStmt)
            ]
        self.last = self._last()
        self.semi = (
            self.close is None
            and tokens[self.last].text == ";"
            and p.index.owner(self.last) in (owner, self.block)
            and not any(self._covers(s, self.last) for s in self.stmts)
        )
        cands = p.dangling(owner)
        if self.block is not owner:
            cands += p.dangling(self.block)
            cands += p.unemitted(p.trivia.leading(self.block))
        self.pre = sorted(
            {c.token: c for c in cands if header_last < c.token < self.last}.values(),
            key=lambda c: c.token,
        )
        self.source: Kind = (
            "braces"
            if self.open_tok is not None
            else "keyword"
            if kw_tok is not None
            else "bare"
        )
        self._stmt: tuple[Doc, Doc] | None = None
        self._kind: Kind | None = None

    def _covers(self, stmt: Node, tok: int) -> bool:
        sp = self.p.span(stmt)
        return sp is not None and sp[0] <= tok <= sp[1]

    def _last(self) -> int:
        p = self.p
        if self.close is not None:
            return self.close
        end = self.kw_tok if self.kw_tok is not None else self.header_last
        for s in self.stmts:
            sp = p.span(s)
            if sp is not None:
                end = max(end, sp[1])
        n = p.index.next_code(end)
        if (
            n < len(p.tokens)
            and p.tokens[n].text == ";"
            and p.index.owner(n) in (self.owner, self.block)
        ):
            end = n
        return end

    @property
    def qualifies(self) -> bool:
        """Whether the body may use the single-statement form (prefer-single-line)."""
        p = self.p
        if self.form == "block" or self.nested_braces or len(self.single_stmts) != 1:
            return False
        if not isinstance(self.single_stmts[0], SIMPLE):
            return False
        lo, hi = self.header_last, self.last
        if any(p.tokens[i].is_comment for i in range(lo + 1, hi)):
            return False
        sp = p.index.node_span(self.single_stmts[0])
        if sp is not None and any(
            "\n" in p.tokens[i].text for i in range(sp[0], sp[1] + 1)
        ):
            return False
        return not any(lo < r.off_token < hi for r in p.off.regions) and not (
            sp is not None and p.off.contains(p.tokens[sp[0]].start_offset)
        )

    def statement(self) -> tuple[Doc, Doc]:
        """The single-statement body (with `;`) and the last statement's trailing comments."""
        if self._stmt is None:
            p = self.p
            stmts = self.single_stmts
            for s in self.stmts:
                if s not in stmts and (sp := p.index.node_span(s)) is not None:
                    p.record("remove-empty-statements", sp[0])
            with p.nested() as n:
                last = len(stmts) - 1
                d = concat(
                    *(p.print(s, trailing=k < last) for k, s in enumerate(stmts))
                )
                if self.semi:
                    d = concat(d, ";")
                trail = indent(p.trailing_comments(stmts[-1]), n) if stmts else EMPTY
            self._stmt = (d, trail)
        return self._stmt

    def _block_trail(self) -> Doc:
        if self.block is self.owner:
            return EMPTY
        return self.p.trailing_comments(self.block)

    def single_width(self) -> int | None:
        """Flat width of the single-statement body, if it has one."""
        return flat_width(self.statement()[0], self.p.options)

    @property
    def kind(self) -> Kind:
        """The output form: braces, or the keyword/bare single-statement form."""
        if self._kind is None:
            self._kind = self._decide()
        return self._kind

    def _decide(self) -> Kind:
        single: Kind = "keyword" if self.form == "keyword" else "bare"
        if self.form == "block":
            return "braces"
        if self.mode == "preserve":
            return self.source
        if self.mode == "prefer-braces" or not self.qualifies:
            return "braces"
        if self.form == "keyword":
            col = self.p.indent + self.p.options.indent_width
            return single if fits(self.p, self.single_width(), col) else "braces"
        # Bare: decided in `doc`, which knows the header's width.
        return single

    def _record(self) -> None:
        tok = self.kw_tok if self.kw_tok is not None else self.open_tok
        if tok is None:
            sp = self.p.index.node_span(self.stmts[0]) if self.stmts else None
            tok = self.header_last if sp is None else sp[0]
        self.p.record(RULE, tok)

    def doc(self, header: Doc, header_broke: bool = False) -> Doc:
        """`header` followed by the body in the chosen form.

        `header_broke`: the header ends with an own-line `//` comment and its
        line break.
        """
        kind = self.kind
        if kind == "bare" and self.mode != "preserve":
            d, _ = self.statement()
            w = flat_width(concat(header, " ", d), self.p.options)
            if header_broke or not fits(self.p, w):
                kind = "braces"
        if kind == "braces":
            return self.braces(header, header_broke)
        return self.single(header, header_broke, kind)

    def _split(self, at: int | None) -> tuple[list[Comment], list[Comment]]:
        if at is None:
            return [], self.pre
        return [c for c in self.pre if c.token < at], [
            c for c in self.pre if c.token > at
        ]

    def _with_comments(
        self, header: Doc, broke: bool, cs: list[Comment]
    ) -> tuple[Doc, bool]:
        if not cs:
            return header, broke
        header = concat(header, self.p.comments_after(cs))
        if ends_line(cs):
            return concat(header, hardline), True
        return header, broke

    def braces(self, header: Doc, header_broke: bool = False) -> Doc:
        """`header {` + statements + `}` (`brace-style` applies)."""
        p = self.p
        changed = self.source != "braces" or (
            self.kw_tok is not None and self.mode != "preserve"
        )
        if changed and self.form != "block":
            self._record()
        if self.source == "braces":
            before, after = self._split(self.open_tok)
            if self.block is not self.owner:
                after = []
        else:
            before, after = self._split(self.kw_tok)
        header, broke = self._with_comments(header, header_broke, before)
        if (
            self.kw_tok is not None
            and self.source == "braces"
            and self.mode == "preserve"
        ):
            header = concat(header, self.keyword if broke else f" {self.keyword}")
            broke = False
        only_empty = (
            self.source != "braces"
            and p.options.remove_empty_statements
            and all(isinstance(s, chapel.EmptyStmt) for s in self.stmts)
        )
        if self._stmt is not None and not only_empty:
            d, trail = self._stmt
            with p.nested() as n:
                inner = concat(p.comments_after(after, first_blank=False), hardline, d)
            body = concat(
                "{", indent(inner, n), trail, hardline, "}", self._block_trail()
            )
        elif self.source == "braces" and self.block is not self.owner:
            body = p.print(self.block, leading=False)
        elif self.source == "braces":
            assert self.open_tok is not None
            body = braced(p, self.owner, self.open_tok, self.stmts, after_open=after)
        else:
            body = self._convert(after)
        return attach_body(p, header, body, header_ends_line=broke)

    def _convert(self, after: list[Comment]) -> Doc:
        """Braces around a keyword or bare body."""
        p = self.p
        stmts = self.stmts
        if (
            not after
            and p.options.remove_empty_statements
            and all(isinstance(s, chapel.EmptyStmt) for s in stmts)
            and not any(p.trivia.leading(s) or p.trivia.trailing(s) for s in stmts)
        ):
            for s in stmts:
                sp = p.index.node_span(s)
                if sp is not None:
                    p.record("remove-empty-statements", sp[0])
            return concat("{ }", self._block_trail())
        first = (self.kw_tok if self.kw_tok is not None else self.header_last) + 1
        with p.nested() as n:
            inner = concat(
                p.comments_after(after, first_blank=False),
                hardline,
                p.statement_list(stmts, first, self.last + 1),
            )
        return concat("{", indent(inner, n), hardline, "}", self._block_trail())

    def single(
        self, header: Doc, header_broke: bool = False, kind: Kind | None = None
    ) -> Doc:
        """The keyword (`header do S;`) or bare (`header S;`) form."""
        p = self.p
        kind = kind or ("keyword" if self.form == "keyword" else "bare")
        if self.source == "braces" or (self.source == "bare" and kind == "keyword"):
            self._record()
        d, trail = self.statement()
        trail = concat(trail, self._block_trail())
        n = p.options.indent_width
        lead = p.trivia.leading(self.single_stmts[0]) if self.single_stmts else []
        if kind == "keyword":
            before, after = self._split(self.kw_tok)
            hid = GroupId("header")
            h, broke = self._with_comments(group(header, hid), header_broke, before)
            h = concat(h, self.keyword if broke else f" {self.keyword}")
        else:
            hid = None
            h, after = header, self.pre
            broke = header_broke
        if after:
            sep: Doc = hardline if _breaks(after) else text(" ")
            stmt = concat(p.comments_after(after, first_blank=False), sep, d)
            return concat(h, indent(stmt, n), trail)
        if lead and lead[0].is_line and lead[0].placement is Placement.END_OF_LINE:
            return concat(h, indent(d, n), trail)
        if broke or (lead and lead[0].placement is Placement.OWN_LINE):
            return concat(h, indent(concat(hardline, d), n), trail)
        if hid is None:
            return concat(h, " ", d, trail)
        # A header that breaks puts the body on its own line (section 8.3).
        brk = if_break(hardline, line, hid)
        return concat(h, group(indent(concat(brk, d), n)), trail)


def body(
    p: Printer,
    owner: Node,
    header: Doc,
    header_last: int,
    *,
    header_broke: bool = False,
    block: Node | None = None,
    form: Form = "keyword",
    keyword: str = "do",
) -> Doc:
    """`header` and the body of `owner` per `single-statement-body` (see `Body`)."""
    b = Body(p, owner, header_last, block=block, form=form, keyword=keyword)
    return b.doc(header, header_broke)
