from pathlib import Path

import pytest

from chplfmt.lexer import TokenKind, check_invariants, tokenize
from corpus import LEAF_TYPES, corpus_params, extern_ranges, parsed, preorder

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_lexer_on_corpus(path: Path) -> None:
    with parsed(path) as (source, result):
        tokens = tokenize(source, extern_ranges(source, result.asts))
        assert check_invariants(source, tokens) == []
        starts = {t.start for t in tokens if t.kind is not TokenKind.EOF}
        ends = {t.end for t in tokens if t.kind is not TokenKind.EOF}
        bad: list[str] = []
        for node in preorder(result.asts):
            if not isinstance(node, LEAF_TYPES):
                continue
            loc = node.location()
            start, end = loc.start(), loc.end()
            if start not in starts or end not in ends:
                bad.append(f"{type(node).__name__} {start}-{end}")
        assert bad == []
