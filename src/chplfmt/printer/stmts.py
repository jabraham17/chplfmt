"""Printers for Block, Return, Yield, Break, Continue, Throw, Delete, EmptyStmt, Label, Defer, Begin, Cobegin, Sync, Serial, Local, On, Manage, Try, Catch, Select, When, Use, Import, VisibilityClause, As, Include, Require, Implements, ExternBlock, Init (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

import itertools
from contextlib import ExitStack

from chplfmt._chapel import chapel
from chplfmt.doc import Doc, concat, hardline, indent
from chplfmt.printer.common import braced
from chplfmt.printer.core import Printer, printer
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
