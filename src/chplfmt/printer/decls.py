"""Printers for declarations and functions."""

from __future__ import annotations

from collections.abc import Sequence

from chplfmt._chapel import chapel
from chplfmt.doc import (
    ALL_LINES,
    EMPTY,
    Doc,
    align,
    concat,
    conditional_group,
    fill,
    flat_width,
    hardline,
    text,
)
from chplfmt.doc.ir import DocKind
from chplfmt.offregions import is_statement_list
from chplfmt.printer.body import Body
from chplfmt.printer.common import (
    NO_SPACE_BEFORE,
    header_start,
    semicolon,
    tokens_doc,
    with_attributes,
)
from chplfmt.printer.core import Printer, printer
from chplfmt.printer.lists import (
    BracketList,
    ListKind,
    assignment,
    bracket_layouts,
    list_item,
    list_parts,
)
from chplfmt.tokens import Node

_TIGHT_VARARG = frozenset({"..."})


def _span(p: Printer, node: Node) -> tuple[int, int]:
    sp = p.index.node_span(node)
    assert sp is not None
    return sp


def _own(p: Printer, node: Node, texts: str | tuple[str, ...]) -> list[int]:
    if isinstance(texts, str):
        texts = (texts,)
    return [i for i in p.index.own_tokens(node) if p.tokens[i].text in texts]


def _kids_in(p: Printer, node: Node, first: int, last: int) -> list[Node]:
    out: list[Node] = []
    for k in p.index.children(node):
        sp = p.index.node_span(k)
        if sp is not None and first <= sp[0] and sp[1] <= last:
            out.append(k)
    return out


def _end(p: Printer, node: Node) -> int:
    """Last token of `node`, before its own `;`/`,` (dyno includes it for `type t;`)."""
    last = _span(p, node)[1]
    if p.tokens[last].text in (";", ",") and p.index.owner(last) is node:
        last -= 1
    return last


def _statement(p: Printer, node: Node, d: Doc) -> Doc:
    """`d` with `;` if `node` is a statement, and its attributes."""
    if is_statement_list(p.index.parent(node)):
        d = semicolon(p, node, d)
    return with_attributes(p, node, d)


def _spaced(p: Printer, first: int, d: Doc) -> Doc:
    """`d` (starting at token `first`) preceded by a space unless it is tight."""
    if d.kind is DocKind.CONCAT and not d.parts:
        return d
    return d if p.tokens[first].text in NO_SPACE_BEFORE else concat(" ", d)


def _fits(p: Printer, width: int) -> bool:
    limit = p.options.line_length
    return not limit or p.indent + width <= limit


# Variables


def _init(p: Printer, node: Node) -> tuple[int, Node] | None:
    """The node's own `=` token and the initializer after it."""
    eq = _own(p, node, "=")
    if not eq:
        return None
    for k in p.index.children(node):
        sp = p.index.node_span(k)
        if sp is not None and sp[0] > eq[-1]:
            return eq[-1], k
    return None


def _with_init(p: Printer, node: Node, first: int, last: int) -> Doc:
    """Tokens `first..last` of `node`, with `= init` laid out as an assignment."""
    found = _init(p, node)
    if found is None:
        d, _ = tokens_doc(p, node, first, last)
        return d
    lhs, _ = tokens_doc(p, node, first, found[0] - 1)
    return assignment(p, lhs, "=", found[1])


@printer(chapel.Variable)
def print_variable(p: Printer, node: Node) -> Doc:
    d = _with_init(p, node, header_start(p, node), _end(p, node))
    return _statement(p, node, d)


@printer(chapel.MultiDecl)
def print_multi_decl(p: Printer, node: Node) -> Doc:
    """`var a = 1, b = 2;`: declarations bin-packed after the keywords."""
    decls = [
        k
        for k in p.index.children(node)
        if isinstance(k, chapel.Decl) and p.index.node_span(k) is not None
    ]
    if not decls:
        return p.fallback(node)
    head, broke = tokens_doc(p, node, header_start(p, node), _span(p, decls[0])[0] - 1)
    w = flat_width(head, p.options)
    col = None if broke or w is None else p.indent + w + 1
    with p.nested(0 if col is None or w is None else w + 1):
        items = [list_item(p, k) for k in decls]
        body = align(fill(list_parts(items)))
    if any(it.raw for it in items):
        # Multi-line fallback text can't move: keep the source layout.
        first, last = _span(p, decls[0])[0], _end(p, decls[-1])
        p.emitted[:] = [i for i in p.emitted if not first <= i <= last]
        body = p.raw_tokens(first, last, col=col)
    d = concat(head, body) if broke else concat(head, " ", body)
    return _statement(p, node, d)


