"""remove-redundant-parens. Decision point: `wrap_user_parens`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from chplfmt._chapel import chapel
from chplfmt.lexer import TokenKind
from chplfmt.rules.base import Rule
from chplfmt.tokens import Node, TokenIndex

if TYPE_CHECKING:
    from chplfmt.printer.core import Printer

OPTION = "remove-redundant-parens"

_ASSIGN_OPS = frozenset(
    {"=", "+=", "-=", "*=", "/=", "%=", "**=", "&=", "|=", "^=", "<<=", ">>="}
    | {"&&=", "||="}
)
_NUMERIC = (
    chapel.IntLiteral,
    chapel.UintLiteral,
    chapel.RealLiteral,
    chapel.ImagLiteral,
)
# Expressions that run until a keyword (`then`, `else`, `do`); kept in parens
# where a keyword or `{` follows.
_OPEN_ENDED = (chapel.Conditional, chapel.IndexableLoop, chapel.Let)


def user_paren_tokens(index: TokenIndex) -> set[int]:
    found: set[int] = set()
    # Only nodes owning a `(` can have user parentheses.
    owners = {
        index.owner(i)
        for i, t in enumerate(index.tokens)
        if t.text == "(" and t.kind is TokenKind.PUNCT
    }
    for node in owners:
        if node is None:
            continue
        for i, j, _ in index.user_parens(node):
            found.update((i, j))
    return found


RULE = Rule(OPTION, lambda o: o.remove_redundant_parens, user_paren_tokens)


def keep(p: Printer, node: Node, layer: tuple[int, int], depth: int) -> bool:
    """Whether the `depth`-th (innermost = 0) layer of user parens around `node` stays."""
    if not p.options.remove_redundant_parens:
        return True
    # `try (x): t` differs from `try x: t`; `while try x {` does not parse.
    if isinstance(node, chapel.Try) or _after_try(p.index, layer[0]):
        return True
    if depth == 0 and not removable(p.index, node):
        return True
    p.record(OPTION, layer[0])
    return False


def _after_try(index: TokenIndex, open_tok: int) -> bool:
    i = open_tok - 1
    while i >= 0 and index.tokens[i].is_comment:
        i -= 1
    return i >= 0 and index.tokens[i].text in ("try", "try!")


def removable(index: TokenIndex, node: Node) -> bool:
    """Whether the last layer of parentheses around `node` is redundant."""
    parent = index.parent(node)
    # `new (owned C)()`, `proc (union).f()`: the parentheses are syntax.
    if isinstance(parent, chapel.New) or (
        isinstance(parent, chapel.Formal) and parent.is_this()
    ):
        return False
    if is_atom(node):
        # `(f)(x)`, `(a.b)[i]`: keep a parenthesized callee unless it is a call.
        if (
            isinstance(parent, chapel.FnCall)
            and parent.called_expression() == node
            and not isinstance(node, chapel.FnCall)
        ):
            return False
        # `(1).type`: `1.` would lex as a real literal.
        return not (isinstance(node, _NUMERIC) and isinstance(parent, chapel.Dot))
    return parent is not None and is_whole_expression(parent, node)


def is_atom(node: Node) -> bool:
    """Identifier, literal, call or index expression (not `new C()`), dot access."""
    if isinstance(node, chapel.FnCall):
        return not isinstance(node.called_expression(), chapel.New)
    return isinstance(node, chapel.Identifier | chapel.Literal | chapel.Dot)


def is_whole_expression(parent: Node, node: Node) -> bool:
    """Whether `node` is a whole statement-level expression of `parent`."""
    match parent:
        case chapel.Return() | chapel.Yield():
            return parent.value() == node
        case chapel.Throw():
            return parent.error_expression() == node
        case chapel.Variable() | chapel.TupleDecl():
            return parent.init_expression() == node
        case chapel.OpCall():
            return (
                parent.op() in _ASSIGN_OPS
                and parent.num_actuals() == 2
                and parent.actual(1) == node
            )
        case _:
            pass
    if isinstance(node, _OPEN_ENDED):
        return False
    match parent:
        case chapel.Conditional() | chapel.While() | chapel.DoWhile():
            return parent.condition() == node
        case chapel.IndexableLoop():
            return parent.iterand() == node
        case chapel.Select():
            return not isinstance(node, chapel.When)
        case chapel.When():
            return any(e == node for e in parent.case_exprs())
        case chapel.On():
            return parent.destination() == node
        case _:
            return False
