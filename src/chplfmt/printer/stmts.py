"""Printers for Block, Return, Yield, Break, Continue, Throw, Delete, EmptyStmt, Label, Defer, Begin, Cobegin, Sync, Serial, Local, On, Manage, Try, Catch, Select, When, Use, Import, VisibilityClause, As, Include, Require, Implements, ExternBlock, Init.

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

import itertools
from contextlib import ExitStack

from chplfmt._chapel import chapel
from chplfmt.doc import (
    ALL_LINES,
    EMPTY,
    Doc,
    concat,
    conditional_group,
    flat_width,
    group,
    hardline,
    indent,
    line,
    text,
)
from chplfmt.printer.body import Body, Form
from chplfmt.printer.common import (
    after_block,
    attach_body,
    attribute_group,
    body_statements,
    braced,
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
    list_item,
)
from chplfmt.tokens import Node


@printer(chapel.Block)
def print_block(p: Printer, node: Node) -> Doc:
    """`{ ... }`; brace-less blocks fall back.

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


# Simple statements


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


# Statements with bodies


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
        else (
            "bare"
            if isinstance(node, chapel.Begin | chapel.Sync | chapel.Defer)
            else "keyword"
        )
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
    if starts:
        hl = _before(p, min(starts))
    elif (kids := list(p.index.children(blk))) and p.tokens[first].text == "otherwise":
        # `otherwise S;` without `do`.
        hl = _before(p, outer_start(p, kids[0]))
    else:
        return None
    cases = list(node.case_exprs())
    if (
        cases
        and p.tokens[first].text == "when"
        and not any(p.tokens[i].is_comment for i in range(first, hl + 1))
    ):
        header, broke = concat("when ", list_fill(p, cases)), False
    else:
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


@printer(chapel.Match)
def print_match(p: Printer, node: Node) -> Doc | None:
    first = header_start(p, node)
    open_tok = next(
        (i for i in p.index.own_tokens(node) if p.tokens[i].text == "{"), None
    )
    if open_tok is None:
        return None
    header, broke = _match_header(p, node, node, first, open_tok)
    cases = body_statements(p, node, open_tok)
    d = attach_body(p, header, braced(p, node, open_tok, cases), header_ends_line=broke)
    return with_attributes(p, node, d)


@printer(chapel.MatchCase)
def print_match_case(p: Printer, node: Node) -> Doc | None:
    blk = _block_child(p, node)
    if blk is None:
        return None
    first = header_start(p, node)
    open_tok = open_brace(p, blk)
    if open_tok is None:
        do_tok = next(
            (i for i in p.index.own_tokens(node) if p.tokens[i].text == "do"), None
        )
        if do_tok is None:
            return None
        hl = _before(p, do_tok)
        header, broke = tokens_doc(p, node, first, hl)
        return with_attributes(p, node, Body(p, node, hl, block=blk).doc(header, broke))
    hl = _before(p, open_tok)
    header, broke = _match_header(p, node, blk, first, open_tok)
    return with_attributes(
        p, node, Body(p, node, hl, block=blk, form="block").doc(header, broke)
    )


def _match_header(
    p: Printer, node: Node, brace_owner: Node, first: int, open_tok: int
) -> tuple[Doc, bool]:
    header, broke = tokens_doc(p, node, first, _before(p, open_tok))
    before = [c for c in p.dangling(brace_owner, "{") if c.token < open_tok]
    if before:
        header = concat(header, p.comments_after(before))
        if before[-1].is_line:
            header = concat(header, hardline)
            broke = True
    return header, broke


def _block_child(p: Printer, node: Node) -> Node | None:
    return next(
        (k for k in p.index.children(node) if isinstance(k, chapel.Block)), None
    )


@printer(chapel.Try)
def print_try(p: Printer, node: Node) -> Doc | None:
    """`try { } catch e: E { } catch { }`; `try! f();` and `try! f()` (expression)."""
    assert isinstance(node, chapel.Try)
    blk = _block_child(p, node)
    if blk is None:
        if node.is_expression_level() and len(kids := _kids(p, node)) == 1:
            first = header_start(p, node)
            return group(
                concat(
                    p.tokens[first].text,
                    indent(
                        concat(line, p.print(kids[0])),
                        p.options.continuation_indent,
                    ),
                )
            )
        return print_simple(p, node)
    first = header_start(p, node)
    header = text(p.tokens[first].text)
    d = Body(p, node, first, block=blk, form="block").doc(header)
    prev: Node = blk
    for c in node.handlers():
        sep = after_block(p, prev, c)
        handler = p.print(c)
        if flat_width(sep, p.options) == 1:
            d = conditional_group(
                [concat(d, " ", handler), concat(d, hardline, handler)], ALL_LINES
            )
        else:
            d = concat(d, sep, handler)
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
        header = conditional_group(
            [
                concat("catch ", rest),
                concat(
                    "catch",
                    indent(concat(hardline, rest), p.options.continuation_indent),
                ),
            ],
            ALL_LINES,
        )
    d = Body(p, node, hl, block=blk, form="block").doc(header, broke)
    return with_attributes(p, node, d)


def with_clause(p: Printer, node: Node) -> tuple[Doc, int | None] | None:
    """`with (ref x, + reduce y)` and the flat width of `with (` + first intent + `,`/`)`.

    The width is None when comments are involved.
    """
    opens = [i for i in p.index.own_tokens(node) if p.tokens[i].text == "("]
    if not opens:
        return None
    kids = [k for k in p.index.children(node) if p.index.node_span(k) is not None]
    quiet = not p.dangling(node)
    items = [list_item(p, k) for k in kids]
    layouts = bracket_layouts(p, node, opens[0], items, ListKind.FIXED)
    lst = layouts.doc() if layouts.aligned is None else layouts.aligned
    d = p.dangling_comments(node, "header")
    first_w = None
    if items and quiet:
        w = flat_width(concat(items[0].lead, items[0].body), p.options)
        first_w = None if w is None else w + len("with (") + 1
    return concat("with", d, " ", lst), first_w


@printer(chapel.WithClause)
def print_with_clause(p: Printer, node: Node) -> Doc | None:
    """`with (ref x, + reduce y)`: never the break-after-`(` fallback."""
    wc = with_clause(p, node)
    return None if wc is None else wc[0]


def with_header(p: Printer, before: Doc, clause: Doc) -> Doc:
    """`before with (...)`; the clause starts its own line (at the current
    indentation) if `with (` and its first intent don't fit after `before`."""
    return conditional_group(
        [concat(before, " ", clause), concat(before, hardline, clause)]
    )
