"""Printer core (design section 7.7): dispatch, `print`, fallback, statement lists.

Construct printers live in the sibling modules and register themselves with
`@printer(chapel.Kind, ...)`. A printer is `fn(p: Printer, node) -> Doc`; it
prints children with `p.print(child)` and nested statement lists with
`p.statement_list(...)` inside `with p.nested() as n:` + `indent(..., n)`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from chplfmt._chapel import chapel
from chplfmt.comments import expected_comment_text, space_line_comment
from chplfmt.config import FormatOptions
from chplfmt.doc import (
    EMPTY,
    Doc,
    concat,
    hardline,
    literalline,
    text,
    trailing_comment,
    verbatim,
)
from chplfmt.lexer import TokenKind
from chplfmt.offregions import (
    OffRegion,
    OffRegions,
    find_off_regions,
    is_statement_list,
)
from chplfmt.source import display_width
from chplfmt.tokens import Node, Span, TokenIndex

log = logging.getLogger("chplfmt.printer")

type PrintFn = Callable[[Printer, Node], Doc]

REGISTRY: dict[type, PrintFn] = {}


def printer(*classes: type) -> Callable[[PrintFn], PrintFn]:
    """Register the decorated function as the printer for `classes` (and subclasses)."""

    def register(fn: PrintFn) -> PrintFn:
        for cls in classes:
            REGISTRY[cls] = fn
        return fn

    return register


@dataclass(frozen=True)
class RuleApplication:
    """A rule changed the source form at 1-based `input_line` (section 7.8)."""

    rule: str
    input_line: int


@dataclass
class PrintReport:
    applications: list[RuleApplication] = field(default_factory=list[RuleApplication])
    # Nodes printed by the fallback, as `"Tag@line:col"` (coverage gate).
    fallbacks: list[str] = field(default_factory=list[str])

    def rule_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.applications:
            counts[a.rule] = counts.get(a.rule, 0) + 1
        return counts


@dataclass(frozen=True)
class _Element:
    """One item of a statement list: a node, a loose token run, a comment, or an off region."""

    first: int  # token span
    last: int
    node: Node | None = None
    comment: bool = False
    region: OffRegion | None = None


class Printer:
    """Builds the Doc for one file. Not reusable across files."""

    def __init__(
        self,
        index: TokenIndex,
        options: FormatOptions,
        *,
        off: OffRegions | None = None,
        registry: dict[type, PrintFn] | None = None,
    ) -> None:
        self.index = index
        self.source = index.source
        self.tokens = index.tokens
        self.options = options
        self.off = find_off_regions(index) if off is None else off
        self._region_at = {r.off_token: r for r in self.off.regions}
        self.registry = REGISTRY if registry is None else registry
        self.report = PrintReport()
        # Absolute output column of the current statement indentation. Keep it
        # in sync with `indent(...)` via `nested()`; the fallback relies on it.
        self.indent = 0
        # Output column where the last `print`ed node ended, if known.
        self.end_col: int | None = None
        self._dispatch: dict[type, PrintFn | None] = {}

    # Bookkeeping

    def record(self, rule: str, token: int) -> None:
        """Record a `RuleApplication` at the line of token `token`."""
        self.report.applications.append(
            RuleApplication(rule, self.tokens[token].start[0])
        )

    @contextmanager
    def nested(self, n: int | None = None) -> Generator[int]:
        """Track one more level of indentation (default `indent-width`); yields it."""
        n = self.options.indent_width if n is None else n
        self.indent += n
        try:
            yield n
        finally:
            self.indent -= n

    def lookup(self, cls: type) -> PrintFn | None:
        if cls not in self._dispatch:
            self._dispatch[cls] = next(
                (self.registry[c] for c in cls.__mro__ if c in self.registry), None
            )
        return self._dispatch[cls]

    # The print wrapper

    def print(self, node: Node, *, col: int | None = None) -> Doc:
        """Print `node` (section 7.7); `col` is its output start column if known."""
        sp = self.span(node)
        if sp is not None and self.off.contains(self.tokens[sp[0]].start_offset):
            self.end_col = None
            return verbatim(self._original(sp))
        fn = self.lookup(type(node))
        if fn is None:
            d = self.fallback(node, col=col)
        else:
            d = fn(self, node)
            self.end_col = None
        d = self.wrap_user_parens(node, d)
        return concat(self.leading_comments(node), d, self.trailing_comments(node))

    def wrap_user_parens(self, node: Node, d: Doc) -> Doc:
        """Re-add the user's parentheses around `node` (remove-redundant-parens hook)."""
        layers = self.index.parens_around(node)
        for depth, layer in enumerate(layers):
            if self.keep_parens(node, layer, depth):
                d = concat("(", d, ")")
                self.end_col = None
        return d

    def keep_parens(self, node: Node, layer: tuple[int, int], depth: int) -> bool:
        """Whether one layer of user parentheses stays (M6: the rule decides)."""
        return True

    def leading_comments(self, node: Node) -> Doc:
        """Comments attached before `node` (M4 trivia); none yet."""
        return EMPTY

    def trailing_comments(self, node: Node) -> Doc:
        """Comments attached after `node` (M4 trivia); none yet."""
        return EMPTY

    def _original(self, sp: Span) -> str:
        return self.source.text[
            self.tokens[sp[0]].start_offset : self.tokens[sp[1]].end_offset
        ]

    def span(self, node: Node) -> Span | None:
        """The node's tokens, with the terminating `;` for statements in a list."""
        if is_statement_list(self.index.parent(node)):
            return self.index.stmt_span(node)
        return self.index.node_span(node)

    # Fallback

    def fallback(self, node: Node, *, col: int | None = None) -> Doc:
        """The node's source text, re-indented relative to its first line."""
        sp = self.span(node)
        if sp is None:
            self.end_col = col
            return EMPTY
        pos = self.tokens[sp[0]].start
        self.report.fallbacks.append(f"{node.tag()}@{pos[0]}:{pos[1]}")
        if log.isEnabledFor(logging.DEBUG):
            log.debug("fallback printer for %s at %d:%d", node.tag(), *pos)
        return self.raw_tokens(sp[0], sp[1], col=col)

    def raw_tokens(self, first: int, last: int, *, col: int | None = None) -> Doc:
        """Tokens `first..last` laid out as in the source (see `fallback`).

        Line `i` is indented by `self.indent + (d_i - d_0)` (never below 0),
        where `d_i` is the display column of its first token in the source and
        `d_0` the indentation of the first line. Whitespace between tokens on a
        line becomes spaces of the same display width (tab stops measured in
        the source), so alignment within a line is kept. Blank lines collapse
        to `max-blank-lines`. Multi-line strings and extern blocks are emitted
        byte-for-byte; comments get their normalized text.
        """
        tokens = self.tokens
        source = self.source
        stext = source.text
        opts = self.options
        tab = opts.tab_size
        start_col = self.indent if col is None else col
        line0 = tokens[first].start[0]
        ws = source.line_text(line0)
        d0 = display_width(ws[: len(ws) - len(ws.lstrip())], 0, tab)
        shift = self.indent - d0

        parts: list[Doc] = []
        cur: list[str] = []
        line_start = start_col  # output column of cur[0]

        def flush() -> None:
            if cur:
                parts.append(text("".join(cur)))
                cur.clear()

        def out_col() -> int:
            return display_width("".join(cur), line_start, tab)

        regions = self._region_at
        i = first
        while i <= last:
            tok = tokens[i]
            if i > first:
                if tok.nl_before:
                    flush()
                    blank = min(tok.nl_before - 1, opts.max_blank_lines)
                    parts.extend([literalline] * (blank + 1))
                    r = regions.get(i)
                    if r is not None:
                        region = stext[r.start : r.end]
                        parts.append(verbatim(region))
                        line_start = display_width(region.rsplit("\n", 1)[-1], 0, tab)
                        while i <= last and tokens[i].start_offset < r.end:
                            i += 1
                        continue
                    d = source.display_column(tok.start_offset, tab)
                    line_start = max(0, d + shift)
                    if line_start:
                        cur.append(" " * line_start)
                    line_start = 0
                elif tok.ws_before:
                    prev_end = tokens[i - 1].end_offset
                    gap = display_width(
                        stext[prev_end : tok.start_offset],
                        source.display_column(prev_end, tab),
                        tab,
                    ) - source.display_column(prev_end, tab)
                    cur.append(" " * max(gap, 1))
            kind = tok.kind
            if kind is TokenKind.LINE_COMMENT or kind is TokenKind.BLOCK_COMMENT:
                out = self.comment_text(i, out_col())
                first_line, *rest = out.split("\n")
                cur.append(first_line)
                for seg in rest:
                    flush()
                    parts.append(literalline)
                    cur.append(seg)
                    line_start = 0
            elif "\n" in tok.text:  # multi-line string or extern block
                flush()
                parts.append(verbatim(tok.text))
                last_seg = tok.text.rsplit("\n", 1)[1]
                line_start = display_width(last_seg, 0, tab)
            else:
                cur.append(tok.text)
            i += 1
        flush()
        self.end_col = out_col()
        return concat(*parts)

    def comment_text(self, i: int, output_col: int) -> str:
        """Normalized text of comment token `i` printed at `output_col`."""
        tok = self.tokens[i]
        opts = self.options
        if (
            opts.comment_spacing
            and tok.kind is TokenKind.LINE_COMMENT
            and space_line_comment(tok.text) != tok.text
        ):
            self.record("comment-spacing", i)
        return expected_comment_text(
            tok.text,
            input_col=self.source.display_column(tok.start_offset, opts.tab_size),
            output_col=output_col,
            tab_size=opts.tab_size,
            comment_spacing=opts.comment_spacing,
        )

    # Statement lists

    def statement_list(self, stmts: Sequence[Node], first: int, end: int) -> Doc:
        """Statements and the comments between them, starting at `self.indent`.

        `first..end-1` are the tokens inside the list (e.g. after `{`, before
        `}`). Statements go on their own lines; blank lines between items
        collapse to `max-blank-lines`; none are kept before the first item.
        Off regions are emitted byte-for-byte. Comments are emitted where they
        are (own-line or after code on the same line) until M4 attaches them.
        """
        parts: list[Doc] = []
        col: int | None = self.indent
        prev: _Element | None = None
        for el in self._elements(stmts, first, end):
            if (
                isinstance(el.node, chapel.EmptyStmt)
                and self.options.remove_empty_statements
            ):
                self.record("remove-empty-statements", el.first)
                continue
            tok = self.tokens[el.first]
            same_line = prev is not None and tok.nl_before == 0
            if el.region is not None:
                if prev is not None:
                    blank = min(max(tok.nl_before - 1, 0), self.options.max_blank_lines)
                    parts.extend([literalline] * (blank + 1))
                r = el.region
                parts.append(verbatim(self.source.text[r.start : r.end]))
                col = None
                prev = el
                continue
            if same_line and (el.comment or (prev is not None and prev.comment)):
                parts.append(text(" "))
                col = None if col is None else col + 1
            elif prev is not None:
                blank = min(max(tok.nl_before - 1, 0), self.options.max_blank_lines)
                parts.extend([hardline] * (blank + 1))
                col = self.indent
            if el.comment:
                d, col = self._list_comment(el.first, col, same_line)
                parts.append(d)
            elif el.node is not None:
                parts.append(self.print(el.node, col=col))
                col = self.end_col
            else:
                parts.append(self.raw_tokens(el.first, el.last, col=col))
                col = self.end_col
            prev = el
        return concat(*parts)

    def _list_comment(
        self, i: int, col: int | None, same_line: bool
    ) -> tuple[Doc, int | None]:
        tok = self.tokens[i]
        if same_line and tok.kind is TokenKind.LINE_COMMENT:
            return trailing_comment(self.comment_text(i, col or 0)), None
        if col is None and "\n" in tok.text:
            # Unknown column: move a multi-line block comment to its own line.
            col = self.indent
            out = self.comment_text(i, col)
            lines = out.split("\n")
            return concat(hardline, self._lines(lines)), None
        out = self.comment_text(i, col or 0)
        lines = out.split("\n")
        tab = self.options.tab_size
        if len(lines) == 1:
            return text(out), (None if col is None else display_width(out, col, tab))
        return self._lines(lines), display_width(lines[-1], 0, tab)

    @staticmethod
    def _lines(lines: list[str]) -> Doc:
        parts: list[Doc] = [text(lines[0])]
        for line in lines[1:]:
            parts += [literalline, text(line)]
        return concat(*parts)

    def _elements(
        self, stmts: Sequence[Node], first: int, end: int
    ) -> Iterator[_Element]:
        """List items in token order; off regions swallow the items they contain."""
        tokens = self.tokens
        regions = sorted(self.off.regions, key=lambda r: r.start)
        ri = 0

        def items() -> Iterator[_Element]:
            i = first
            for node in stmts:
                sp = self.index.stmt_span(node)
                if sp is None:
                    continue
                yield from loose(i, sp[0])
                yield _Element(sp[0], sp[1], node=node)
                i = sp[1] + 1
            yield from loose(i, end)

        def loose(i: int, stop: int) -> Iterator[_Element]:
            while i < stop:
                if tokens[i].is_comment:
                    yield _Element(i, i, comment=True)
                    i += 1
                    continue
                j = i
                while j + 1 < stop and not tokens[j + 1].is_comment:
                    j += 1
                yield _Element(i, j)
                i = j + 1

        current: OffRegion | None = None
        for el in items():
            offset = tokens[el.first].start_offset
            while ri < len(regions) and regions[ri].end <= offset:
                ri += 1
            if ri < len(regions) and regions[ri].start <= offset:
                if regions[ri] is not current:
                    current = regions[ri]
                    yield _Element(current.off_token, current.off_token, region=current)
                continue
            yield el

    # File level

    def print_file(self) -> Doc:
        """The whole file: its top-level statement list and a final newline."""
        roots = self.index.roots
        stmts: list[Node] = []
        for root in roots:
            if isinstance(root, chapel.Module) and root.kind() == "implicit":
                stmts.extend(self.index.children(root))
            else:
                stmts.append(root)
        eof = len(self.tokens) - 1
        if eof == 0:
            return EMPTY
        return concat(self.statement_list(stmts, 0, eof), hardline)
