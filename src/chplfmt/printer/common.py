"""Helpers shared by construct printers: braced bodies, attributes, `;`, token runs."""

from __future__ import annotations

from collections.abc import Sequence

from chplfmt._chapel import chapel
from chplfmt.doc import Doc, concat, hardline, indent, text
from chplfmt.printer.core import Printer
from chplfmt.tokens import Node
from chplfmt.trivia import Comment, Placement

# Anchor kinds of dangling comments that sit in a header (before `{`).
HEADER_ANCHORS = ("", "header", "(", "[", "then", "else")

NO_SPACE_BEFORE = frozenset({",", ")", "]", ":", ";", ".", "(", "["})
NO_SPACE_AFTER = frozenset({"(", "[", "."})
# Tokens after which an open bracket is spaced (`x: [D] int`, `= (1, 2)`).
SPACE_BEFORE_OPEN = frozenset(
    {":", "=", ",", "where", "lifetime", "return", "proc", "iter", "operator", "ref"}
    | {"const", "param", "type"}
)


def ends_line(cs: Sequence[Comment]) -> bool:
    """Whether printing `cs` ends with an own-line `//` comment (a break must follow)."""
    return bool(cs) and cs[-1].is_line and cs[-1].placement is Placement.OWN_LINE


def attribute_group(p: Printer, node: Node) -> Node | None:
    """The node's AttributeGroup, if it has tokens (attributes or pragmas)."""
    return next(
        (k for k in p.index.children(node) if isinstance(k, chapel.AttributeGroup)),
        None,
    )


def with_attributes(p: Printer, node: Node, doc: Doc) -> Doc:
    """`doc` preceded by the node's attributes and pragmas, each on its own line."""
    group = attribute_group(p, node)
    if group is None:
        return doc
    return concat(
        p.print(group, trailing=False),
        p.comments_after(p.trivia.trailing(group)),
        hardline,
        doc,
    )


def header_start(p: Printer, node: Node) -> int:
    """First token of the declaration after its attributes."""
    group = attribute_group(p, node)
    sp = p.index.node_span(group if group is not None else node)
    assert sp is not None
    return sp[1] + 1 if group is not None else sp[0]


def open_brace(p: Printer, node: Node) -> int | None:
    """The node's own body `{`, if any."""
    braces = [i for i in p.index.structural_brackets(node) if p.tokens[i].text == "{"]
    return braces[-1] if braces else None


def tokens_doc(
    p: Printer,
    node: Node,
    first: int,
    last: int,
    *,
    tight: frozenset[str] = frozenset(),
    anchors: tuple[str, ...] = HEADER_ANCHORS,
) -> tuple[Doc, bool]:
    """Tokens `first..last` of `node`: own tokens as text, children via `p.print`.

    Items are separated by one space, except before `NO_SPACE_BEFORE`, after
    `NO_SPACE_AFTER`, and around `tight` tokens. The node's own dangling
    comments with an anchor kind in `anchors` are printed in place. Also
    returns whether the Doc ends with an own-line `//` comment and its line
    break (so the next text must not follow on the same line).
    """
    tokens = p.tokens
    # `p.print` re-adds a child's user parentheses, which `node` owns.
    outer: dict[Node, tuple[int, int]] = {}
    for o, c, k in p.index.user_parens(node):
        if first <= o and c <= last and (k not in outer or o < outer[k][0]):
            outer[k] = (o, c)
    kids: dict[int, tuple[Node, int]] = {}
    for k in p.index.children(node):
        sp = outer.get(k) or p.index.node_span(k)
        if sp is not None and first <= sp[0] <= last:
            kids[sp[0]] = (k, sp[1])
    dangling = {c.token: c for c in p.dangling(node, *anchors)}
    parts: list[Doc] = []
    prev = ""
    broke = False
    i = first
    d: Doc
    while i <= last:
        kid = kids.get(i)
        if kid is not None:
            d, head, tail = p.print(kid[0]), tokens[i].text, tokens[kid[1]].text
            now_broke = ends_line(p.trivia.trailing(kid[0]))
            i = kid[1] + 1
        else:
            tok = tokens[i]
            i += 1
            if tok.is_comment:
                c = dangling.get(i - 1)
                if c is not None:
                    parts.append(p.comments_after([c]))
                    broke = ends_line([c])
                    if broke:
                        parts.append(hardline)
                    prev = " "
                continue
            d, head, tail = text(tok.text), tok.text, tok.text
            now_broke = False
        if (
            parts
            and not broke
            and (
                prev == " "
                or (head in ("(", "[") and prev in SPACE_BEFORE_OPEN)
                or (head == ":" and prev == "operator")
                or not (
                    head in NO_SPACE_BEFORE
                    or prev in NO_SPACE_AFTER
                    or head in tight
                    or prev in tight
                )
            )
        ):
            parts.append(text(" "))
        parts.append(d)
        prev = tail
        broke = now_broke
    return concat(*parts), broke


def semicolon(p: Printer, node: Node, doc: Doc) -> Doc:
    """`doc` terminated by `;` (remaining dangling comments of `node` go before it)."""
    return concat(doc, p.dangling_comments(node), ";")


def attach_body(
    p: Printer, header: Doc, body: Doc, *, header_ends_line: bool = False
) -> Doc:
    """`header` followed by `body` (starting at `{`) per `brace-style`.

    `attach`: ` {` on the header line; `break`: `{` on its own line at the
    header's indentation. `header_ends_line`: the header ends with an own-line
    `//` comment (and its line break), so `{` starts the next line.
    """
    if header_ends_line:
        return concat(header, body)
    sep = text(" ") if p.options.brace_style == "attach" else hardline
    return concat(header, sep, body)


def body_statements(p: Printer, owner: Node, open_tok: int) -> list[Node]:
    """Children of `owner` after its `{`."""
    out: list[Node] = []
    for k in p.index.children(owner):
        sp = p.index.node_span(k)
        if sp is not None and sp[0] > open_tok:
            out.append(k)
    return out


def braced(
    p: Printer,
    owner: Node,
    open_tok: int,
    stmts: Sequence[Node] | None = None,
    *,
    anchors: tuple[str, ...] = ("{",),
    after_open: Sequence[Comment] | None = None,
) -> Doc:
    """`{ statements }` of `owner` from its `{` token `open_tok`.

    Statements go one per line, indented; `}` on its own line. An empty
    body is `{ }`; comments inside it stay inside (`{ /* c */ }`, or
    `{ // c` / own-line ones on indented lines, then `}`). End-of-line
    comments after `{` stay there. `anchors` selects the owner's dangling
    comments printed after `{` (all of them with `()`), unless `after_open`
    gives them.
    """
    close = p.tokens[open_tok].match
    assert close is not None
    if stmts is None:
        stmts = body_statements(p, owner, open_tok)
    if after_open is None:
        after_open = p.dangling(owner, *anchors)
    empty = p.index.next_code(open_tok) == close and not any(
        open_tok < r.off_token < close for r in p.off.regions
    )
    if empty:
        if not after_open:
            return text("{ }")
        if all(
            not c.is_line and c.placement is not Placement.OWN_LINE for c in after_open
        ):
            return concat("{", p.comments_after(after_open), " }")
        with p.nested() as n:
            inner = p.comments_after(after_open, first_blank=False)
        return concat("{", indent(inner, n), hardline, "}")
    with p.nested() as n:
        inner = concat(
            p.comments_after(after_open, first_blank=False),
            hardline,
            p.statement_list(stmts, open_tok + 1, close),
        )
    return concat("{", indent(inner, n), hardline, "}")
