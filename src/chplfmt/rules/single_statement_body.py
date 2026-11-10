"""single-statement-body (design section 7.8). Decision point: printer/body.py."""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.rules.base import Rule
from chplfmt.tokens import TokenIndex

_STATEMENT_BODIES = (
    chapel.Function,
    chapel.While,
    chapel.IndexableLoop,
    chapel.Conditional,
    chapel.When,
    chapel.On,
    chapel.Local,
    chapel.Serial,
    chapel.Manage,
    chapel.Begin,
    chapel.Sync,
    chapel.Defer,
)


def body_delimiter_tokens(index: TokenIndex) -> set[int]:
    """`{`/`}` and `do`/`then` of bodies the single-statement-body rule rewrites."""
    found: set[int] = set()
    for node in index.nodes():
        if isinstance(node, _STATEMENT_BODIES) or (
            isinstance(node, chapel.Block)
            and isinstance(index.parent(node), _STATEMENT_BODIES)
        ):
            found.update(index.body_delimiters(node))
    return found


RULE = Rule(
    "single-statement-body",
    lambda o: o.single_statement_body != "preserve",
    body_delimiter_tokens,
    frozenset({"block_style", "then_block_style", "else_block_style"}),
)
