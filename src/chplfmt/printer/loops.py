"""Printers for For, Forall, Foreach, Coforall, BracketLoop, While, DoWhile, Zip (section 7.7).

WithClause is printed by `stmts`.
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import EMPTY, Doc, concat, flat_width, hardline, text
from chplfmt.printer.body import Body, fits
from chplfmt.printer.common import (
    NO_SPACE_BEFORE,
    ends_line,
    header_start,
    open_brace,
    semicolon,
    tokens_doc,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.exprs import outer_start
from chplfmt.printer.lists import aligned_expr, bracket_list
from chplfmt.printer.stmts import with_clause, with_header
from chplfmt.tokens import Node


def outer_end(p: Printer, node: Node) -> int:
    """Last token of `node`, including the user parentheses around it."""
    layers = p.index.parens_around(node)
    if layers:
        return layers[-1][1]
    sp = p.index.node_span(node)
    assert sp is not None
    return sp[1]


def has_comments(p: Printer, first: int, last: int) -> bool:
    return any(p.tokens[i].is_comment for i in range(first, last + 1))


def keyword_header(
    p: Printer, node: Node, first: int, last: int, kid: Node | None
) -> tuple[Doc, bool]:
    """Tokens `first..last` of `node`; `kid` (a condition or iterand) lines up
    with its own first character when it wraps (section 7.7)."""
    if (
        kid is None
        or p.index.node_span(kid) is None
        or has_comments(p, first, last)
        or not first <= outer_start(p, kid) <= outer_end(p, kid) <= last
    ):
        return tokens_doc(p, node, first, last)
    start, end = outer_start(p, kid), outer_end(p, kid)
    parts: list[Doc] = []
    if start > first:
        parts.append(tokens_doc(p, node, first, start - 1)[0])
        if p.tokens[start - 1].text != "[":
            parts.append(text(" "))
    parts.append(aligned_expr(p, kid))
    if end < last:
        if p.tokens[end + 1].text not in NO_SPACE_BEFORE:
            parts.append(text(" "))
        parts.append(tokens_doc(p, node, end + 1, last)[0])
    return concat(*parts), False


def loop_header(
    p: Printer, node: Node, first: int, last: int, end_width: int
) -> tuple[Doc, bool]:
    """`for i in D`, `forall i in D with (...)`: `with` placement per section 8.7.

    `end_width` is the width of what follows the header (` {`, ` do`).
    """
    assert isinstance(node, chapel.IndexableLoop)
    wc = node.with_clause()
    it = node.iterand()
    wsp = None if wc is None else p.index.node_span(wc)
    if (
        wc is None
        or wsp is None
        or wsp[1] != last
        or p.trivia.leading(wc)
        or p.trivia.trailing(wc)
        or has_comments(p, first, last)
    ):
        return keyword_header(p, node, first, last, it)
    head, _ = keyword_header(p, node, first, wsp[0] - 1, it)
    res = with_clause(p, wc)
    if res is None:
        return concat(head, " ", p.print(wc)), False
    clause, first_w = res
    hw = flat_width(head, p.options)
    if node.is_expression_level() or hw is None or first_w is None:
        return with_header(p, head, clause), False
    single = len(p.index.children(wc)) == 1
    need = hw + 1 + first_w + (end_width if single else 0)
    return concat(head, text(" ") if fits(p, need) else hardline, clause), False


def _body_start(p: Printer, node: Node, first: int, blk: Node) -> int | None:
    """The node's `do`, or the `{` of its body block."""
    starts = [
        i
        for i in [*p.index.own_tokens(node), *p.index.structural_brackets(blk)]
        if i > first and p.tokens[i].text in ("do", "{")
    ]
    return min(starts) if starts else None


@printer(chapel.For, chapel.Forall, chapel.Foreach, chapel.Coforall)
def print_loop(p: Printer, node: Node) -> Doc | None:
    """`for i in D do S;`, `forall i in D with (...) { }`, and expression-level loops."""
    assert isinstance(node, chapel.IndexableLoop)
    first = header_start(p, node)
    blk = node.body()
    start = _body_start(p, node, first, blk)
    hl = None if start is None else p.index.prev_code(start)
    if hl is None:
        return None
    mode = "preserve" if node.is_expression_level() else None
    b = Body(p, node, hl, block=blk, mode=mode)
    attach = p.options.brace_style == "attach"
    end_w = 3 if b.kind != "braces" else 2 if attach else 0
    head, broke = loop_header(p, node, first, hl, end_w)
    return with_attributes(p, node, b.doc(head, broke))


@printer(chapel.BracketLoop)
def print_bracket_loop(p: Printer, node: Node) -> Doc | None:
    """`[i in D] S;`, `[i in D with (ref x)] { }`, `[i in D] i * 2`, `[D] int`."""
    assert isinstance(node, chapel.BracketLoop)
    first = header_start(p, node)
    close = p.tokens[first].match
    if p.tokens[first].text != "[" or close is None:
        return None
    mode = "preserve" if node.is_expression_level() else None
    b = Body(p, node, close, block=node.body(), form="bare", mode=mode)
    head, broke = keyword_header(p, node, first, close, node.iterand())
    return with_attributes(p, node, b.doc(head, broke))


@printer(chapel.While)
def print_while(p: Printer, node: Node) -> Doc | None:
    """`while cond do S;`, `while cond { }`."""
    assert isinstance(node, chapel.While)
    first = header_start(p, node)
    blk = node.body()
    start = _body_start(p, node, first, blk)
    hl = None if start is None else p.index.prev_code(start)
    if hl is None:
        return None
    b = Body(p, node, hl, block=blk)
    head, broke = keyword_header(p, node, first, hl, node.condition())
    return with_attributes(p, node, b.doc(head, broke))


@printer(chapel.DoWhile)
def print_do_while(p: Printer, node: Node) -> Doc | None:
    """`do { } while cond;` (the body form is preserved)."""
    assert isinstance(node, chapel.DoWhile)
    first = header_start(p, node)
    blk = node.body()
    sp, bsp = p.index.node_span(node), p.index.node_span(blk)
    whiles = [i for i in p.index.own_tokens(node) if p.tokens[i].text == "while"]
    if (
        sp is None
        or bsp is None
        or not whiles
        or open_brace(p, blk) is None
        or has_comments(p, bsp[1] + 1, whiles[-1])
    ):
        return None
    w, last = whiles[-1], sp[1]
    semi = p.tokens[last].text == ";" and p.index.owner(last) == node
    d = Body(p, node, first, block=blk, form="block").doc(text("do"))
    cond, _ = keyword_header(p, node, w, last - 1 if semi else last, node.condition())
    sep = EMPTY if ends_line(p.trivia.trailing(blk)) else text(" ")
    d = concat(d, sep, cond)
    return with_attributes(p, node, semicolon(p, node, d) if semi else d)


@printer(chapel.Zip)
def print_zip(p: Printer, node: Node) -> Doc | None:
    """`zip(a, b)`: a list without trailing comma."""
    opens = [i for i in p.index.own_tokens(node) if p.tokens[i].text == "("]
    if not opens:
        return None
    kids = [k for k in p.index.children(node) if p.index.node_span(k) is not None]
    return concat("zip", bracket_list(p, node, opens[0], kids))
