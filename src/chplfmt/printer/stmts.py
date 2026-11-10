"""Printers for Block, Return, Yield, Break, Continue, Throw, Delete, EmptyStmt, Label, Defer, Begin, Cobegin, Sync, Serial, Local, On, Manage, Try, Catch, Select, When, Use, Import, VisibilityClause, As, Include, Require, Implements, ExternBlock, Init (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

import itertools
from contextlib import ExitStack

from chplfmt._chapel import chapel
from chplfmt.doc import EMPTY, Doc, concat, conditional_group, hardline, indent, text
from chplfmt.printer.body import Body, Form
from chplfmt.printer.common import (
    attach_body,
    attribute_group,
    body_statements,
    braced,
    ends_line,
    header_start,
    open_brace,
    semicolon,
    tokens_doc,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.exprs import outer_start, token_text
from chplfmt.printer.lists import (
    ListKind,
    aligned_expr,
    bracket_layouts,
    bracket_list,
    list_fill,
)
from chplfmt.tokens import Node
from chplfmt.trivia import Placement


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


# Statements with bodies (sections 7.8, 8.2, 8.3, 8.9)


def _before(p: Printer, i: int) -> int:
    j = p.index.prev_code(i)
    assert j is not None
    return j


def _header_last(p: Printer, node: Node, first: int, kids: list[Node]) -> int | None:
    """Last header token: before the node's own `do`/`{`, else before its first body statement."""
    own = [
        i
        for i in p.index.own_tokens(node)
        if i > first and p.tokens[i].text in ("do", "{")
    ]
    if own:
        start = own[0]
    elif kids:
        start = outer_start(p, kids[0])
    else:
        return None
    return _before(p, start)


@printer(
    chapel.Begin,
    chapel.Cobegin,
    chapel.Sync,
    chapel.Defer,
    chapel.Serial,
    chapel.Local,
    chapel.On,
    chapel.Manage,
)
def print_block_stmt(p: Printer, node: Node) -> Doc | None:
    """`begin with (...) S;`, `sync { }`, `on x do S;`, `cobegin { }`, ..."""
    first = header_start(p, node)
    head: list[Node] = []
    if isinstance(node, chapel.Begin | chapel.Cobegin):
        wc = node.with_clause()
        head = [] if wc is None else [wc]
    elif isinstance(node, chapel.Serial | chapel.Local):
        cond = node.condition()
        head = [] if cond is None else [cond]
    elif isinstance(node, chapel.On):
        head = [node.destination()]
    elif isinstance(node, chapel.Manage):
        head = list(node.managers())
    attrs = attribute_group(p, node)
    body_kids = [k for k in _kids(p, node) if k is not attrs and k not in head]
    hl = _header_last(p, node, first, body_kids)
    if hl is None:
        return None
    header, broke = tokens_doc(p, node, first, hl)
    form: Form = (
        "block"
        if isinstance(node, chapel.Cobegin)
        else "bare"
        if isinstance(node, chapel.Begin | chapel.Sync | chapel.Defer)
        else "keyword"
    )
    return with_attributes(p, node, Body(p, node, hl, form=form).doc(header, broke))


@printer(chapel.When)
def print_when(p: Printer, node: Node) -> Doc | None:
    """`when 1, 2 do S;`, `when x { }`, `otherwise do S;`."""
    assert isinstance(node, chapel.When)
    blk = node.body()
    first = header_start(p, node)
    starts = [
        i
        for i in [*p.index.own_tokens(node), *p.index.structural_brackets(blk)]
        if i > first and p.tokens[i].text in ("do", "{")
    ]
    if not starts:
        return None
    hl = _before(p, min(starts))
    header, broke = tokens_doc(p, node, first, hl)
    return with_attributes(p, node, Body(p, node, hl, block=blk).doc(header, broke))


@printer(chapel.Select)
def print_select(p: Printer, node: Node) -> Doc | None:
    first = header_start(p, node)
    open_tok = open_brace(p, node)
    if open_tok is None:
        return None
    header, broke = tokens_doc(p, node, first, _before(p, open_tok))
    whens = body_statements(p, node, open_tok)
    d = attach_body(p, header, braced(p, node, open_tok, whens), header_ends_line=broke)
    return with_attributes(p, node, d)


def _block_child(p: Printer, node: Node) -> Node | None:
    return next(
        (k for k in p.index.children(node) if isinstance(k, chapel.Block)), None
    )


def _after_block(p: Printer, prev: Node, nxt: Node) -> Doc:
    """What separates `}` of `prev` from `catch` (`else-placement`, `brace-style`)."""
    if ends_line(p.trivia.trailing(prev)):
        return EMPTY
    if (
        p.options.else_placement == "newline"
        or p.options.brace_style == "break"
        or any(c.placement is Placement.OWN_LINE for c in p.trivia.leading(nxt))
    ):
        return hardline
    return text(" ")


@printer(chapel.Try)
def print_try(p: Printer, node: Node) -> Doc | None:
    """`try { } catch e: E { } catch { }`; `try! f();` and `try! f()` (expression)."""
    assert isinstance(node, chapel.Try)
    blk = _block_child(p, node)
    if blk is None:
        return print_simple(p, node)
    first = header_start(p, node)
    header = text(p.tokens[first].text)
    d = Body(p, node, first, block=blk, form="block").doc(header)
    prev: Node = blk
    for c in node.handlers():
        d = concat(d, _after_block(p, prev, c), p.print(c))
        prev = c
    return with_attributes(p, node, d)


@printer(chapel.Catch)
def print_catch(p: Printer, node: Node) -> Doc | None:
    """`catch`, `catch e`, `catch e: E`, `catch (e: E)` and a braced body."""
    assert isinstance(node, chapel.Catch)
    blk = node.body()
    first = header_start(p, node)
    open_tok = open_brace(p, blk)
    if open_tok is None:
        return None
    hl = _before(p, open_tok)
    header: Doc = text("catch")
    broke = False
    if hl > first:
        rest, broke = tokens_doc(p, node, first + 1, hl)
        header = concat("catch ", rest)
    d = Body(p, node, hl, block=blk, form="block").doc(header, broke)
    return with_attributes(p, node, d)


@printer(chapel.WithClause)
def print_with_clause(p: Printer, node: Node) -> Doc | None:
    """`with (ref x, + reduce y)`: never the break-after-`(` fallback (section 8.7)."""
    opens = [i for i in p.index.own_tokens(node) if p.tokens[i].text == "("]
    if not opens:
        return None
    kids = [k for k in p.index.children(node) if p.index.node_span(k) is not None]
    layouts = bracket_layouts(p, node, opens[0], kids, ListKind.FIXED)
    lst = layouts.doc() if layouts.aligned is None else layouts.aligned
    d = p.dangling_comments(node, "header")
    return concat("with", d, " ", lst)


def with_header(p: Printer, before: Doc, clause: Doc) -> Doc:
    """`before with (...)`; the clause starts its own line (at the current
    indentation) if `with (` and its first intent don't fit after `before`."""
    return conditional_group(
        [concat(before, " ", clause), concat(before, hardline, clause)]
    )
