"""Prettier-style renderer for the document IR (design section 7.6)."""

from __future__ import annotations

import sys
from collections import ChainMap
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass

from chplfmt.config import FormatOptions
from chplfmt.doc.ir import (
    Align,
    Check,
    ColumnText,
    Concat,
    ConditionalGroup,
    Doc,
    DocLike,
    Fill,
    Group,
    GroupId,
    IfBreak,
    Indent,
    Line,
    LineSuffix,
    SuffixBreak,
    Text,
    TrailingComment,
    Verbatim,
    concat,
    hardline,
    literalline,
)
from chplfmt.source import display_width

FLAT = False
BREAK = True


@dataclass(frozen=True, slots=True)
class LineRecord:
    """One output line: code, its trailing `//` comment, and whether it has verbatim text."""

    code: str
    trailing_comment: str | None = None
    verbatim: bool = False


@dataclass(frozen=True, slots=True)
class RenderResult:
    text: str
    lines: list[LineRecord]


@dataclass(frozen=True, slots=True, eq=False)
class _FillAt:
    fill: Fill
    start: int


type _Node = Doc | _FillAt
type _Cmd = tuple[int, bool, _Node]
type _Rests = tuple[list[_Cmd], ...]


def render(doc: DocLike, options: FormatOptions, base_indent: int = 0) -> RenderResult:
    """Lay out `doc`; every line, the first included, starts at `base_indent`."""
    root = concat(doc)
    p = _Printer(options, {}, {}, (), measure=False, pos=base_indent)
    if base_indent:
        p.buf.append(" " * base_indent)
    p.run([(base_indent, BREAK, root)])
    p.finish()
    lines = p.records
    out = align_trailing_comments(lines, options.line_length, options.tab_size)
    return RenderResult("\n".join(out), lines)


def align_trailing_comments(
    lines: Sequence[LineRecord], line_length: int, tab_size: int
) -> list[str]:
    """Join code and trailing comments, aligning comments across runs of lines."""
    limit = line_length or sys.maxsize
    out: list[str] = []
    run: list[tuple[str, int, str]] = []
    col = 0
    allowed = sys.maxsize
    for rec in lines:
        c = rec.trailing_comment
        if c is None or rec.verbatim or not rec.code:
            _flush(run, col, out)
            out.append(rec.code if c is None else f"{rec.code} {c}" if rec.code else c)
            continue
        w = display_width(rec.code, 0, tab_size)
        cw = display_width(c, 0, tab_size)
        # Latest comment start that keeps it within the limit, if one space would.
        own = limit - cw if w + 1 + cw <= limit else sys.maxsize
        if run and max(col, w) + 1 > min(allowed, own):
            _flush(run, col, out)
        if run:
            col, allowed = max(col, w), min(allowed, own)
        else:
            col, allowed = w, own
        run.append((rec.code, w, c))
    _flush(run, col, out)
    return out


def _flush(run: list[tuple[str, int, str]], col: int, out: list[str]) -> None:
    for code, w, c in run:
        out.append(code + " " * (col + 1 - w) + c)
    run.clear()


