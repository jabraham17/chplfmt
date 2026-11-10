"""remove-empty-statements (design section 7.8). Decision point: `statement_list`."""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.rules.base import Rule
from chplfmt.tokens import TokenIndex


def empty_stmt_tokens(index: TokenIndex) -> set[int]:
    found: set[int] = set()
    for node in index.nodes():
        if isinstance(node, chapel.EmptyStmt) and (sp := index.node_span(node)):
            found.update(range(sp[0], sp[1] + 1))
    return found


RULE = Rule(
    "remove-empty-statements",
    lambda o: o.remove_empty_statements,
    empty_stmt_tokens,
    drops_empty_stmts=True,
)
