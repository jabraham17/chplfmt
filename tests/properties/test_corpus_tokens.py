from pathlib import Path
from typing import cast

import pytest

from chplfmt import api
from chplfmt._chapel import parse_text
from chplfmt.config import FormatOptions
from chplfmt.source import SourceText
from chplfmt.tokens import TokenIndex
from corpus import corpus_params, parsed
from reference.tokens import TokenIndex as ReferenceTokenIndex

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_token_index_on_corpus(path: Path) -> None:
    with parsed(path) as (source, result):
        idx = TokenIndex.build(source, result.asts)
        # Includes the wide-Identifier exception (`owned C`, `domain(2)`, ...).
        assert idx.check_leaves() == []
        # Every code token owned, brackets owned in pairs, all explained.
        assert idx.check_ownership() == []


@pytest.mark.parametrize("path", corpus_params())
def test_native_index_phase_3c_on_corpus(path: Path) -> None:
    with parsed(path) as (source, result):
        reference = ReferenceTokenIndex.build(source, result.asts)
        native = TokenIndex.build(source, result.asts)
        _assert_index_parity(native, reference)
        options = FormatOptions()
        output, _ = api._print_text(native, options, str(path))
        reference_output, _ = api._print_text(
            cast(TokenIndex, reference), options, str(path)
        )
        assert output == reference_output
    with parse_text(output, str(path)) as formatted:
        assert not formatted.errors
        formatted_source = SourceText.from_text(output)
        _assert_index_parity(
            TokenIndex.build(formatted_source, formatted.asts),
            ReferenceTokenIndex.build(formatted_source, formatted.asts),
        )


def _assert_index_parity(native: TokenIndex, reference: ReferenceTokenIndex) -> None:
    assert native.tokens == reference.tokens
    assert native.problems == reference.problems
    assert native.nodes() == list(reference.nodes())
    assert native.check_leaves() == reference.check_leaves()
    assert native.check_ownership() == reference.check_ownership()
    for node in reference.nodes():
        assert native.span(node.location()) == reference.span(node.location())
        assert native.node_span(node) == reference.node_span(node)
        assert native.header_span(node) == reference.header_span(node)
        assert native.body_span(node) == reference.body_span(node)
        assert native.stmt_span(node) == reference.stmt_span(node)
        assert native.parent(node) == reference.parent(node)
        assert tuple(native.children(node)) == tuple(reference.children(node))
        assert tuple(native.ast_children(node)) == tuple(reference.ast_children(node))
        assert tuple(native.own_tokens(node)) == tuple(reference.own_tokens(node))
        assert tuple(native.structural_brackets(node)) == tuple(
            reference.structural_brackets(node)
        )
        assert tuple(native.user_parens(node)) == tuple(reference.user_parens(node))
        assert tuple(native.parens_around(node)) == tuple(reference.parens_around(node))
        assert tuple(native.unexplained_brackets(node)) == tuple(
            reference.unexplained_brackets(node)
        )
        assert tuple(native.body_delimiters(node)) == tuple(
            reference.body_delimiters(node)
        )
        assert native.is_wide_identifier(node) == reference.is_wide_identifier(node)
    for token, value in enumerate(reference.tokens):
        assert native.owner(token) == reference.owner(token)
        if token < len(reference.tokens) - 1:
            assert native.next_code(token) == reference.next_code(token)
        assert native.prev_code(token) == reference.prev_code(token)
        assert native.find_start(value.start) == reference.find_start(value.start)
        if token < len(reference.tokens) - 1:
            assert native.find_end(value.end) == reference.find_end(value.end)
