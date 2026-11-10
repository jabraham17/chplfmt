"""Every concrete AstNode subclass has a printer (design sections 7.7, 10)."""

from __future__ import annotations

import inspect

import pytest

import chplfmt.printer  # noqa: F401  (registers the printers)
from chplfmt._chapel import chapel
from chplfmt.printer.core import REGISTRY

IGNORED = {
    "Comment": "comments come from tokens",
    "ErroneousExpression": "parse errors stop formatting",
    "Match": "dyno has no parser rule for `match` (no accessors)",
    "MatchCase": "dyno has no parser rule for `match` (no accessors)",
}


def _ast_classes() -> list[type]:
    return [
        c
        for _, c in inspect.getmembers(chapel, inspect.isclass)
        if issubclass(c, chapel.AstNode)
    ]


def _concrete() -> list[type]:
    # dyno's AST bases (Decl, Loop, Call, Literal, ...) are all abstract.
    return sorted(
        (c for c in _ast_classes() if not c.__subclasses__()),
        key=lambda c: c.__name__,
    )


def test_ignore_list_is_current() -> None:
    names = {c.__name__ for c in _concrete()}
    assert set(IGNORED) <= names


@pytest.mark.parametrize("cls", _concrete(), ids=lambda c: c.__name__)
def test_concrete_node_has_printer(cls: type) -> None:
    if cls.__name__ in IGNORED:
        pytest.skip(IGNORED[cls.__name__])
    assert any(c in REGISTRY for c in cls.__mro__), f"no printer for {cls.__name__}"
