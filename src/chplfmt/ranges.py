"""Range formatting (design section 7.10).

The printer builds the whole file's Doc as usual; every statement list checks
whether it is the deepest one containing the range and, if so, builds the run
of selected items at the existing indentation of the run's first line
(`select`). `splice` renders that run and replaces its source lines.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chplfmt.doc import Doc, align_trailing_comments, render
from chplfmt.doc.render import LineRecord
from chplfmt.lexer import TokenKind
from chplfmt.source import SourceText, display_width

if TYPE_CHECKING:
    from chplfmt.printer.core import Element, Printer


@dataclass
class Selection:
    """The selected run `elements[lo:hi]` of a statement list at nesting `depth`."""

    depth: int
    lo: int
    hi: int
    first_line: int = 0  # 1-based, inclusive source lines of the run
    last_line: int = 0
    base: int = 0  # display indentation of `first_line`
    doc: Doc | None = None


def _offsets(p: Printer, el: Element) -> tuple[int, int]:
    """Source offsets `[start, end)` of an item with its comments."""
    tokens = p.tokens
    nodes = el.swallowed if el.region is not None else [el.node] if el.node else []
    start = tokens[el.first].start_offset
    end = tokens[el.last].end_offset
    if el.region is not None:
        start, end = el.region.start, el.region.end
    for n in nodes:
        for c in p.trivia.leading(n):
            start = min(start, tokens[c.token].start_offset)
        for c in p.trivia.trailing(n):
            end = max(end, tokens[c.token].end_offset)
    return start, end


def _blank(s: str) -> bool:
    return not s.strip(" \t\f\r")


def select(p: Printer, elements: Sequence[Element]) -> Selection | None:
    """The run of `elements` intersecting `p.range_lines` if this list contains it.

    Returns None when the range isn't inside the list's lines (the file's list
    takes any range), or when the run doesn't occupy whole lines (an enclosing
    list then takes the range).
    """
    assert p.range_lines is not None
    a, b = p.range_lines
    src = p.source
    spans = [_offsets(p, el) for el in elements]
    lines = [(src.line_of(s), src.line_of(max(s, e - 1))) for s, e in spans]
    if not lines or (p.list_depth and (a < lines[0][0] or b > lines[-1][1])):
        return None
    hit = [k for k, (s, e) in enumerate(lines) if s <= b and a <= e]
    sel = Selection(p.list_depth, hit[0] if hit else 0, hit[-1] + 1 if hit else 0)
    if not hit:
        return sel
    start, end = spans[sel.lo][0], spans[sel.hi - 1][1]
    first, last = lines[sel.lo][0], lines[sel.hi - 1][1]
    text = src.text
    if not _blank(text[src.line_start(first) : start]) or not _blank(
        text[end : max(end, src.line_end(last))]
    ):
        return None
    head = src.line_text(first)
    sel.first_line, sel.last_line = first, last
    sel.base = display_width(
        head[: len(head) - len(head.lstrip())], 0, p.options.tab_size
    )
    return sel


_LINE = re.compile(r"[^\n]*\n|[^\n]+")


def _commented_line(p: Printer, starts: list[int], line: int) -> LineRecord | None:
    """Source `line` as code plus trailing `//` comment, if it is exactly that."""
    src = p.source
    if not 1 <= line <= src.line_count:
        return None
    ls, le = src.line_start(line), src.line_end(line)
    if any(r.start < le and r.end > ls for r in p.off.regions):
        return None
    tokens = p.tokens
    i = bisect_left(starts, ls)
    if i and tokens[i - 1].end_offset > ls:
        return None  # continues a multi-line token
    j = i
    while j < len(tokens) and tokens[j].start_offset < le:
        if tokens[j].end_offset > le:
            return None
        j += 1
    if j - i < 2 or tokens[j - 1].kind is not TokenKind.LINE_COMMENT:
        return None
    c = tokens[j - 1]
    return LineRecord(src.text[ls : c.start_offset].rstrip(), c.text)


def _align_with_context(p: Printer, sel: Selection, records: list[LineRecord]) -> str:
    """Join `records`, aligning trailing comments as a whole-file format would.

    A run of aligned comments may continue into the unchanged lines around the
    range, so those lines join the alignment without being rewritten.
    """
    starts = [t.start_offset for t in p.tokens]
    above: list[LineRecord] = []
    line = sel.first_line - 1
    while rec := _commented_line(p, starts, line):
        above.append(rec)
        line -= 1
    above.reverse()
    below: list[LineRecord] = []
    line = sel.last_line + 1
    while rec := _commented_line(p, starts, line):
        below.append(rec)
        line += 1
    o = p.options
    out = align_trailing_comments(above + records + below, o.line_length, o.tab_size)
    return "\n".join(out[len(above) : len(above) + len(records)])


def splice(source: SourceText, sel: Selection, p: Printer) -> str:
    """`source` with the selected lines replaced by the rendered run."""
    assert sel.doc is not None
    old = _LINE.findall(source.text)
    first, last = sel.first_line - 1, sel.last_line
    eol = "\r\n" if old[first].endswith("\r\n") else "\n"
    last_eol = old[last - 1][len(old[last - 1].rstrip("\r\n")) :]
    rendered = _align_with_context(
        p, sel, render(sel.doc, p.options, base_indent=sel.base).lines
    )
    new = [ln + "\n" if ln.endswith("\r") else ln + eol for ln in rendered.split("\n")]
    if not rendered.strip():
        new = []  # every item was dropped (remove-empty-statements)
    elif not last_eol:
        new[-1] = new[-1].removesuffix(eol)
    return "".join(old[:first] + new + old[last:])
