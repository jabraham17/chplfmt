from pathlib import Path

import pytest

from chplfmt.offregions import find_off_regions
from chplfmt.tokens import TokenIndex
from chplfmt.trivia import attach
from corpus import corpus_params, parsed

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_every_comment_attached_exactly_once(path: Path) -> None:
    with parsed(path) as (source, result):
        index = TokenIndex.build(source, result.asts)
        off = find_off_regions(index)
        a = attach(index, off)
        expected = [
            i
            for i, t in enumerate(index.tokens)
            if t.is_comment and not off.contains(t.start_offset)
        ]
        assert a.comments == expected
        assert sorted(a.where) == expected
        seen: list[int] = []
        for node, nc in a.by_node.items():
            seen += [c.token for c in nc.leading + nc.trailing]
            seen += [d.comment.token for d in nc.dangling]
            sp = None if node is None else index.node_span(node)
            if sp is None:
                continue
            assert all(c.token < sp[0] for c in nc.leading), node
            assert all(c.token > sp[1] for c in nc.trailing), node
        assert sorted(seen) == expected
