"""Printers for Conditional (statement and expression level) (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import (
    Doc,
    DocLike,
    align,
    concat,
    flat_width,
    group,
    hardline,
    indent,
    line,
    text,
)
from chplfmt.printer.body import Body, fits
from chplfmt.printer.common import (
    ends_line,
    header_start,
    open_brace,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.exprs import outer_start
from chplfmt.printer.lists import aligned_expr
from chplfmt.printer.loops import has_comments, keyword_header
from chplfmt.tokens import Node
from chplfmt.trivia import Comment, Placement


def _own(p: Printer, node: Node, word: str) -> list[int]:
    return [i for i in p.index.own_tokens(node) if p.tokens[i].text == word]


def _stmt_else_if(p: Printer, node: chapel.Conditional) -> chapel.Conditional | None:
    """The `if` of `else if` (a brace-less else block holding only a Conditional)."""
    els = node.else_block()
    if els is None or open_brace(p, els) is not None:
        return None
    kids = p.index.children(els)
    if len(kids) == 1 and isinstance(kids[0], chapel.Conditional):
        return kids[0]
    return None


def _in_chain(p: Printer, node: Node) -> bool:
    blk = p.index.parent(node)
    par = None if blk is None else p.index.parent(blk)
    return isinstance(par, chapel.Conditional) and _stmt_else_if(p, par) == node


def _between(p: Printer, node: Node, blk: Node, lo: int, hi: int) -> list[Comment]:
    cs = [*p.dangling(node), *p.dangling(blk)]
    done = set(p.emitted)
    cs += [c for c in p.trivia.leading(blk) if c.token not in done]
    return sorted(
        {c.token: c for c in cs if lo < c.token < hi}.values(), key=lambda c: c.token
    )


def _statement_if(p: Printer, node: chapel.Conditional) -> Doc | None:
    """`if c then S;`, `if c { } else { }`, `else if` chains (sections 7.8, 8.2, 8.3)."""
    first = header_start(p, node)
    then_blk = node.then_block()
    open_t = open_brace(p, then_blk)
    kws = [i for i in _own(p, node, "then") if open_t is None or i < open_t]
    start = kws[0] if kws else open_t
    hl = None if start is None else p.index.prev_code(start)
    if hl is None:
        return None
    opt = p.options.single_statement_body
    nested = _stmt_else_if(p, node)
    chain = nested is not None or _in_chain(p, node)
    mode = "prefer-braces" if chain and opt != "preserve" else opt
    tb = Body(p, node, hl, block=then_blk, keyword="then", mode=mode)
    els = node.else_block()
    if els is None:
        head, broke = keyword_header(p, node, first, hl, node.condition())
        return with_attributes(p, node, tb.doc(head, broke))
    ets = [i for i in _own(p, node, "else") if i > tb.last]
    if not ets:
        return None
    et = ets[0]
    eb = None if nested else Body(p, node, et, block=els, form="bare", mode=mode)
    sp = p.index.node_span(node)
    one_line = (
        mode == "prefer-single-line"
        and eb is not None
        and sp is not None
        and tb.qualifies
        and eb.qualifies
        and not has_comments(p, first, sp[1])
    )
    head, broke = keyword_header(p, node, first, hl, node.condition())
    if one_line and eb is not None:
        flat = concat(head, " then ", tb.statement()[0], " else ", eb.statement()[0])
        one_line = fits(p, flat_width(flat, p.options))
    if one_line and eb is not None:
        d = concat(
            tb.single(head, broke, "keyword"),
            " ",
            eb.single(text("else"), False, "bare"),
        )
        return with_attributes(p, node, d)
    if mode == "preserve":
        then_d = tb.doc(head, broke)
        braced = tb.kind == "braces"
    else:
        then_d = tb.braces(head, broke)
        braced = True
    before = _between(p, node, els, tb.last, et)
    before_d = p.comments_after(before)
    if nested is not None:
        after = _between(p, node, els, et, outer_start(p, nested))
        gap: Doc = text(" ")
        if after and (after[-1].is_line or after[-1].placement is Placement.OWN_LINE):
            gap = hardline
        rest = concat("else", p.comments_after(after), gap, p.print(nested))
    elif eb is not None and mode == "preserve":
        rest = eb.doc(text("else"))
    else:
        assert eb is not None
        rest = eb.braces(text("else"))
    if before:
        sep: Doc = concat(before_d, hardline)
    elif braced and ends_line(p.trivia.trailing(then_blk)):
        sep = text("")
    elif braced:
        # Comments after `else` are the else body's; `before` has the rest.
        nl = p.options.else_placement == "newline" or p.options.brace_style == "break"
        sep = hardline if nl else text(" ")
    else:
        sep = hardline
        w = flat_width(concat(then_d, " ", rest), p.options)
        if mode == "preserve" and (eb is None or eb.kind != "braces") and fits(p, w):
            sep = text(" ")
    return with_attributes(p, node, concat(then_d, sep, rest))


def _branch(p: Printer, block: Node) -> Doc:
    lead = p.leading_comments(block)
    (kid,) = p.index.children(block)
    return concat(lead, p.print(kid), p.trailing_comments(block))


def _else_if(p: Printer, block: Node) -> chapel.Conditional | None:
    """The `if` of an `else if` that joins the enclosing expression's chain."""
    kids = p.index.children(block)
    if len(kids) != 1:
        return None
    k = kids[0]
    if (
        isinstance(k, chapel.Conditional)
        and k.is_expression_level()
        and not p.index.parens_around(k)
        and not p.trivia.leading(k)
        and not p.trivia.trailing(k)
        and not p.trivia.leading(block)
        and not p.trivia.trailing(block)
    ):
        return k
    return None


@printer(chapel.Conditional)
def print_conditional(p: Printer, node: Node) -> Doc | None:
    """Statement- and expression-level `if`."""
    assert isinstance(node, chapel.Conditional)
    if not node.is_expression_level():
        return _statement_if(p, node)
    # Check everything before printing: a fallback must not follow printed children.
    chain = [node]
    while (
        (els := chain[-1].else_block()) is not None
        and not p.dangling(chain[-1], "else")
        and (nested := _else_if(p, els))
    ):
        chain.append(nested)
    for c in chain:
        blocks = [c.then_block(), c.else_block()]
        if len(p.dangling(c)) != len(p.dangling(c, "then", "else")) or any(
            b is not None and len(p.index.children(b)) != 1 for b in blocks
        ):
            return None

    def keyword(c: chapel.Conditional, kw: str, block: Node) -> list[DocLike]:
        cs = p.dangling(c, kw)
        if not cs and not p.trivia.leading(block):
            return [f"{kw} ", _branch(p, block)]
        brk = not cs or cs[-1].is_line or cs[-1].placement is Placement.OWN_LINE
        sep = hardline if brk else text(" ")
        n = p.options.indent_width
        return [kw, indent(concat(p.comments_after(cs), sep, _branch(p, block)), n)]

    parts: list[DocLike] = []
    for k, c in enumerate(chain):
        if k:
            parts += [line, "else if "]
        parts += [aligned_expr(p, c.condition()), line]
        parts += keyword(c, "then", c.then_block())
    last = chain[-1].else_block()
    if last is not None:
        parts += [line, *keyword(chain[-1], "else", last)]
    return group(concat("if ", align(concat(*parts))))
