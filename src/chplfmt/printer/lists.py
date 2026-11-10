"""Shared list layouts: `bracket_list` (section 7.7), bin-packed lists, assignments."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from chplfmt.doc import (
    ALL_LINES,
    EMPTY,
    FIRST_LINE,
    Doc,
    align,
    concat,
    conditional_group,
    fill,
    group,
    hardline,
    indent,
    line,
    on_render,
    softline,
    text,
)
from chplfmt.printer.core import Printer, aligns_in_parens
from chplfmt.tokens import Node
from chplfmt.trivia import Placement


class ListKind(enum.Enum):
    """Whether a trailing comma is legal in a list (section 6)."""

    FIXED = "fixed"  # illegal: calls, formals, `with`, `zip`, `use`, ...
    TRAILING = "trailing"  # legal, optional: array/domain literals, enums
    TUPLE = "tuple"  # legal; required with one element (tuples, tuple decls)


@dataclass(frozen=True)
class ListItem:
    """One list element with its comments, split around its comma."""

    lead: Doc  # leading comments (with their line breaks)
    body: Doc
    before_comma: Doc = EMPTY
    after_comma: Doc = EMPTY
    # An own-line leading comment: the item must start a line.
    breaks_before: bool = False
    # The first leading comment is an end-of-line `//` comment (after the
    # previous comma or the open bracket).
    eol_lead: bool = False
    # A `//` or own-line comment follows: the next thing must start a line.
    breaks_after: bool = False
    # Multi-line fallback text, which can't move: the list keeps its source layout.
    raw: bool = False


def prints_raw_lines(p: Printer, node: Node, n_fallbacks: int) -> bool:
    """Whether `node` spans source lines and its printing (since `n_fallbacks`) fell back."""
    sp = p.index.node_span(node)
    return (
        sp is not None
        and len(p.report.fallbacks) > n_fallbacks
        and p.tokens[sp[0]].start[0] != p.tokens[sp[1]].start[0]
    )


def list_item(p: Printer, node: Node, prefix: Doc = EMPTY) -> ListItem:
    """`node` as a list element (`prefix`, e.g. `name=`, goes after its leading comments)."""
    lead = p.trivia.leading(node)
    lead_doc = p.leading_comments(node)
    n_fallbacks = len(p.report.fallbacks)
    body = concat(prefix, p.print(node, leading=False, trailing=False))
    trail = p.trivia.trailing(node)
    sp = p.index.node_span(node)
    comma = None
    if sp is not None:
        j = p.index.next_code(sp[1])
        if j < len(p.tokens) and p.tokens[j].text == ",":
            comma = j
    before = [c for c in trail if comma is not None and c.token < comma]
    after = [c for c in trail if comma is None or c.token > comma]
    if before and (before[-1].is_line or before[-1].placement is Placement.OWN_LINE):
        after = before + after
        before = []
    return ListItem(
        lead=lead_doc,
        body=body,
        before_comma=p.comments_after(before),
        after_comma=p.comments_after(after),
        breaks_before=any(c.placement is Placement.OWN_LINE for c in lead),
        eol_lead=bool(lead)
        and lead[0].is_line
        and lead[0].placement is Placement.END_OF_LINE,
        breaks_after=any(c.is_line or c.placement is Placement.OWN_LINE for c in after),
        raw=prints_raw_lines(p, node, n_fallbacks),
    )


def _items(p: Printer, items: Sequence[ListItem | Node]) -> list[ListItem]:
    return [it if isinstance(it, ListItem) else list_item(p, it) for it in items]


def list_parts(items: Sequence[ListItem], last_comma: Doc = EMPTY) -> list[Doc]:
    """Fill parts `item, sep, item, ...`; commas belong to the items."""
    parts: list[Doc] = []
    last = len(items) - 1
    for k, it in enumerate(items):
        if k:
            prev = items[k - 1]
            parts.append(hardline if prev.breaks_after or it.breaks_before else line)
        comma = "," if k < last else last_comma
        parts.append(concat(it.lead, it.body, it.before_comma, comma, it.after_comma))
    return parts


def list_fill(p: Printer, items: Sequence[ListItem | Node]) -> Doc:
    """`a, b, c` bin-packed, aligned with the first item (no brackets)."""
    return align(fill(list_parts(_items(p, items))))


@dataclass(frozen=True)
class BracketList:
    """The two layouts of a bracketed list; `aligned` is None if comments forbid it."""

    aligned: Doc | None
    fallback: Doc

    def doc(self) -> Doc:
        if self.aligned is None:
            return group(self.fallback, should_break=True)
        if self.aligned is self.fallback:
            return self.aligned
        return group(conditional_group([self.aligned, self.fallback], ALL_LINES))


def bracket_layouts(
    p: Printer,
    owner: Node,
    open_tok: int,
    items: Sequence[ListItem | Node],
    kind: ListKind = ListKind.FIXED,
    *,
    spacing: bool = False,
) -> BracketList:
    """Layouts of the list `open_tok ... match` (see `bracket_list`)."""
    tokens = p.tokens
    opts = p.options
    close = tokens[open_tok].match
    assert close is not None
    open_text, close_text = tokens[open_tok].text, tokens[close].text
    its = _items(p, items)
    if any(it.raw for it in its):
        p.emitted[:] = [i for i in p.emitted if not open_tok < i < close]
        d = p.raw_tokens(open_tok, close)
        return BracketList(d, d)
    rest = [c for c in p.dangling(owner, open_text) if open_tok < c.token < close]
    rest_breaks = any(c.is_line or c.placement is Placement.OWN_LINE for c in rest)
    if not its and not rest_breaks:
        rest_doc = concat(
            *(
                concat(" " if k else "", p.comment_doc(c.token))
                for k, c in enumerate(rest)
            )
        )
    else:
        rest_doc = p.comments_after(rest)
    if not its:
        if not rest_breaks:
            d = concat(open_text, rest_doc, close_text)
        else:
            d = concat(
                open_text,
                indent(rest_doc, opts.continuation_indent),
                hardline,
                close_text,
            )
        return BracketList(d, d)

    prev = p.index.prev_code(close)
    assert prev is not None
    src_comma = prev > open_tok and tokens[prev].text == ","
    comma_tok = prev
    always = kind is ListKind.TUPLE and len(its) == 1
    if always or kind is ListKind.FIXED or not opts.trailing_comma:
        aligned_comma: Doc = text(",") if always or src_comma else EMPTY
        fallback_comma: Doc = aligned_comma
    else:

        def rec() -> None:
            p.record("trailing-comma", comma_tok)

        aligned_comma = on_render(rec) if src_comma else EMPTY
        fallback_comma = text(",") if src_comma else concat(",", on_render(rec))

    cont = opts.continuation_indent
    first = EMPTY if its[0].eol_lead else softline
    fallback = concat(
        open_text,
        indent(concat(first, fill(list_parts(its, fallback_comma)), rest_doc), cont),
        softline,
        close_text,
    )
    if its[0].eol_lead or its[0].breaks_before or its[-1].breaks_after or rest:
        return BracketList(None, fallback)
    sp = " " if spacing else ""
    aligned = concat(
        open_text, sp, align(fill(list_parts(its, aligned_comma))), sp, close_text
    )
    return BracketList(aligned, fallback)


def bracket_list(
    p: Printer,
    owner: Node,
    open_tok: int,
    items: Sequence[ListItem | Node],
    kind: ListKind = ListKind.FIXED,
    *,
    spacing: bool = False,
) -> Doc:
    """A bracketed list (section 8.4): flat, aligned bin-pack, or the fallback.

    `open_tok` is the open bracket token (owned by `owner`, whose dangling
    comments inside the brackets are printed); `items` are nodes or prepared
    `ListItem`s. The fallback breaks after the open bracket, indents by
    `continuation-indent`, and puts the close bracket on its own line.
    Trailing commas follow the `trailing-comma` rule for `kind`. `spacing`
    puts spaces inside non-empty brackets (`bracket-spacing`).
    """
    return bracket_layouts(p, owner, open_tok, items, kind, spacing=spacing).doc()


def aligned_expr(p: Printer, node: Node) -> Doc:
    """`node` after a keyword or `=`: operator chains and `if` align with their first character."""
    d = p.print(node)
    return align(d) if aligns_in_parens(node) else d


def assignment(p: Printer, lhs: Doc, op: str, rhs: Node) -> Doc:
    """`lhs op rhs` (section 7.7): break inside `rhs` first, after `op` last."""
    cont = p.options.continuation_indent
    lead = p.trivia.leading(rhs)
    if lead and (lead[0].is_line or lead[0].placement is Placement.OWN_LINE):
        lead_doc = p.leading_comments(rhs)
        with p.nested(cont):
            r = p.print(rhs, leading=False)
        if lead[0].placement is Placement.END_OF_LINE:
            return concat(lhs, " ", op, indent(concat(lead_doc, r), cont))
        return concat(lhs, " ", op, indent(concat(hardline, lead_doc, r), cont))
    # Fallback text keeps source line offsets, so it can't move between layouts.
    n_fallbacks, n_emitted = len(p.report.fallbacks), len(p.emitted)
    r = p.print(rhs)
    if prints_raw_lines(p, rhs, n_fallbacks):
        sp = p.index.node_span(rhs)
        if sp is None or not p.tokens[sp[0]].nl_before:
            return concat(lhs, " ", op, " ", r)
        del p.report.fallbacks[n_fallbacks:]
        del p.emitted[n_emitted:]
        with p.nested(cont):
            r = p.print(rhs)
        return concat(lhs, " ", op, indent(concat(hardline, r), cont))
    return conditional_group(
        [
            concat(lhs, " ", op, " ", align(r) if aligns_in_parens(rhs) else r),
            concat(lhs, " ", op, indent(concat(hardline, r), cont)),
        ],
        FIRST_LINE,
    )
