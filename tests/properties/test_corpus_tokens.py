from pathlib import Path

import pytest

from chplfmt.tokens import TokenIndex
from corpus import corpus_params, parsed

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
def test_native_index_phase_3a_on_corpus(path: Path) -> None:
    with parsed(path) as (source, result):
        reference = TokenIndex.build(source, result.asts)
        native = TokenIndex.build_native(source, result.asts)
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
            assert native.children(node) == reference.children(node)
            assert native.ast_children(node) == reference.ast_children(node)
            assert native.own_tokens(node) == reference.own_tokens(node)
            assert native.structural_brackets(node) == reference.structural_brackets(
                node
            )
            assert native.user_parens(node) == reference.user_parens(node)
            assert native.parens_around(node) == reference.parens_around(node)
            assert native.unexplained_brackets(node) == reference.unexplained_brackets(
                node
            )
            assert native.body_delimiters(node) == reference.body_delimiters(node)
            assert native.is_wide_identifier(node) == reference.is_wide_identifier(node)
        for token, value in enumerate(reference.tokens):
            assert native.owner(token) == reference.owner(token)
            if token < len(reference.tokens) - 1:
                assert native.next_code(token) == reference.next_code(token)
            assert native.prev_code(token) == reference.prev_code(token)
            assert native.find_start(value.start) == reference.by_start[value.start]
            if token < len(reference.tokens) - 1:
                assert native.find_end(value.end) == reference.by_end[value.end]
