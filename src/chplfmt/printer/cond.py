"""Printers for Conditional (statement and expression level) (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import Doc, DocLike, align, concat, group, line
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.lists import aligned_expr
from chplfmt.tokens import Node


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
    """Expression-level `if`; statement-level ones fall back (M5d)."""
    assert isinstance(node, chapel.Conditional)
    if not node.is_expression_level():
        return None
    # Check everything before printing: a fallback must not follow printed children.
    chain = [node]
    while (els := chain[-1].else_block()) is not None and (nested := _else_if(p, els)):
        chain.append(nested)
    for c in chain:
        blocks = [c.then_block(), c.else_block()]
        if p.dangling(c) or any(
            b is not None and len(p.index.children(b)) != 1 for b in blocks
        ):
            return None
    parts: list[DocLike] = []
    for k, c in enumerate(chain):
        if k:
            parts += [line, "else if "]
        parts += [
            aligned_expr(p, c.condition()),
            line,
            "then ",
            _branch(p, c.then_block()),
        ]
    last = chain[-1].else_block()
    if last is not None:
        parts += [line, "else ", _branch(p, last)]
    return group(concat("if ", align(concat(*parts))))
