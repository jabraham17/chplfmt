"""Printers for Block, Return, Yield, Break, Continue, Throw, Delete, EmptyStmt, Label, Defer, Begin, Cobegin, Sync, Serial, Local, On, Manage, Try, Catch, Select, When, Use, Import, VisibilityClause, As, Include, Require, Implements, ExternBlock, Init (section 7.7).

Register with `@printer(chapel.Kind)` from `chplfmt.printer.core`.
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.doc import Doc
from chplfmt.printer.common import braced, open_brace
from chplfmt.printer.core import Printer, printer
from chplfmt.tokens import Node


@printer(chapel.Block)
def print_block(p: Printer, node: Node) -> Doc:
    """`{ ... }`; brace-less blocks fall back (M5e)."""
    open_tok = open_brace(p, node)
    if open_tok is None:
        return p.fallback(node)
    return braced(p, node, open_tok, anchors=())
