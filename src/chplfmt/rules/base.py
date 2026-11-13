"""The `Rule` record shared by all rewrite rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from chplfmt.config import FormatOptions
from chplfmt.tokens import TokenIndex


def no_tokens(index: TokenIndex) -> set[int]:
    return set()


@dataclass(frozen=True)
class Rule:
    """A rule's option plus its verifier normalization (applied to both sides when enabled).

    The printer-side decision functions live in the rule's module.
    """

    option: str
    enabled: Callable[[FormatOptions], bool]
    # Tokens the rule may add or remove.
    removable_tokens: Callable[[TokenIndex], set[int]] = no_tokens
    # AST attributes the rule may change.
    ignored_attrs: frozenset[str] = frozenset()
    # Whether `EmptyStmt` children of statement lists may disappear.
    drops_empty_stmts: bool = False
