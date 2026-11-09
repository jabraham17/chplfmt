"""Corpus discovery for property tests (design section 10)."""

from __future__ import annotations

import os
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from chplfmt._chapel import ParseResult, chapel, parse_text
from chplfmt.source import SourceDecodeError, SourceText

LEAF_TYPES = (chapel.Identifier, chapel.Literal)


def chpl_home() -> Path | None:
    # Importing chplfmt._chapel sets CHPL_HOME when it had to discover it.
    home = os.environ.get("CHPL_HOME")
    return Path(home) if home else None


def corpus_roots() -> list[Path]:
    home = chpl_home()
    if home is None:
        return []
    return [d for d in (home / "modules", home / "test") if d.is_dir()]


def corpus_files() -> list[Path]:
    """Every `.chpl` file under the corpus roots, sorted."""
    return sorted(p for root in corpus_roots() for p in root.rglob("*.chpl"))


def corpus_params() -> list[object]:
    """`pytest.param`s for `corpus_files()`, with ids relative to CHPL_HOME."""
    home = chpl_home()
    files = corpus_files()
    if home is None or not files:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no Chapel corpus"))]
    return [pytest.param(p, id=str(p.relative_to(home))) for p in files]


@contextmanager
def parsed(path: Path) -> Iterator[tuple[SourceText, ParseResult]]:
    """Read and parse `path`; skip the test if dyno reports errors."""
    try:
        source = SourceText.from_bytes(path.read_bytes())
    except SourceDecodeError as e:
        pytest.skip(f"not UTF-8: {e}")
    with parse_text(source.text, str(path)) as result:
        if result.errors:
            pytest.skip(f"dyno reports {len(result.errors)} error(s)")
        yield source, result


def preorder(asts: Iterable[chapel.AstNode]) -> Iterator[chapel.AstNode]:
    for root in asts:
        yield from chapel.preorder(root)


def extern_ranges(
    source: SourceText, asts: Iterable[chapel.AstNode]
) -> list[tuple[int, int]]:
    """Offsets of `extern { ... }` blocks, for the lexer's OPAQUE tokens."""
    ranges: list[tuple[int, int]] = []
    for node in preorder(asts):
        if isinstance(node, chapel.ExternBlock):
            loc = node.location()
            ranges.append((source.offset(loc.start()), source.offset(loc.end())))
    return ranges
