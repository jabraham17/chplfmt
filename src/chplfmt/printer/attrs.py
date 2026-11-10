"""Printers for AttributeGroup and Attribute (pragmas included) (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import Doc, concat, hardline, text
from chplfmt.printer.common import tokens_doc
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.exprs import actual_items
from chplfmt.printer.lists import bracket_list
from chplfmt.tokens import Node
from chplfmt.trivia import Placement


@printer(chapel.AttributeGroup)
def print_attribute_group(p: Printer, node: Node) -> Doc:
    """Pragmas and attributes in source order, one per line (section 8.10)."""
    sp = p.index.node_span(node)
    assert sp is not None
    tokens = p.tokens
    kids: dict[int, tuple[Node, int]] = {}
    for k in p.index.children(node):
        ks = p.index.node_span(k)
        if ks is not None:
            kids[ks[0]] = (k, ks[1])
    dangling = {c.token: c for c in p.dangling(node)}
    parts: list[Doc] = []
    i = sp[0]
    while i <= sp[1]:
        kid = kids.get(i)
        if kid is not None:
            lead = p.trivia.leading(kid[0])
            eol = bool(lead) and lead[0].placement is Placement.END_OF_LINE
            if parts and not (eol and lead[0].is_line):
                parts.append(hardline)
            parts.append(p.print(kid[0], trailing=False))
            parts.append(p.comments_after(p.trivia.trailing(kid[0])))
            i = kid[1] + 1
            continue
        tok = tokens[i]
        if tok.is_comment:
            c = dangling.get(i)
            if c is not None:
                parts.append(p.comments_after([c]))
            i += 1
            continue
        if parts:
            parts.append(hardline)
        if tok.text == "pragma":
            j = p.index.next_code(i)
            pre = [dangling[t] for t in range(i + 1, j) if t in dangling]
            parts += [text("pragma"), p.comments_after(pre), text(" " + tokens[j].text)]
            i = j + 1
        else:
            parts.append(text(tok.text))
            i += 1
    return concat(*parts)


@printer(chapel.Attribute)
def print_attribute(p: Printer, node: Node) -> Doc:
    """`@name`, `@a.b`, `@name(args)`; named actuals as `since="2.0"`."""
    sp = p.index.node_span(node)
    assert sp is not None
    brackets = p.index.structural_brackets(node)
    if brackets and brackets[0] > sp[0]:
        open_tok = brackets[0]
        name, _ = tokens_doc(
            p, node, sp[0], open_tok - 1, tight=frozenset({"="}), anchors=()
        )
        if not p.tokens[open_tok - 1].is_comment:
            items = actual_items(p, node, open_tok)
            return concat(name, bracket_list(p, node, open_tok, items))
    d, _ = tokens_doc(p, node, sp[0], sp[1], tight=frozenset({"="}), anchors=())
    return d
