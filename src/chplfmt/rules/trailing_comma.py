"""trailing-comma.

Decision points: `bracket_list` (printer/lists.py) and enum layout
(printer/aggregates.py).
"""

from __future__ import annotations

from chplfmt._chapel import chapel
from chplfmt.rules.base import Rule
from chplfmt.tokens import TokenIndex


def trailing_comma_tokens(index: TokenIndex) -> set[int]:
    """Trailing commas where they are legal and optional (not in 1-tuples)."""
    found: set[int] = set()
    for node in index.nodes():
        if isinstance(node, chapel.Tuple) and node.num_actuals() == 1:
            continue
        if isinstance(node, chapel.TupleDecl) and sum(1 for _ in node.decls()) == 1:
            continue
        if not isinstance(
            node,
            (chapel.Array, chapel.Domain, chapel.Tuple, chapel.TupleDecl, chapel.Enum),
        ):
            continue
        for open_ in index.structural_brackets(node):
            close = index.tokens[open_].match
            prev = None if close is None else index.prev_code(close)
            if (
                prev is not None
                and prev > open_
                and index.tokens[prev].text == ","
                and index.owner(prev) == node
            ):
                found.add(prev)
    return found


RULE = Rule(
    "trailing-comma",
    lambda o: o.trailing_comma,
    trailing_comma_tokens,
    frozenset({"has_trailing_comma"}),
)