@printer(chapel.TupleDecl)
def print_tuple_decl(p: Printer, node: Node) -> Doc:
    """`var (a, b) = t;`, `(x, y): (int, int)` formals, nested tuples."""
    first = header_start(p, node)
    last = _end(p, node)
    opens = _own(p, node, "(")
    if not opens:
        return p.fallback(node)
    open_tok = opens[0]
    close = p.tokens[open_tok].match
    assert close is not None
    decls = _kids_in(p, node, open_tok + 1, close - 1)
    lhs = bracket_layouts(
        p, node, open_tok, decls, ListKind.TUPLE, spacing=p.options.bracket_spacing
    ).doc()
    if open_tok > first:
        head, broke = tokens_doc(p, node, first, open_tok - 1)
        lhs = concat(head, lhs) if broke else concat(head, " ", lhs)
    init = _init(p, node)
    tail_end = init[0] - 1 if init is not None else last
    if close < tail_end:
        tail, _ = tokens_doc(p, node, close + 1, tail_end)
        lhs = concat(lhs, _spaced(p, close + 1, tail))
    d = assignment(p, lhs, "=", init[1]) if init is not None else lhs
    return _statement(p, node, d)


@printer(chapel.ForwardingDecl)
def print_forwarding(p: Printer, node: Node) -> Doc:
    last = _span(p, node)[1]
    if p.tokens[last].text == ";" and p.index.owner(last) is not node:
        # `forwarding x except y;`: the `;` belongs to the VisibilityClause.
        d, _ = tokens_doc(p, node, header_start(p, node), last)
        return with_attributes(p, node, d)
    if p.tokens[last].text == ";":
        last -= 1
    d, _ = tokens_doc(p, node, header_start(p, node), last)
    return _statement(p, node, d)


@printer(chapel.Formal, chapel.AnonFormal, chapel.TaskVar, chapel.ReduceIntent)
def print_formal(p: Printer, node: Node) -> Doc:
    d = _with_init(p, node, header_start(p, node), _span(p, node)[1])
    return with_attributes(p, node, d)


@printer(chapel.VarArgFormal)
def print_var_arg_formal(p: Printer, node: Node) -> Doc:
    d, _ = tokens_doc(
        p, node, header_start(p, node), _span(p, node)[1], tight=_TIGHT_VARARG
    )
    return with_attributes(p, node, d)


# Functions


class _Signature:
    """`pre(formals)post` of a function or function type, with its list layouts."""

    def __init__(self, p: Printer, node: Node, first: int, last: int) -> None:
        self.layouts: BracketList | None = None
        self.post: Doc = EMPTY
        self.broke = False
        open_tok = _formals_open(p, node, first, last)
        if open_tok is None:
            self.pre, self.broke = tokens_doc(p, node, first, last)
            return
        close = p.tokens[open_tok].match
        assert close is not None
        receiver = node.this_formal() if isinstance(node, chapel.Function) else None
        receiver_span = p.index.node_span(receiver) if receiver is not None else None
        if (
            receiver_span is not None
            and first < receiver_span[0] < open_tok
            and p.tokens[receiver_span[0]].text == "("
        ):
            prefix, _ = tokens_doc(p, node, first, receiver_span[0] - 1)
            suffix, _ = tokens_doc(p, node, receiver_span[0], open_tok - 1)
            self.pre = conditional_group(
                [
                    concat(prefix, " ", suffix),
                    concat(prefix, hardline, suffix),
                ],
                ALL_LINES,
            )
        else:
            self.pre, _ = tokens_doc(p, node, first, open_tok - 1)
        formals = _kids_in(p, node, open_tok + 1, close - 1)
        self.layouts = bracket_layouts(p, node, open_tok, formals, ListKind.FIXED)
        if close < last:
            post, self.broke = tokens_doc(p, node, close + 1, last)
            self.post = _spaced(p, close + 1, post)

    def doc(self) -> Doc:
        if self.layouts is None:
            return self.pre
        return concat(self.pre, self.layouts.doc(), self.post)


def _formals_open(p: Printer, node: Node, first: int, last: int) -> int | None:
    if isinstance(node, chapel.Function | chapel.FunctionSignature) and (
        node.is_parenless()
    ):
        return None
    after = first - 1
    if isinstance(node, chapel.Function) and not node.is_anonymous():
        name = p.index.span(node.name_location())
        if name is not None:
            after = name[1]
    opens = [i for i in _own(p, node, "(") if after < i <= last]
    return opens[0] if opens else None


@printer(chapel.FunctionSignature)
def print_function_signature(p: Printer, node: Node) -> Doc:
    sp = _span(p, node)
    return _Signature(p, node, sp[0], sp[1]).doc()


