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
from chplfmt._chapel import parse_text
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
    candidates: list[tuple[int, int, str]] = []
    for a, b in itertools.pairwise(tokens):
        if a.kind in FIXED or b.kind in FIXED or b.nl_before:
            continue
        if a.text == "proc" and b.text == "(":
            continue
        gap = text[a.end_offset : b.start_offset]
        if gap.strip(" \t"):
            continue
        if gap:
            choices = [s for s in (" ", "  ", "\t") if s != gap]
            candidate = (a.end_offset, b.start_offset, rng.choice(choices))
        elif a.kind in INSERTABLE and b.kind in INSERTABLE:
            candidate = (a.end_offset, b.start_offset, " ")
        else:
            continue
        candidates.append(candidate)
        if rng.random() <= 0.3:
            edits.append(candidate)
    if not edits and candidates:
        edits.append(rng.choice(candidates))
    out: list[str] = []
    pos = 0
    for start, end, new in edits:
        out += [text[pos:start], new]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def test_perturb_changes_short_input() -> None:
    text = "var x = 1;\n"
    changed = perturb(text, tokenize(SourceText.from_text(text)), random.Random(1))
    assert changed != text


def test_perturb_keeps_function_type_lexical_adjacency() -> None:
    text = "proc f(g: proc()) { var x = 1; }\n"
    changed = perturb(text, tokenize(SourceText.from_text(text)), random.Random(1))
    assert changed != text
    assert "proc()" in changed
    with parse_text(changed, "t.chpl") as result:
        assert not result.errors


def test_perturb_with_no_safe_gap_is_unchanged() -> None:
    text = "// only a comment\n"
    assert perturb(text, tokenize(SourceText.from_text(text)), random.Random(1)) == text


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
    if changed == text:
        pytest.skip("no safe mutable whitespace gaps")
    if not opaque:
        relexed = tokenize(SourceText.from_text(changed))
        assert [t.text for t in relexed] == [t.text for t in tokens]
    out = api.format_text(changed, path=str(path), debug=SKIP_VERIFY)
    assert out.text == base.text
