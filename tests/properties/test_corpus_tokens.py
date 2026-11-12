import gc
import tracemalloc
from pathlib import Path

import pytest

from chplfmt import api
from chplfmt._chapel import parse_text
from chplfmt.config import FormatOptions
from chplfmt.lexer import TokenKind, check_invariants
from chplfmt.source import SourceText
from chplfmt.tokens import _MAY_HAVE_CURLY, TokenIndex
from corpus import corpus_params, parsed, preorder, sample_params

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_curly_location_class_allowlist(path: Path) -> None:
    with parsed(path) as (_, result):
        for node in preorder(result.asts):
            if type(node).__name__ not in _MAY_HAVE_CURLY:
                assert node.curly_braces_location() is None, (path, type(node).__name__)


@pytest.mark.parametrize("path", sample_params()[:1])
def test_repeated_corpus_formatting_does_not_grow_traced_memory(path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    tracemalloc.start()
    try:
        for _ in range(5):
            api.format_text(text, path=str(path))
        gc.collect()
        baseline, _ = tracemalloc.get_traced_memory()
        for _ in range(20):
            api.format_text(text, path=str(path))
        gc.collect()
        current, _ = tracemalloc.get_traced_memory()
        assert current - baseline < 128 * 1024, (baseline, current)
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("path", corpus_params())
def test_token_index_on_corpus(path: Path) -> None:
    with parsed(path) as (source, result):
        idx = TokenIndex.build(source, result.asts)
        # Includes the wide-Identifier exception (`owned C`, `domain(2)`, ...).
        assert idx.check_leaves() == []
        # Every code token owned, brackets owned in pairs, all explained.
        assert idx.check_ownership() == []


@pytest.mark.parametrize("path", corpus_params())
def test_index_queries_on_input_and_formatted_output(path: Path) -> None:
    with parsed(path) as (source, result):
        index = TokenIndex.build(source, result.asts)
        _assert_index_invariants(index)
        options = FormatOptions()
        output, _ = api._print_text(index, options, str(path))
    with parse_text(output, str(path)) as formatted:
        assert not formatted.errors
        formatted_source = SourceText.from_text(output)
        _assert_index_invariants(TokenIndex.build(formatted_source, formatted.asts))


def _assert_index_invariants(index: TokenIndex) -> None:
    assert check_invariants(index.source, index.tokens) == []
    assert index.problems == []
    assert index.check_leaves() == []
    assert index.check_ownership() == []
    for node in index.nodes():
        for token in index.own_tokens(node):
            assert index.owner(token) is node
        for child in index.children(node):
            assert index.parent(child) is node
        for token in index.structural_brackets(node):
            match = index.tokens[token].match
            assert match is not None
            assert index.owner(match) is node
    for token, value in enumerate(index.tokens):
        if value.kind is TokenKind.EOF:
            continue
        assert index.find_start(value.start) == token
        assert index.find_end(value.end) == token
