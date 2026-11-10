"""Range consistency (design section 10, property 4).

(a) On canonically formatted text whose spacing was perturbed inside the
range, formatting the range restores the whole-file output.
(b) On formatted text shifted right by `SHIFT` columns, range output keeps
the shifted indentation (and line breaking uses the actual columns).
"""

from __future__ import annotations

import hashlib
import itertools
import random
from pathlib import Path

import pytest

from chplfmt import api
from chplfmt._chapel import parse_text
from chplfmt.config import FormatOptions
from chplfmt.lexer import COMMENT_KINDS, TokenKind, tokenize
from chplfmt.source import SourceText
from corpus import extern_ranges, parsed, sample_params

pytestmark = pytest.mark.corpus

SKIP_VERIFY = api.DebugOptions(skip_verify=True)
FIXED = frozenset({TokenKind.OPAQUE, TokenKind.EOF, *COMMENT_KINDS})
RANGES = 10
SHIFT = 3


def perturb(
    text: str, lo: int, hi: int, rng: random.Random, opaque: list[tuple[int, int]]
) -> str:
    """`text` with some same-line gaps between code tokens on lines lo..hi changed."""
    source = SourceText.from_text(text)
    edits: list[tuple[int, int, str]] = []
    for a, b in itertools.pairwise(tokenize(source, opaque)):
        if a.kind in FIXED or b.kind in FIXED or b.nl_before:
            continue
        if not lo <= b.start[0] <= hi or rng.random() > 0.5:
            continue
        gap = text[a.end_offset : b.start_offset]
        if gap:
            edits.append((a.end_offset, b.start_offset, rng.choice(["  ", "\t"])))
    out: list[str] = []
    pos = 0
    for start, end, new in edits:
        out += [text[pos:start], new]
        pos = end
    out.append(text[pos:])
    return "".join(out)


def random_ranges(text: str, seed: str) -> list[tuple[int, int]]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
    n = max(text.count("\n"), 1)
    out: list[tuple[int, int]] = []
    for _ in range(RANGES):
        a = rng.randint(1, n)
        out.append((a, min(n, a + rng.randint(0, 8))))
    return out


def canonical(path: Path, options: FormatOptions) -> str:
    with parsed(path) as (source, _):
        text = source.text
    if "chplfmt:" in text:
        pytest.skip("off regions keep source spacing")
    base = api.format_text(text, path=str(path), options=options, debug=SKIP_VERIFY)
    if base.report.fallbacks:
        pytest.skip("fallback output keeps source spacing")
    return base.text


@pytest.mark.parametrize("path", sample_params())
def test_range_equals_whole_file(path: Path) -> None:
    whole = canonical(path, FormatOptions())
    rng = random.Random(path.name)
    with parse_text(whole, str(path)) as result:
        # extern blocks hold C code, not Chapel tokens to perturb
        opaque = extern_ranges(SourceText.from_text(whole), result.asts)
    for lo, hi in random_ranges(whole, path.name):
        changed = perturb(whole, lo, hi, rng, opaque)
        out = api.format_text(changed, path=str(path), lines=(lo, hi))
        assert out.text == whole, f"lines {lo}:{hi}"


@pytest.mark.parametrize("path", sample_params())
def test_range_keeps_shifted_indentation(path: Path) -> None:
    length = FormatOptions().line_length
    whole = canonical(path, FormatOptions(line_length=length - SHIFT))
    shifted = "".join(
        " " * SHIFT + ln if ln.strip() else ln for ln in whole.splitlines(keepends=True)
    )
    for lo, hi in random_ranges(whole, path.name + "shift"):
        out = api.format_text(shifted, path=str(path), lines=(lo, hi))
        assert out.text == shifted, f"lines {lo}:{hi}"
