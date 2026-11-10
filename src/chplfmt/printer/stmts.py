"""Printers for Block, Return, Yield, Break, Continue, Throw, Delete, EmptyStmt, Label, Defer, Begin, Cobegin, Sync, Serial, Local, On, Manage, Try, Catch, Select, When, Use, Import, VisibilityClause, As, Include, Require, Implements, ExternBlock, Init (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

import itertools
from contextlib import ExitStack

from chplfmt._chapel import chapel
from chplfmt.doc import EMPTY, Doc, concat, hardline, indent, text
from chplfmt.printer.common import (
    attribute_group,
    braced,
    header_start,
    semicolon,
    tokens_doc,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.exprs import outer_start, token_text
from chplfmt.printer.lists import aligned_expr, bracket_list, list_fill
from chplfmt.tokens import Node


@printer(chapel.Block)
def print_block(p: Printer, node: Node) -> Doc:
    """`{ ... }`; brace-less blocks fall back (M5e).

    dyno merges `{ { ... } }` in a function body into one Block owning both pairs.
    """
    braces = [i for i in p.index.own_tokens(node) if p.tokens[i].text == "{"]
    if not braces:
        return p.fallback(node)
    for a, b in itertools.pairwise(braces):
        if p.index.next_code(a) != b:
            return p.fallback(node)
    with ExitStack() as stack:
        widths = [stack.enter_context(p.nested()) for _ in braces[1:]]
        d = braced(p, node, braces[-1], anchors=())
    for n in reversed(widths):
        d = concat("{", indent(concat(hardline, d), n), hardline, "}")
    return d


# Simple statements (sections 8.9, 8.12)


def _bounds(p: Printer, node: Node) -> tuple[int, int, bool] | None:
    """First token after attributes, last token before the node's own `;`, and whether it has one."""
    sp = p.index.node_span(node)
    if sp is None:
        return None
    last = sp[1]
    semi = p.tokens[last].text == ";" and p.index.owner(last) is node
    return header_start(p, node), last - 1 if semi else last, semi


def _kids(p: Printer, node: Node) -> list[Node]:
    group = attribute_group(p, node)
    return [
        k
        for k in p.index.children(node)
        if k is not group and p.index.node_span(k) is not None
    ]


def _prefix(p: Printer, node: Node, first: int, stop: int) -> Doc:
    """Tokens `first..stop-1` followed by a space (or the line break of a `//` comment)."""
    if first >= stop:
        return EMPTY
    d, broke = tokens_doc(p, node, first, stop - 1)
    return d if broke else concat(d, " ")


def _finish(p: Printer, node: Node, d: Doc, semi: bool) -> Doc:
    return with_attributes(p, node, semicolon(p, node, d) if semi else d)


def _own_code(p: Printer, node: Node, first: int, last: int) -> list[str]:
    return [
        p.tokens[i].text
        for i in p.index.own_tokens(node)
        if first <= i <= last and not p.tokens[i].is_comment
    ]


@printer(
    chapel.Break,
    chapel.Continue,
    chapel.Include,
    chapel.Implements,
    chapel.Init,
    chapel.Label,
    chapel.As,
)
def print_simple(p: Printer, node: Node) -> Doc | None:
    """Keywords and children separated by single spaces."""
    b = _bounds(p, node)
    if b is None:
        return None
    first, last, semi = b
    d, _ = tokens_doc(p, node, first, last)
    return _finish(p, node, d, semi)


@printer(chapel.Return, chapel.Yield, chapel.Throw)
def print_return(p: Printer, node: Node) -> Doc | None:
    """`return x;`: a wrapped value lines up after `return `."""
    b = _bounds(p, node)
    if b is None:
        return None
    first, last, semi = b
    kids = _kids(p, node)
    if not kids:
        d, _ = tokens_doc(p, node, first, last)
        return _finish(p, node, d, semi)
    if len(kids) != 1:
        return None
    start = outer_start(p, kids[0])
    d = concat(_prefix(p, node, first, start), aligned_expr(p, kids[0]))
    return _finish(p, node, d, semi)


@printer(chapel.Use, chapel.Import, chapel.Delete, chapel.Require)
def print_list_stmt(p: Printer, node: Node) -> Doc | None:
    """`use A, B;`: items bin-packed, aligned after the keyword."""
    b = _bounds(p, node)
    kids = _kids(p, node)
    if b is None or not kids:
        return None
    first, last, semi = b
    start = outer_start(p, kids[0])
    if any(t != "," for t in _own_code(p, node, start, last)):
        return None
    d = concat(_prefix(p, node, first, start), list_fill(p, kids))
    return _finish(p, node, d, semi)


@printer(chapel.VisibilityClause)
def print_visibility_clause(p: Printer, node: Node) -> Doc | None:
    """`M`, `M only a, b`, `M except a`, `M.{a, b}` (also `forwarding x except y;`)."""
    b = _bounds(p, node)
    kids = _kids(p, node)
    if b is None or not kids:
        return None
    first, last, semi = b
    sym, limits = kids[0], kids[1:]
    start = outer_start(p, sym)
    own = [
        i
        for i in p.index.own_tokens(node)
        if start <= i <= last and not p.tokens[i].is_comment
    ]
    texts = [p.tokens[i].text for i in own]
    if texts[:2] == [".", "{"]:
        if any(t != "," for t in texts[2:-1]) or texts[-1] != "}":
            return None
        tail = concat(".", bracket_list(p, node, own[1], limits))
    elif texts and texts[0] in ("only", "except"):
        if any(t != "," for t in texts[1:]):
            return None
        tail = concat(" ", texts[0])
        if limits:
            tail = concat(tail, " ", list_fill(p, limits))
    elif not texts and not limits:
        tail = EMPTY
    else:
        return None
    d = concat(_prefix(p, node, first, start), p.print(sym), tail)
    return semicolon(p, node, d) if semi else concat(d, p.dangling_comments(node))


@printer(chapel.ExternBlock)
def print_extern_block(p: Printer, node: Node) -> Doc | None:
    own = [i for i in p.index.own_tokens(node) if not p.tokens[i].is_comment]
    if len(own) != 1:
        return None
    return token_text(p, own[0])


@printer(chapel.EmptyStmt)
def print_empty_stmt(p: Printer, node: Node) -> Doc:
    return text(";")