class _Printer:
    """Runs the command stack; in `measure` mode it only checks that lines fit."""

    def __init__(
        self,
        options: FormatOptions,
        group_modes: MutableMapping[GroupId, bool],
        memo: dict[tuple[int, int, int, int], int],
        rests: _Rests,
        *,
        measure: bool,
        pos: int,
    ) -> None:
        self.options = options
        self.tab = options.tab_size
        self.limit = options.line_length or sys.maxsize
        self.group_modes = group_modes
        self.memo = memo
        self.rests = rests
        self.measure = measure
        self.pos = pos
        self.buf: list[str] = []
        self.protect = 0
        self.comment: str | None = None
        self.line_verbatim = False
        self.records: list[LineRecord] = []
        self.suffixes: list[_Cmd] = []
        self.remeasure = False

    def finish(self) -> None:
        """End the current line, trimming trailing whitespace outside verbatim text."""
        if not self.measure:
            buf = self.buf
            p = self.protect
            code = "".join(buf[:p]) + "".join(buf[p:]).rstrip(" \t")
            self.records.append(LineRecord(code, self.comment, self.line_verbatim))
            buf.clear()
            self.protect = 0
            self.comment = None
        self.line_verbatim = False

    def _newline(self, ind: int) -> None:
        self.finish()
        if ind and not self.measure:
            self.buf.append(" " * ind)
        self.pos = ind

    def run(self, cmds: list[_Cmd]) -> bool:
        """Process `cmds`; False as soon as a measured line is too long."""
        tab = self.tab
        measure = self.measure
        limit = self.limit
        buf = self.buf
        while True:
            if not cmds:
                if not self.suffixes:
                    return True
                cmds.extend(reversed(self.suffixes))
                self.suffixes.clear()
                continue
            ind, mode, d = cmds.pop()
            if isinstance(d, Text):
                if not measure:
                    buf.append(d.s)
                w = d.width
                self.pos = self.pos + w if w >= 0 else display_width(d.s, self.pos, tab)
                if measure and self.pos > limit and not self.line_verbatim:
                    return False
            elif isinstance(d, Concat):
                cmds.extend([(ind, mode, p) for p in reversed(d.parts)])
            elif isinstance(d, Line):
                if mode == FLAT and not d.hard:
                    if not d.soft:
                        if not measure:
                            buf.append(" ")
                        self.pos += 1
                    continue
                if mode == FLAT:
                    self.remeasure = True
                if self.suffixes:
                    cmds.append((ind, mode, d))
                    cmds.extend(reversed(self.suffixes))
                    self.suffixes.clear()
                    continue
                self._newline(0 if d.literal else ind)
            elif isinstance(d, Group):
                broken = d.forced
                if mode == FLAT and not self.remeasure:
                    m = broken
                else:
                    self.remeasure = False
                    m = broken or not self._fits(
                        [(ind, FLAT, d.contents)], (cmds, *self.rests), self.pos, False
                    )
                if d.id is not None:
                    self.group_modes[d.id] = m
                cmds.append((ind, m, d.contents))
            elif isinstance(d, Indent):
                cmds.append((ind + d.n, mode, d.contents))
            elif isinstance(d, Align):
                cmds.append((self.pos, mode, d.contents))
            elif isinstance(d, Fill):
                self._fill(d, 0, ind, mode, cmds)
            elif isinstance(d, _FillAt):
                self._fill(d.fill, d.start, ind, mode, cmds)
            elif isinstance(d, IfBreak):
                gid = d.group_id
                gm = mode if gid is None else self.group_modes.get(gid, FLAT)
                cmds.append((ind, mode, d.broken if gm else d.flat))
            elif isinstance(d, ConditionalGroup):
                if mode == FLAT and not self.remeasure and not d.forced:
                    cmds.append((ind, FLAT, d.alts[0]))
                else:
                    self.remeasure = False
                    cmds.append(self._select(d, ind, cmds))
            elif isinstance(d, LineSuffix):
                if not measure:
                    self.suffixes.append((ind, mode, d.contents))
            elif isinstance(d, TrailingComment):
                if not measure:
                    c = self.comment
                    self.comment = d.text if c is None else f"{c} {d.text}"
            elif isinstance(d, Verbatim):
                if d.bol:
                    if not measure and (self.suffixes or "".join(buf).strip(" ")):
                        cmds += [(ind, mode, d), (ind, mode, literalline)]
                        continue
                    buf.clear()
                    self.protect = 0
                    self.pos = 0
                for i, seg in enumerate(d.s.split("\n")):
                    if i:
                        self.finish()
                        self.pos = 0
                    if not seg:
                        continue
                    if not measure:
                        buf.append(seg)
                        self.protect = len(buf)
                    self.pos = display_width(seg, self.pos, tab)
                    self.line_verbatim = True
            elif isinstance(d, ColumnText):
                for i, seg in enumerate(d.make(self.pos).split("\n")):
                    if i:
                        self.finish()
                        self.pos = 0
                    if not measure:
                        buf.append(seg)
                    self.pos = display_width(seg, self.pos, tab)
            elif isinstance(d, SuffixBreak) and self.suffixes:
                cmds.append((ind, mode, hardline))
            # BreakParent prints nothing.

    def _fill(self, f: Fill, i: int, ind: int, mode: bool, cmds: list[_Cmd]) -> None:
        parts = f.parts
        n = len(parts) - i
        if n <= 0:
            return
        content = parts[i]
        # The last content is measured with what follows it, up to the next break.
        rests: _Rests = (cmds, *self.rests)
        content_fits = self._fits(
            [(ind, FLAT, content)], rests if n == 1 else (), self.pos, True
        )
        if n == 1:
            cmds.append((ind, not content_fits, content))
            return
        ws = parts[i + 1]
        if n == 2:
            cmds.append((ind, not content_fits, ws))
            cmds.append((ind, not content_fits, content))
            return
        pair_fits = content_fits and self._fits(
            [(ind, FLAT, parts[i + 2]), (ind, FLAT, ws), (ind, FLAT, content)],
            rests if n == 3 else (),
            self.pos,
            True,
        )
        cmds.append((ind, mode, _FillAt(f, i + 2)))
        cmds.append((ind, not pair_fits, ws))
        cmds.append((ind, not content_fits, content))

    def _select(self, d: ConditionalGroup, ind: int, cmds: list[_Cmd]) -> _Cmd:
        alts = d.alts
        rests: _Rests = (cmds, *self.rests)
        first = alts[0]
        if not first.forced and self._fits(
            [(ind, FLAT, first)], rests, self.pos, False
        ):
            return (ind, FLAT, first)
        if d.check is Check.FIRST_LINE:
            for a in alts[:-1]:
                if self._fits([(ind, BREAK, a)], rests, self.pos, False):
                    return (ind, BREAK, a)
            return (ind, BREAK, alts[-1])
        rest_w = self._scan([], rests, 0, False)
        if rest_w < 0:
            rest_w = self.limit + 1
        key = (id(d), self.pos, ind, rest_w)
        idx = self.memo.get(key)
        if idx is None:
            idx = len(alts) - 1
            for i, a in enumerate(alts[:-1]):
                if self._all_lines_fit(a, ind, cmds, rest_w):
                    idx = i
                    break
            self.memo[key] = idx
        return (ind, BREAK, alts[idx])

    def _all_lines_fit(self, alt: Doc, ind: int, cmds: list[_Cmd], rest_w: int) -> bool:
        sub = _Printer(
            self.options,
            ChainMap({}, self.group_modes),
            self.memo,
            (cmds, *self.rests),
            measure=True,
            pos=self.pos,
        )
        sub.line_verbatim = self.line_verbatim
        if not sub.run([(ind, BREAK, alt)]):
            return False
        return sub.line_verbatim or sub.pos + rest_w <= self.limit

    def _fits(
        self, nxt: list[_Cmd], rests: _Rests, col: int, must_be_flat: bool
    ) -> bool:
        return self._scan(nxt, rests, col, must_be_flat) >= 0

    def _scan(
        self, nxt: list[_Cmd], rests: _Rests, col: int, must_be_flat: bool
    ) -> int:
        """Column reached at the first possible line break, or -1 if it doesn't fit."""
        limit = self.limit
        tab = self.tab
        stack = nxt
        ri = -1
        rj = 0
        while True:
            if not stack:
                while rj == 0:
                    ri += 1
                    if ri == len(rests):
                        return col
                    rj = len(rests[ri])
                rj -= 1
                stack.append(rests[ri][rj])
                must_be_flat = False
            _, mode, d = stack.pop()
            if isinstance(d, Text):
                w = d.width
                col = col + w if w >= 0 else display_width(d.s, col, tab)
                if col > limit:
                    return -1
            elif isinstance(d, Concat):
                stack.extend([(0, mode, p) for p in reversed(d.parts)])
            elif isinstance(d, Line):
                if mode or d.hard:
                    return col
                if not d.soft:
                    col += 1
                    if col > limit:
                        return -1
            elif isinstance(d, Group):
                b = d.forced
                if must_be_flat and b:
                    return -1
                stack.append((0, b or mode, d.contents))
            elif isinstance(d, ConditionalGroup):
                b = d.forced
                if must_be_flat and b:
                    return -1
                m = b or mode
                stack.append((0, m, d.alts[-1] if m else d.alts[0]))
            elif isinstance(d, Indent | Align):
                stack.append((0, mode, d.contents))
            elif isinstance(d, Fill):
                stack.extend([(0, mode, p) for p in reversed(d.parts)])
            elif isinstance(d, _FillAt):
                parts = d.fill.parts
                stack.extend(
                    [
                        (0, mode, parts[k])
                        for k in range(len(parts) - 1, d.start - 1, -1)
                    ]
                )
            elif isinstance(d, IfBreak):
                gid = d.group_id
                gm = mode if gid is None else self.group_modes.get(gid, FLAT)
                stack.append((0, mode, d.broken if gm else d.flat))
            elif isinstance(d, Verbatim):
                head, nl, _ = d.s.partition("\n")
                col = display_width(head, 0 if d.bol else col, tab)
                if nl:
                    return col
                if col > limit:
                    return -1
            elif isinstance(d, ColumnText):
                head = d.make(col).partition("\n")[0]
                return display_width(head, col, tab)
            # LineSuffix, TrailingComment, BreakParent, SuffixBreak: zero width.
