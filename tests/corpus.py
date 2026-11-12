"""Corpus discovery for property tests (design section 10)."""

from __future__ import annotations

import hashlib
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


def _hash(path: Path) -> str:
    home = chpl_home()
    rel = path.relative_to(home) if home is not None else path
    return hashlib.sha256(str(rel).encode()).hexdigest()


def shard() -> tuple[int, int]:
    """`CHPLFMT_SHARD=k/n` (1-based) selects one of `n` disjoint corpus slices."""
    spec = os.environ.get("CHPLFMT_SHARD", "1/1")
    k, _, n = spec.partition("/")
    k_i, n_i = int(k), int(n or "1")
    if not 1 <= k_i <= n_i:
        raise ValueError(f"invalid CHPLFMT_SHARD={spec!r} (expected k/n, 1<=k<=n)")
    return k_i, n_i


def in_shard(path: Path) -> bool:
    k, n = shard()
    return n == 1 or int(_hash(path), 16) % n == k - 1


def corpus_test_limit() -> int | None:
    """`CHPLFMT_CORPUS_TEST_MAX`: at most this many files from `$CHPL_HOME/test`."""
    value = os.environ.get("CHPLFMT_CORPUS_TEST_MAX")
    return int(value) if value else None


def corpus_files() -> list[Path]:
    """Every `.chpl` file under the corpus roots in this shard, sorted.

    Files from `$CHPL_HOME/test` are capped at `corpus_test_limit()` (chosen by a
    stable hash).
    """
    home = chpl_home()
    limit = corpus_test_limit()
    files: list[Path] = []
    for root in corpus_roots():
        found = list(root.rglob("*.chpl"))
        if home is not None and root == home / "test" and limit is not None:
            found = sorted(found, key=_hash)[:limit]
        files += found
    return sorted(p for p in files if in_shard(p))


def corpus_params() -> list[object]:
    """`pytest.param`s for `corpus_files()`, with ids relative to CHPL_HOME."""
    home = chpl_home()
    files = corpus_files()
    if home is None or not files:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no Chapel corpus"))]
    return [pytest.param(p, id=str(p.relative_to(home))) for p in files]


SAMPLE_SIZE = 12
SAMPLE_MAX_BYTES = 30_000


def full_corpus() -> bool:
    return os.environ.get("CHPLFMT_FULL_CORPUS") == "1"


def sample_files(pinned: Iterable[str] = ()) -> list[Path]:
    """A deterministic sample of `corpus_files()`; all of it if CHPLFMT_FULL_CORPUS=1.

    The sample is the `pinned` files (paths relative to CHPL_HOME, skipped if
    absent) plus small-to-medium files chosen by a stable hash of the path.
    """
    home = chpl_home()
    files = corpus_files()
    if home is None or not files or full_corpus():
        return files
    pins = [home / r for r in pinned if (home / r).is_file() and in_shard(home / r)]
    by_hash = sorted(
        (p for p in files if p not in pins and p.stat().st_size <= SAMPLE_MAX_BYTES),
        key=_hash,
    )
    return sorted([*pins, *by_hash[:SAMPLE_SIZE]])


def sample_params(pinned: Iterable[str] = ()) -> list[object]:
    """`pytest.param`s for `sample_files(pinned)`, with ids relative to CHPL_HOME."""
    home = chpl_home()
    files = sample_files(pinned)
    if home is None or not files:
        return [pytest.param(None, marks=pytest.mark.skip(reason="no Chapel corpus"))]
    return [pytest.param(p, id=str(p.relative_to(home))) for p in files]


@contextmanager
def parsed(path: Path) -> Iterator[tuple[SourceText, ParseResult]]:
    """Read and parse `path`; fail on unexpected parser errors."""
    try:
        source = SourceText.from_bytes(path.read_bytes())
    except SourceDecodeError as e:
        pytest.skip(f"not UTF-8: {e}")
    with parse_text(source.text, str(path)) as result:
        if result.errors:
            home = chpl_home()
            if (
                home is not None
                and path == home / "modules/internal/ChapelBase.chpl"
                and [(d.kind, d.message) for d in result.errors]
                == [
                    ("error", "'&&=' operator may not be overloaded"),
                    ("error", "'||=' operator may not be overloaded"),
                ]
            ):
                pytest.xfail("known ChapelBase.chpl operator overload errors")
            pytest.fail(f"dyno reports {len(result.errors)} error(s): {path}")
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