def _clause(p: Printer, node: Node, kw: int, last: int) -> tuple[Doc, bool]:
    """`where cond` / `lifetime a, b` from keyword token `kw` to `last`."""
    kids = _kids_in(p, node, kw + 1, last)
    word = p.tokens[kw].text
    if word == "lifetime" and kids:
        items = [list_item(p, k) for k in kids]
        return concat(word, " ", align(fill(list_parts(items)))), items[-1].breaks_after
    d, broke = tokens_doc(p, node, kw + 1, last)
    return concat(word, " ", align(d)), broke


def _join(docs: Sequence[Doc], sep: Doc) -> Doc:
    parts: list[Doc] = []
    for k, d in enumerate(docs):
        if k:
            parts.append(sep)
        parts.append(d)
    return concat(*parts)


def _header(p: Printer, sig: _Signature, clauses: list[Doc], end_width: int) -> Doc:
    """Lay out the signature and `where`/`lifetime` clauses.

    `end_width` is the width of what ends the last line (` {`, ` do`, `;`).
    """
    if not clauses:
        return sig.doc()
    opts = p.options
    head_w = flat_width(sig.doc(), opts)
    widths = [flat_width(c, opts) for c in clauses]
    shared_w: int | None = None
    if all(w is not None for w in widths):
        shared_w = sum(w for w in widths if w is not None) + len(clauses) - 1
    one_line = _join(clauses, text(" "))
    if (
        head_w is not None
        and shared_w is not None
        and _fits(p, head_w + 1 + shared_w + end_width)
    ):
        return concat(sig.doc(), " ", one_line)
    shared = shared_w is not None and _fits(p, shared_w + end_width)
    lines = one_line if shared else _join(clauses, hardline)
    layouts = sig.layouts
    if layouts is None:
        return concat(sig.pre, hardline, lines)
    fallback_head = concat(sig.pre, layouts.fallback, sig.post)
    # The fallback's `)` line: `) where cond {` if the first clause fits there.
    tail: Doc = concat(hardline, lines)
    close_w = flat_width(concat(")", sig.post), opts)
    if close_w is not None and shared_w is not None:
        w0 = widths[0]
        if _fits(p, close_w + 1 + shared_w + end_width):
            tail = concat(" ", one_line)
        elif w0 is not None and _fits(
            p, close_w + 1 + w0 + (end_width if len(clauses) == 1 else 0)
        ):
            tail = concat(" ", _join(clauses, hardline))
    fallback = concat(fallback_head, tail)
    if layouts.aligned is None:
        return fallback
    aligned = concat(sig.pre, layouts.aligned, sig.post, hardline, lines)
    return conditional_group([aligned, fallback], ALL_LINES)


@printer(chapel.Function)
def print_function(p: Printer, node: Node) -> Doc:
    """proc/iter/operator/lambda: header, clauses, and a braced, `do`, or no body."""
    assert isinstance(node, chapel.Function)
    tokens = p.tokens
    first = header_start(p, node)
    last = _span(p, node)[1]
    body = node.body()
    body_sp = None if body is None else p.index.node_span(body)
    braced = body is not None and any(
        tokens[i].text == "{" for i in p.index.own_tokens(body)
    )
    do_tok = next(iter(_own(p, node, "do")), None)
    semi = [i for i in _own(p, node, ";") if do_tok is None or i > do_tok]
    clause_kws = sorted(_own(p, node, ("where", "lifetime")))
    start = do_tok if do_tok is not None else body_sp[0] if body_sp else None
    b: Body | None = None
    if body is not None and (braced or do_tok is not None) and start is not None:
        prev = p.index.prev_code(start)
        assert prev is not None
        # Lambdas keep their form: `do` bodies can't end inside an expression.
        mode = "preserve" if node.is_anonymous() else None
        b = Body(p, node, prev, block=body, mode=mode)
        end_tok = start
        if b.kind == "braces":
            end_width = 2 if p.options.brace_style == "attach" else 0
        else:
            end_width = 3
    elif semi:
        end_tok, end_width = semi[-1], 1
    else:
        end_tok, end_width = last + 1, 0
    sig = _Signature(p, node, first, (clause_kws[0] if clause_kws else end_tok) - 1)
    clauses: list[Doc] = []
    broke = sig.broke
    for k, kw in enumerate(clause_kws):
        stop = clause_kws[k + 1] - 1 if k + 1 < len(clause_kws) else end_tok - 1
        c, broke = _clause(p, node, kw, stop)
        clauses.append(c)
    header = _header(p, sig, clauses, end_width)
    if b is not None:
        d = b.doc(header, broke)
    elif semi:
        d = semicolon(p, node, header)
    else:
        d = header
    return with_attributes(p, node, d)
