"""Printers for identifiers, literals, calls, and other non-operator expressions (section 7.7)."""

from __future__ import annotations

from collections.abc import Callable

from chplfmt._chapel import chapel
from chplfmt.doc import (
    EMPTY,
    Doc,
    align,
    concat,
    fill,
    group,
    hardline,
    line,
    text,
    verbatim,
)
from chplfmt.lexer import TokenKind
from chplfmt.offregions import is_statement_list
from chplfmt.printer.common import semicolon, tokens_doc
from chplfmt.printer.core import Printer, PrintFn
from chplfmt.printer.core import printer as _register
from chplfmt.printer.lists import (
    ListItem,
    ListKind,
    bracket_list,
    list_item,
    list_parts,
)
from chplfmt.tokens import Node


def statement(p: Printer, node: Node, d: Doc) -> Doc:
    """`d` with its `;` if `node` is an expression statement."""
    if not is_statement_list(p.index.parent(node)):
        return d
    sp, stmt = p.index.node_span(node), p.index.stmt_span(node)
    if stmt is None or stmt == sp or p.tokens[stmt[1]].text != ";":
        return d
    return semicolon(p, node, d)


def printer(*classes: type) -> Callable[[PrintFn], PrintFn]:
    """`core.printer` for expressions, which may also be statements."""

    def register(fn: PrintFn) -> PrintFn:
        def wrapped(p: Printer, node: Node) -> Doc:
            return statement(p, node, fn(p, node))

        _register(*classes)(wrapped)
        return fn

    return register


def token_text(p: Printer, i: int) -> Doc:
    """Token `i` as text; a multi-line string is emitted byte-for-byte."""
    s = p.tokens[i].text
    return verbatim(s) if "\n" in s else text(s)


def own_code(p: Printer, node: Node) -> list[int]:
    """The node's own non-comment tokens."""
    return [i for i in p.index.own_tokens(node) if not p.tokens[i].is_comment]


@printer(chapel.Identifier, chapel.Literal)
def print_leaf(p: Printer, node: Node) -> Doc:
    sp = p.index.node_span(node)
    return EMPTY if sp is None else token_text(p, sp[0])


@printer(chapel.TypeQuery, chapel.Let)
def print_tokens(p: Printer, node: Node) -> Doc:
    sp = p.index.node_span(node)
    if sp is None:
        return EMPTY
    d, _ = tokens_doc(p, node, sp[0], sp[1])
    return d


def outer_start(p: Printer, node: Node) -> int:
    """First token of `node`, including the user parentheses around it."""
    layers = p.index.parens_around(node)
    if layers:
        return layers[-1][0]
    sp = p.index.node_span(node)
    assert sp is not None
    return sp[0]


def actual_items(p: Printer, call: Node, open_tok: int) -> list[ListItem]:
    """The actuals inside the call's `open_tok`, with `name=` for named ones."""
    items: list[ListItem] = []
    for a in p.index.children(call):
        if p.index.node_span(a) is None or outer_start(p, a) <= open_tok:
            continue
        prefix = EMPTY
        eq = p.index.prev_code(outer_start(p, a))
        if (
            eq is not None
            and eq > open_tok
            and p.tokens[eq].text == "="
            and p.index.owner(eq) == call
            and (name := p.index.prev_code(eq)) is not None
            and p.tokens[name].kind is TokenKind.IDENT
        ):
            prefix = text(p.tokens[name].text + "=")
        items.append(list_item(p, a, prefix))
    return items


@printer(chapel.FnCall)
def print_fn_call(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.FnCall)
    called = node.called_expression()
    callee = p.print(called)
    brackets = p.index.structural_brackets(node)
    if not brackets:
        # Keyword-like calls: `owned C`, `sync int`, `sparse subdomain(D)`.
        parts = [callee]
        for a in p.index.children(node):
            if a != called:
                parts += [text(" "), p.print(a)]
        return concat(*parts)
    open_tok = brackets[0]
    items = actual_items(p, node, open_tok)
    return concat(callee, bracket_list(p, node, open_tok, items))


@printer(chapel.PrimCall)
def print_prim_call(p: Printer, node: Node) -> Doc:
    own = own_code(p, node)
    open_tok = p.index.structural_brackets(node)[0]
    name = next(i for i in own if i > open_tok and p.tokens[i].kind is TokenKind.STRING)
    items: list[ListItem | Node] = [ListItem(lead=EMPTY, body=token_text(p, name))]
    items.extend(p.index.children(node))
    return concat(token_text(p, own[0]), bracket_list(p, node, open_tok, items))


@printer(chapel.Dot)
def print_dot(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.Dot)
    own = own_code(p, node)
    dot = next(i for i in own if p.tokens[i].text == ".")
    field = next(i for i in own if i > dot)
    return concat(p.print(node.receiver()), ".", token_text(p, field))


@printer(chapel.New)
def print_new(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.New)
    words = [
        p.tokens[i].text
        for i in own_code(p, node)
        if p.tokens[i].kind is TokenKind.IDENT
    ]
    return concat(" ".join(words), " ", p.print(node.type_expression()))


@printer(chapel.Range)
def print_range(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.Range)
    op = next(i for i in own_code(p, node) if p.tokens[i].text.startswith(".."))
    lo, hi = node.lower_bound(), node.upper_bound()
    return concat(
        EMPTY if lo is None else p.print(lo),
        p.tokens[op].text,
        EMPTY if hi is None else p.print(hi),
    )


@printer(chapel.Reduce, chapel.Scan)
def print_reduce(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.Reduce | chapel.Scan)
    kw = next(i for i in own_code(p, node) if p.tokens[i].text in ("reduce", "scan"))
    op, iterand = p.print(node.op()), p.print(node.iterand())
    return concat(op, " ", p.tokens[kw].text, " ", iterand)


def _literal(p: Printer, node: Node, kind: ListKind) -> Doc:
    open_tok = p.index.structural_brackets(node)[0]
    items = p.index.children(node)
    spacing = p.options.bracket_spacing
    return bracket_list(p, node, open_tok, items, kind, spacing=spacing)


@printer(chapel.Domain)
def print_domain(p: Printer, node: Node) -> Doc:
    return _literal(p, node, ListKind.TRAILING)


@printer(chapel.Tuple)
def print_tuple(p: Printer, node: Node) -> Doc:
    return _literal(p, node, ListKind.TUPLE)


@printer(chapel.Array)
def print_array(p: Printer, node: Node) -> Doc:
    rows = p.index.children(node)
    if not any(isinstance(r, chapel.ArrayRow) for r in rows):
        return _literal(p, node, ListKind.TRAILING)
    open_tok = p.index.structural_brackets(node)[0]
    close = p.tokens[open_tok].match
    assert close is not None
    if any(p.tokens[i].is_comment for i in range(open_tok + 1, close)):
        return p.raw_tokens(open_tok, close)
    # A row that started a line in the source keeps doing so.
    parts: list[Doc] = []
    for k, row in enumerate(rows):
        sp = p.index.node_span(row)
        assert sp is not None
        if k:
            parts.append(hardline if p.tokens[sp[0]].nl_before else line)
        semi = p.index.next_code(sp[1])
        parts.append(concat(p.print(row), ";" if p.tokens[semi].text == ";" else ""))
    pad = " " if p.options.bracket_spacing else ""
    return group(concat("[", pad, align(fill(parts)), pad, "]"))


@printer(chapel.ArrayRow)
def print_array_row(p: Printer, node: Node) -> Doc:
    return fill(list_parts([list_item(p, k) for k in p.index.children(node)]))
