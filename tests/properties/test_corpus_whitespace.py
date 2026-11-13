"""Whitespace insensitivity.

Randomly (seeded per file) changing spaces between tokens inside lines, away
from comments, strings, and newlines, doesn't change the output.
"""

from __future__ import annotations

import hashlib
import itertools
import random
from pathlib import Path

import pytest

from chplfmt import api
from chplfmt.lexer import COMMENT_KINDS, Token, TokenKind, tokenize
from chplfmt.source import SourceText
from corpus import extern_ranges, parsed, sample_params

pytestmark = pytest.mark.corpus

SKIP_VERIFY = api.DebugOptions(skip_verify=True)
FIXED = frozenset({TokenKind.OPAQUE, TokenKind.EOF, *COMMENT_KINDS})
INSERTABLE = frozenset({TokenKind.IDENT, TokenKind.PUNCT})


def perturb(text: str, tokens: list[Token], rng: random.Random) -> str:
    """`text` with the spacing of some same-line gaps between code tokens changed."""
    edits: list[tuple[int, int, str]] = []
    for a, b in itertools.pairwise(tokens):
        if a.kind in FIXED or b.kind in FIXED or b.nl_before:
            continue
        gap = text[a.end_offset : b.start_offset]
        if gap.strip(" \t") or rng.random() > 0.3:
            continue
        if gap:
            edits.append((a.end_offset, b.start_offset, rng.choice([" ", "  ", "\t"])))
        elif a.kind in INSERTABLE and b.kind in INSERTABLE:
            edits.append((a.end_offset, b.start_offset, " "))
    out: list[str] = []
    pos = 0
    for start, end, new in edits:
        out += [text[pos:start], new]
        pos = end
    out.append(text[pos:])
    return "".join(out)


PINNED = (
    "modules/internal/ChapelRange.chpl",
    "modules/internal/DefaultSparse.chpl",
    "modules/packages/Python.chpl",
    "modules/packages/Zarr.chpl",
)


@pytest.mark.parametrize("path", sample_params(PINNED))
def test_whitespace_insensitive(path: Path) -> None:
    with parsed(path) as (source, result):
        text = source.text
        opaque = extern_ranges(source, result.asts)
        tokens = tokenize(source, opaque)
    if "chplfmt:" in text:
        pytest.skip("off regions keep source spacing")
    base = api.format_text(text, path=str(path), debug=SKIP_VERIFY)
    if base.report.fallbacks:
        pytest.skip("fallback output keeps source spacing")
    seed = int(hashlib.sha256(path.name.encode()).hexdigest()[:8], 16)
    changed = perturb(text, tokens, random.Random(seed))
    assert changed != text
    if not opaque:
        relexed = tokenize(SourceText.from_text(changed))
        assert [t.text for t in relexed] == [t.text for t in tokens]
    out = api.format_text(changed, path=str(path), debug=SKIP_VERIFY)
    assert out.text == base.text
