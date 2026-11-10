"""Printers for Module, Class, Record, Union, Interface, Enum, EnumElement (section 8.8)."""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import (
    Doc,
    align,
    concat,
    fill,
    flat_width,
    hardline,
    indent,
    line,
)
from chplfmt.printer.common import (
    HEADER_ANCHORS,
    attach_body,
    braced,
    ends_line,
    header_start,
    open_brace,
    tokens_doc,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.tokens import Node


def _header(p: Printer, node: Node, open_tok: int) -> tuple[Doc, bool]:
    """`[keywords] name[(formals)][: A, B]` with its comments; True if it ends a line."""
    first = header_start(p, node)
    inherit: list[Node] = []
    if isinstance(node, chapel.AggregateDecl):
        inherit = [e for e in node.inherit_exprs() if p.index.node_span(e) is not None]
    if not inherit:
        return tokens_doc(p, node, first, open_tok - 1)
    sp = p.index.node_span(inherit[0])
    assert sp is not None
    colon = p.index.prev_code(sp[0])
    assert colon is not None
    head, _ = tokens_doc(p, node, first, colon - 1)
    parts: list[Doc] = []
    for k, e in enumerate(inherit):
        if k:
            parts.append(line)
        comma = "," if k < len(inherit) - 1 else ""
        parts.append(concat(p.print(e, trailing=False), comma, p.trailing_comments(e)))
    broke = ends_line(p.trivia.trailing(inherit[-1]))
    rest = p.dangling(node, *HEADER_ANCHORS)
    tail = p.comments_after(rest)
    if rest:
        broke = ends_line(rest)
        if broke:
            tail = concat(tail, hardline)
    return concat(head, ": ", align(fill(parts)), tail), broke


@printer(chapel.Module, chapel.Class, chapel.Record, chapel.Union, chapel.Interface)
def print_braced_decl(p: Printer, node: Node) -> Doc:
    open_tok = open_brace(p, node)
    if open_tok is None:
        return p.fallback(node)
    header, broke = _header(p, node, open_tok)
    body = braced(p, node, open_tok)
    return with_attributes(
        p, node, attach_body(p, header, body, header_ends_line=broke)
    )


@printer(chapel.EnumElement)
def print_enum_element(p: Printer, node: Node) -> Doc:
    sp = p.index.node_span(node)
    assert sp is not None
    d, _ = tokens_doc(p, node, header_start(p, node), sp[1], anchors=())
    return with_attributes(p, node, d)


@printer(chapel.Enum)
def print_enum(p: Printer, node: Node) -> Doc:
    """Flat `enum E { a, b }` if it fits without forced breaks, else one per line."""
    open_tok = open_brace(p, node)
    if open_tok is None:
        return p.fallback(node)
    close = p.tokens[open_tok].match
    assert close is not None
    tokens = p.tokens
    opts = p.options
    header, broke = tokens_doc(p, node, header_start(p, node), open_tok - 1)
    after_open = p.comments_after(p.dangling(node, "{"))
    elems: list[Node] = []
    for k in p.index.children(node):
        sp = p.index.node_span(k)
        if isinstance(k, chapel.EnumElement) and sp is not None and sp[0] > open_tok:
            elems.append(k)
    last_code = p.index.prev_code(close)
    assert last_code is not None
    had_comma = tokens[last_code].text == ","
    # (element with leading comments, its trailing comments, blank lines before)
    pieces: list[tuple[Doc, Doc, int]] = []
    with p.nested() as n:
        for e in elems:
            lead = p.trivia.leading(e)
            sp = p.index.node_span(e)
            assert sp is not None
            nl = tokens[lead[0].token if lead else sp[0]].nl_before
            pieces.append(
                (
                    concat(
                        p.leading_comments(e), p.print(e, leading=False, trailing=False)
                    ),
                    p.comments_after(p.trivia.trailing(e)),
                    min(max(nl - 1, 0), opts.max_blank_lines),
                )
            )
        rest = p.comments_after(p.dangling(node))

    def items(last_comma: bool) -> list[Doc]:
        last = len(pieces) - 1
        return [
            concat(d, "," if k < last or last_comma else "", trail)
            for k, (d, trail, _) in enumerate(pieces)
        ]

    flat = concat(
        header,
        " {",
        after_open,
        *(concat(" ", d) for d in items(had_comma and not opts.trailing_comma)),
        rest,
        " }",
    )
    if not broke and not flat.forced and _fits(p, flat):
        if opts.trailing_comma and had_comma:
            p.record("trailing-comma", last_code)
        return with_attributes(p, node, flat)
    if opts.trailing_comma and not had_comma:
        p.record("trailing-comma", last_code)
    lines: list[Doc] = []
    for d, (_, _, gap) in zip(
        items(opts.trailing_comma or had_comma), pieces, strict=True
    ):
        lines += [hardline] * (gap + 1 if lines else 1)
        lines.append(d)
    block = concat("{", after_open, indent(concat(*lines, rest), n), hardline, "}")
    return with_attributes(
        p, node, attach_body(p, header, block, header_ends_line=broke)
    )


def _fits(p: Printer, flat: Doc) -> bool:
    width = p.options.line_length
    if not width:
        return True
    w = flat_width(flat, p.options)
    return w is not None and p.indent + w <= width
