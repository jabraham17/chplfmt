"""Printer core (design section 7.7): dispatch, `print`, fallback, statement lists.

Construct printers live in the sibling modules and register themselves with
`@printer(chapel.Kind, ...)`. A printer is `fn(p: Printer, node) -> Doc`; it
prints children with `p.print(child)` and nested statement lists with
`p.statement_list(...)` inside `with p.nested() as n:` + `indent(..., n)`.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Generator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

from chplfmt._chapel import chapel
from chplfmt.comments import expected_comment_text, space_line_comment
from chplfmt.config import FormatOptions
from chplfmt.doc import (
    EMPTY,
    Doc,
    break_parent,
    column_text,
    concat,
    hardline,
    literalline,
    text,
    trailing_comment,
    verbatim,
)
from chplfmt.errors import InternalError
from chplfmt.lexer import TokenKind
from chplfmt.offregions import (
    OffRegion,
    OffRegions,
    directive,
    find_off_regions,
    is_statement_list,
)
from chplfmt.source import display_width
from chplfmt.tokens import Node, Span, TokenIndex
from chplfmt.trivia import Attachment, Comment, Key, Placement, attach

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


@dataclass(frozen=True)
class PrintWarning:
    """A user-facing warning at 1-based `line`:`col` (byte column)."""

    line: int
    col: int
    message: str


@dataclass
class PrintReport:
    applications: list[RuleApplication] = field(default_factory=list[RuleApplication])
    # Nodes printed by the fallback, as `"Tag@line:col"` (coverage gate).
    fallbacks: list[str] = field(default_factory=list[str])
    warnings: list[PrintWarning] = field(default_factory=list[PrintWarning])

    def rule_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in self.applications:
            counts[a.rule] = counts.get(a.rule, 0) + 1
        return counts


@dataclass
class _Element:
    """One item of a statement list: a node, a loose token run, or an off region."""

    first: int  # token span
    last: int
    node: Node | None = None
    region: OffRegion | None = None
    swallowed: list[Node] = field(default_factory=list[Node])  # nodes in `region`


class Printer:
    """Builds the Doc for one file. Not reusable across files."""

    def __init__(
        self,
        index: TokenIndex,
        options: FormatOptions,
        *,
        off: OffRegions | None = None,
        registry: dict[type, PrintFn] | None = None,
        path: str = "<stdin>",
    ) -> None:
        self.index = index
        self.source = index.source
        self.tokens = index.tokens
        self.options = options
        self.path = path
        self.off = find_off_regions(index) if off is None else off
        self._region_at = {r.off_token: r for r in self.off.regions}
        self.registry = REGISTRY if registry is None else registry
        self.report = PrintReport()
        self.trivia: Attachment = attach(index, self.off)
        # Comment tokens put into the Doc, for the exactly-once check.
        self.emitted: list[int] = []
        for i in self.off.misplaced:
            self._warn_directive(i)
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

    def print(
        self,
        node: Node,
        *,
        col: int | None = None,
        leading: bool = True,
        trailing: bool = True,
    ) -> Doc:
        """Print `node` (section 7.7); `col` is its output start column if known.

        Leading and trailing comments are included unless the caller prints
        them itself (`leading=False` + `leading_comments(node)`, e.g. comments
        before `else`). Print each node once and reuse the Doc in alternatives.
        """
        lead = self.leading_comments(node) if leading else EMPTY
        sp = self.span(node)
        if sp is not None and self.off.contains(self.tokens[sp[0]].start_offset):
            self.end_col = None
            d: Doc = verbatim(self._original(sp))
        else:
            fn = self.lookup(type(node))
            if fn is None:
                d = self.fallback(node, col=col)
            else:
                d = fn(self, node)
                self.end_col = None
            d = self.wrap_user_parens(node, d)
        return concat(lead, d, self.trailing_comments(node) if trailing else EMPTY)

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

    # Comments (section 7.5). Each helper marks what it returns as emitted.

    def comment_doc(self, i: int) -> Doc:
        """Comment token `i`; a multi-line block comment re-indents by its column."""
        self.emitted.append(i)
        if "\n" in self.tokens[i].text:
            return column_text(lambda col: self.comment_text(i, col))
        return text(self.comment_text(i, 0))

    def _breaks(self, nl: int) -> list[Doc]:
        blank = min(max(nl - 1, 0), self.options.max_blank_lines)
        return [hardline] * (blank + 1)

    def leading_comments(self, node: Key) -> Doc:
        """Comments before `node`, each followed by a space or line break(s).

        An end-of-line `//` comment (e.g. after an open bracket) becomes a
        trailing comment of the current line.
        """
        parts: list[Doc] = []
        for c in self.trivia.leading(node):
            if c.is_line and c.placement is Placement.END_OF_LINE:
                self.emitted.append(c.token)
                parts.append(trailing_comment(self.comment_text(c.token, 0)))
            else:
                parts.append(self.comment_doc(c.token))
            parts += (
                self._breaks(c.nl_after) if c.nl_after or c.is_line else [text(" ")]
            )
        return concat(*parts)

    def trailing_comments(self, node: Key) -> Doc:
        """Comments after `node`.

        Own-line ones go on their own lines (blank lines collapsed); `//`
        end-of-line ones become trailing comments (`break_parent`); others
        follow after one space. After an own-line `//` comment a line break
        follows, except for statement-list items (the list adds it).
        """
        cs = self.trivia.trailing(node)
        parts = [self._comment_after(c) for c in cs]
        if (
            cs
            and cs[-1].is_line
            and cs[-1].placement is Placement.OWN_LINE
            and node is not None
            and not self.is_list_item(node)
        ):
            parts.append(hardline)
        return concat(*parts)

    def is_list_item(self, node: Node) -> bool:
        """Whether `node` is a statement of its parent's statement list."""
        parent = self.index.parent(node)
        if not is_statement_list(parent):
            return False
        if parent is None or (
            isinstance(parent, chapel.Module) and parent.kind() == "implicit"
        ):
            return True
        opens = [
            i
            for i in self.index.structural_brackets(parent)
            if self.tokens[i].text == "{"
        ]
        sp = self.index.node_span(node)
        return not opens or sp is None or sp[0] > opens[-1]

    def comments_after(self, cs: Sequence[Comment], *, first_blank: bool = True) -> Doc:
        """Comments `cs` as `trailing_comments` lays them out (no final break).

        With `first_blank=False`, blank lines before the first one are dropped.
        """
        parts: list[Doc] = []
        for k, c in enumerate(cs):
            if k == 0 and not first_blank and c.placement is Placement.OWN_LINE:
                parts.append(concat(hardline, self.comment_doc(c.token)))
                continue
            parts.append(self._comment_after(c))
        return concat(*parts)

    def _comment_after(self, c: Comment) -> Doc:
        if c.placement is Placement.OWN_LINE:
            return concat(*self._breaks(c.nl_before), self.comment_doc(c.token))
        if c.is_line:
            self.emitted.append(c.token)
            return concat(trailing_comment(self.comment_text(c.token, 0)), break_parent)
        return concat(" ", self.comment_doc(c.token))

    def dangling_comments(self, node: Key, *anchors: str) -> Doc:
        """Not-yet-emitted dangling comments of `node` (all, or those after `anchors`).

        Anchor kinds are `{`, `(`, `[`, `then`, `else`, `header`, or `""` for
        comments with no anchor. Own-line comments start on a new line; others
        follow after one space. The caller must break the line after the
        result if it may end with a `//` comment (it ends with `break_parent`).
        """
        return self.comments_after(self.dangling(node, *anchors))

    def dangling(self, node: Key, *anchors: str) -> list[Comment]:
        """Not-yet-emitted dangling comments of `node` (see `dangling_comments`)."""
        done = set(self.emitted)
        found: list[Comment] = []
        for d in self.trivia.dangling(node):
            kind = "" if d.anchor is None else d.anchor.kind
            if d.comment.token in done or (anchors and kind not in anchors):
                continue
            found.append(d.comment)
        return found

    def check_comments(self) -> None:
        """Raise `InternalError` unless every attached comment was emitted once."""
        counts = Counter(self.emitted)
        for i in self.trivia.comments:
            n = counts.pop(i, 0)
            if n != 1:
                self._comment_error(i, f"printed {n} times")
        for i in counts:
            self._comment_error(i, "printed but not attached")

    def _comment_error(self, i: int, what: str) -> None:
        line, col = self.tokens[i].start
        raise InternalError(
            f"{self.path}: internal error: comment at {line}:{col} {what}"
        )

    def _warn_directive(self, i: int) -> None:
        line, col = self.tokens[i].start
        why = (
            "no matching `chplfmt: off`"
            if directive(self.index, i) == "on"
            else "not between statements"
        )
        message = f"chplfmt directive ignored ({why})"
        log.warning("%s:%d:%d: %s", self.path, line, col, message)
        self.report.warnings.append(PrintWarning(line, col, message))

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
        known = True  # False after a multi-line comment (column set at render)

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
                    known = True
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
                if "\n" in tok.text:
                    flush()
                    parts.append(self.comment_doc(i))
                    known = False
                else:
                    self.emitted.append(i)
                    cur.append(self.comment_text(i, 0))
            elif "\n" in tok.text:  # multi-line string or extern block
                flush()
                parts.append(verbatim(tok.text))
                last_seg = tok.text.rsplit("\n", 1)[1]
                line_start = display_width(last_seg, 0, tab)
                known = True
            else:
                cur.append(tok.text)
            i += 1
        flush()
        self.end_col = out_col() if known else None
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
        """Statements with their comments, starting at `self.indent`.

        `first..end-1` are the tokens inside the list (e.g. after `{`, before
        `}`). Statements go on their own lines; blank lines between items
        (counted from an item's first leading comment) collapse to
        `max-blank-lines`; none are added before the first item. Off regions
        are emitted byte-for-byte from the start of their line. The caller
        must follow the result with a line break (the last item may end with
        an own-line `//` comment) and prints dangling comments of the list's
        owner (`dangling_comments`), e.g. an end-of-line comment after `{`.
        """
        parts: list[Doc] = []
        started = False
        for el in self._elements(stmts, first, end):
            node = el.node
            if el.region is not None:
                lead = [c for n in el.swallowed for c in self.trivia.leading(n)]
                if started:
                    parts += self._breaks(
                        self.tokens[lead[0].token if lead else el.first].nl_before
                    )
                r = el.region
                parts += [self.leading_comments(n) for n in el.swallowed]
                parts.append(verbatim(self.source.text[r.start : r.end], bol=True))
                parts += [self.trailing_comments(n) for n in el.swallowed]
                started = True
                continue
            first_tok = el.first
            if node is not None and (lead := self.trivia.leading(node)):
                first_tok = lead[0].token
            if (
                isinstance(node, chapel.EmptyStmt)
                and self.options.remove_empty_statements
            ):
                self.record("remove-empty-statements", el.first)
                cs = self.trivia.leading(node) + self.trivia.trailing(node)
                if not cs:
                    continue
                d = self._comment_lines(cs)
            elif node is not None:
                d = self.print(node, col=self.indent)
            else:
                d = self.raw_tokens(el.first, el.last, col=self.indent)
            if started:
                parts += self._breaks(self.tokens[first_tok].nl_before)
            parts.append(d)
            started = True
        return concat(*parts)

    def _comment_lines(self, cs: list[Comment]) -> Doc:
        """Comments each on its own line (those of a dropped statement or file)."""
        parts: list[Doc] = []
        for k, c in enumerate(cs):
            if k:
                parts += self._breaks(c.nl_before)
            parts.append(self.comment_doc(c.token))
        return concat(*parts)

    def _elements(self, stmts: Sequence[Node], first: int, end: int) -> list[_Element]:
        """List items in token order; off regions swallow the items they contain.

        Comments are not items: they are attached to nodes.
        """
        tokens = self.tokens
        items: list[_Element] = []

        def loose(i: int, stop: int) -> None:
            while i < stop:
                if tokens[i].is_comment:
                    i += 1
                    continue
                j = i
                while j + 1 < stop and not tokens[j + 1].is_comment:
                    j += 1
                items.append(_Element(i, j))
                i = j + 1

        i = first
        for node in stmts:
            sp = self.index.stmt_span(node)
            if sp is None:
                continue
            loose(i, sp[0])
            items.append(_Element(sp[0], sp[1], node=node))
            i = sp[1] + 1
        loose(i, end)

        regions = sorted(
            (
                r
                for r in self.off.regions
                if first <= r.off_token < end
                and not any(it.first <= r.off_token <= it.last for it in items)
            ),
            key=lambda r: r.off_token,
        )
        if not regions:
            return items
        out: list[_Element] = []
        ri = 0
        current: _Element | None = None
        for it in items:
            while ri < len(regions) and regions[ri].off_token < it.first:
                r = regions[ri]
                current = _Element(r.off_token, r.off_token, region=r)
                out.append(current)
                ri += 1
            if (
                current is not None
                and (r := current.region) is not None
                and r.start <= tokens[it.first].start_offset < r.end
            ):
                if it.node is not None:
                    current.swallowed.append(it.node)
                continue
            out.append(it)
        out += [_Element(r.off_token, r.off_token, region=r) for r in regions[ri:]]
        return out

    # File level

    def print_file(self) -> Doc:
        """The whole file: its top-level statement list and a final newline.

        Raises `InternalError` if a comment would be lost or duplicated.
        """
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
        body = self.statement_list(stmts, 0, eof)
        # Comments of a file without statements.
        cs = [
            d.comment
            for key in {self.trivia.file_node, None}
            for d in self.trivia.dangling(key)
        ]
        if cs:
            cs.sort(key=lambda c: c.token)
            body = concat(body, self._comment_lines(cs))
        self.check_comments()
        return concat(body, hardline)
