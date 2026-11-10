"""Rewrite rules (design section 7.8): printer decisions plus verifier normalizations."""

from __future__ import annotations

from chplfmt.rules import (
    comment_spacing,
    empty_statements,
    redundant_parens,
    single_statement_body,
    trailing_comma,
)
from chplfmt.rules.base import Rule

RULES: list[Rule] = [
    comment_spacing.RULE,
    single_statement_body.RULE,
    redundant_parens.RULE,
    trailing_comma.RULE,
    empty_statements.RULE,
]

__all__ = ["RULES", "Rule"]
