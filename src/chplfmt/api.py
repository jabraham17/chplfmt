"""Stable library interface (section 7.11). Not thread-safe."""

from __future__ import annotations

import difflib
import gc
import os
from bisect import bisect_left
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field

from chplfmt._chapel import Diagnostic, parse_text
from chplfmt.config import FormatOptions, load_options
from chplfmt.doc import render
from chplfmt.errors import ChplParseError, FormatError, VerificationError
from chplfmt.printer import Printer, PrintReport
from chplfmt.source import SourceText
from chplfmt.tokens import TokenIndex
from chplfmt.verify import verify

__all__ = [
    "ChplParseError",
    "DebugOptions",
    "Diagnostic",
    "FormatError",
    "FormatOptions",
    "FormatResult",
    "TextEdit",
    "VerificationError",
    "format_text",
    "load_options",
]

STDIN_PATH = "<stdin>"


@dataclass(frozen=True)
class TextEdit:
    start_line: int  # 0-based
    end_line: int  # 0-based, exclusive
    new_text: str


@dataclass(frozen=True)
class FormatResult:
    text: str
    changed: bool
    edits: list[TextEdit]
    # Internal: rule applications and fallbacks (for --check --verbose, tests).
    report: PrintReport = field(
        default_factory=PrintReport, compare=False, repr=False, kw_only=True
    )


@dataclass(frozen=True)
class DebugOptions:
    """Development-only switches (hidden CLI flags)."""

    dump_failed_dir: str | None = None  # save output that fails verification
    skip_verify: bool = False


def compute_edits(old: str, new: str) -> list[TextEdit]:
    """Minimal line-level edits that turn `old` into `new`."""
    a = old.splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    edits: list[TextEdit] = []
    i = j = 0
    for x, y, n in _matching_blocks(a, b):
        if i < x or j < y:
            edits.append(TextEdit(i, x, "".join(b[j:y])))
        i, j = x + n, y + n
    return edits


def _matching_blocks(a: list[str], b: list[str]) -> list[tuple[int, int, int]]:
    """Equal runs `(i, j, n)` in order, ending with `(len(a), len(b), 0)`.

    Patience-style: common prefix/suffix, then lines unique on both sides as
    anchors; difflib only sees the (normally small) ranges between anchors.
    """
    blocks: list[tuple[int, int, int]] = []
    stack = [(0, len(a), 0, len(b))]
    while stack:
        alo, ahi, blo, bhi = stack.pop()
        n = 0
        while alo + n < ahi and blo + n < bhi and a[alo + n] == b[blo + n]:
            n += 1
        if n:
            blocks.append((alo, blo, n))
            alo, blo = alo + n, blo + n
        n = 0
        while alo < ahi - n and blo < bhi - n and a[ahi - 1 - n] == b[bhi - 1 - n]:
            n += 1
        if n:
            blocks.append((ahi - n, bhi - n, n))
            ahi, bhi = ahi - n, bhi - n
        if alo == ahi or blo == bhi:
            continue
        anchors = _unique_anchors(a, b, alo, ahi, blo, bhi)
        if not anchors:
            matcher = difflib.SequenceMatcher(
                a=a[alo:ahi], b=b[blo:bhi], autojunk=False
            )
            blocks += [
                (alo + x, blo + y, n) for x, y, n in matcher.get_matching_blocks() if n
            ]
            continue
        for x, y in anchors:
            stack.append((alo, x, blo, y))
            blocks.append((x, y, 1))
            alo, blo = x + 1, y + 1
        stack.append((alo, ahi, blo, bhi))
    blocks.sort()
    blocks.append((len(a), len(b), 0))
    return blocks


def _unique_anchors(
    a: list[str], b: list[str], alo: int, ahi: int, blo: int, bhi: int
) -> list[tuple[int, int]]:
    """Longest increasing run of lines occurring exactly once in each range."""
    count: dict[str, int] = {}
    where: dict[str, int] = {}
    for i in range(alo, ahi):
        count[a[i]] = count.get(a[i], 0) + 1
        where[a[i]] = i
    in_b: dict[str, int] = {}
    for j in range(blo, bhi):
        if count.get(b[j]) == 1:
            in_b[b[j]] = -1 if b[j] in in_b else j
    pairs = sorted((where[s], j) for s, j in in_b.items() if j >= 0)
    # Patience sorting: longest increasing subsequence of the `j`s.
    tails: list[int] = []
    tail_idx: list[int] = []
    prev: list[int] = [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        p = bisect_left(tails, j)
        prev[k] = tail_idx[p - 1] if p else -1
        if p == len(tails):
            tails.append(j)
            tail_idx.append(k)
        else:
            tails[p], tail_idx[p] = j, k
    out: list[tuple[int, int]] = []
    k = tail_idx[-1] if tail_idx else -1
    while k >= 0:
        out.append(pairs[k])
        k = prev[k]
    out.reverse()
    return out


@contextmanager
def _gc_paused() -> Generator[None]:
    # Indexing allocates ~10^6 long-lived objects; repeated full collections
    # of them cost ~20% of the run on large files.
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


def format_text(
    text: str,
    *,
    path: str | None = None,
    options: FormatOptions = FormatOptions(),  # noqa: B008 (frozen)
    lines: tuple[int, int] | None = None,
    debug: DebugOptions = DebugOptions(),  # noqa: B008 (frozen)
) -> FormatResult:
    """Format `text`; `lines` is an inclusive 1-based line range."""
    logical = path or STDIN_PATH
    if lines is not None and not 1 <= lines[0] <= lines[1]:
        raise ValueError(f"invalid line range {lines[0]}:{lines[1]}")
    with _gc_paused(), parse_text(text, logical) as parsed:
        if parsed.errors:
            raise ChplParseError(parsed.errors)
        index = TokenIndex.build(SourceText.from_text(text), parsed.asts)
        result, report = _print_text(index, options)
        if not debug.skip_verify:
            try:
                verify(
                    text,
                    result,
                    logical,
                    options,
                    input_parse=parsed,
                    input_index=index,
                )
            except VerificationError:
                if debug.dump_failed_dir is not None:
                    _dump_failed(debug.dump_failed_dir, logical, result)
                raise
    edits = compute_edits(text, result)
    return FormatResult(result, result != text, edits, report=report)


def _print_text(index: TokenIndex, options: FormatOptions) -> tuple[str, PrintReport]:
    p = Printer(index, options)
    return render(p.print_file(), options).text, p.report


def _dump_failed(directory: str, path: str, text: str) -> None:
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(path) + ".failed")
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text)
