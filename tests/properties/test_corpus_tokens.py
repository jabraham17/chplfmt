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
        for node in reference.nodes():
            assert native.span(node.location()) == reference.span(node.location())
            assert native.node_span(node) == reference.node_span(node)
            assert native.parent(node) == reference.parent(node)
            assert native.children(node) == reference.children(node)
            assert native.own_tokens(node) == reference.own_tokens(node)
        for token, value in enumerate(reference.tokens):
            assert native.owner(token) == reference.owner(token)
            assert native.find_start(value.start) == reference.by_start[value.start]
            if token < len(reference.tokens) - 1:
                assert native.find_end(value.end) == reference.by_end[value.end]
