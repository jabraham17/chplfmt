"""Immutable source text with conversions between dyno positions, offsets, and columns."""

from __future__ import annotations

import unicodedata
from bisect import bisect_right
from collections.abc import Sequence
from itertools import repeat

DEFAULT_TAB_SIZE = 2

# A dyno position: 1-based line and 1-based UTF-8 byte column (a tab counts as 1).
Pos = tuple[int, int]


class SourceDecodeError(ValueError):
    """The input is not valid UTF-8."""

    def __init__(self, line: int, byte_col: int, reason: str) -> None:
        self.line = line
        self.byte_col = byte_col
        super().__init__(f"{line}:{byte_col}: invalid UTF-8 ({reason})")


def char_width(ch: str) -> int:
    """Display width of one code point: 2 for East Asian Wide/Fullwidth, else 1."""
    if ch < "\u1100":
        return 1
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(
    text: str, start_col: int = 0, tab_size: int = DEFAULT_TAB_SIZE
) -> int:
    """Return the 0-based display column reached after `text` starting at `start_col`.

    A tab advances to the next multiple of `tab_size`, measured from the
    absolute column; a newline restarts at column 0.
    """
    if text.isascii() and "\t" not in text and "\n" not in text:
        return start_col + len(text)
    col = start_col
    for ch in text:
        if ch == "\t":
            col += tab_size - col % tab_size
        elif ch == "\n":
            col = 0
        else:
            col += char_width(ch)
    return col


class SourceText:
    """The original bytes and decoded text of one file.

    Offsets are code-point indices into `text`. Lines are separated by `\\n`
    only, as in dyno; a `\\r` right before `\\n` belongs to the line ending.
    """

    data: bytes
    text: str
    line_starts: tuple[int, ...]
    uses_crlf: bool
    _ascii: tuple[bool, ...]

    def __init__(self, data: bytes, text: str) -> None:
        starts = [0]
        i = text.find("\n")
        while i != -1:
            starts.append(i + 1)
            i = text.find("\n", i + 1)
        ends = [*starts[1:], len(text)]
        init = object.__setattr__
        init(self, "data", data)
        init(self, "text", text)
        init(self, "line_starts", tuple(starts))
        init(self, "uses_crlf", "\r\n" in text)
        init(
            self,
            "_ascii",
            tuple(text[s:e].isascii() for s, e in zip(starts, ends, strict=True)),
        )

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SourceText is immutable")

    @classmethod
    def from_bytes(cls, data: bytes) -> SourceText:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as e:
            line = data.count(b"\n", 0, e.start) + 1
            col = e.start - (data.rfind(b"\n", 0, e.start) + 1) + 1
            raise SourceDecodeError(line, col, e.reason) from None
        return cls(data, text)

    @classmethod
    def from_text(cls, text: str) -> SourceText:
        return cls(text.encode("utf-8"), text)

    def __repr__(self) -> str:
        return f"SourceText({len(self.text)} chars, {self.line_count} lines)"

    @property
    def line_count(self) -> int:
        return len(self.line_starts)

    def line_start(self, line: int) -> int:
        """Offset of the first character of 1-based `line`."""
        if not 1 <= line <= len(self.line_starts):
            raise ValueError(f"line {line} out of range")
        return self.line_starts[line - 1]

    def line_end(self, line: int) -> int:
        """Offset just past the line's content (before `\\r\\n` or `\\n`)."""
        start = self.line_start(line)
        if line == len(self.line_starts):
            return len(self.text)
        end = self.line_starts[line] - 1
        if end > start and self.text[end - 1] == "\r":
            end -= 1
        return end

    def line_text(self, line: int) -> str:
        """The line's content without its line ending."""
        return self.text[self.line_start(line) : self.line_end(line)]

    def line_of(self, offset: int) -> int:
        """1-based line containing `offset` (`len(text)` is on the last line)."""
        if not 0 <= offset <= len(self.text):
            raise ValueError(f"offset {offset} out of range")
        return bisect_right(self.line_starts, offset)

    def pos(self, offset: int) -> Pos:
        """Convert a code-point offset to a dyno `(line, byte_col)` position."""
        line = self.line_of(offset)
        start = self.line_starts[line - 1]
        if self._ascii[line - 1]:
            return line, offset - start + 1
        return line, len(self.text[start:offset].encode("utf-8")) + 1

    def positions(self, offsets: Sequence[int]) -> list[Pos]:
        """`pos` of each offset."""
        if offsets and not (min(offsets) >= 0 and max(offsets) <= len(self.text)):
            raise ValueError("offset out of range")
        starts = self.line_starts
        lines = list(map(bisect_right, repeat(starts, len(offsets)), offsets))
        out = [
            (k, off - starts[k - 1] + 1) for k, off in zip(lines, offsets, strict=True)
        ]
        if not all(self._ascii):
            ascii_ = self._ascii
            for i, k in enumerate(lines):
                if not ascii_[k - 1]:
                    out[i] = self.pos(offsets[i])
        return out

    def offset(self, pos: Pos) -> int:
        """Convert a dyno `(line, byte_col)` position to a code-point offset."""
        line, col = pos
        start = self.line_start(line)
        # The last valid offset on a line is that of its '\n' (or EOF).
        limit = self.line_starts[line] - 1 if line < self.line_count else len(self.text)
        if col < 1:
            raise ValueError(f"position {pos} out of range")
        if self._ascii[line - 1]:
            if start + col - 1 > limit:
                raise ValueError(f"position {pos} out of range")
            return start + col - 1
        encoded = self.text[start:limit].encode("utf-8")
        if col - 1 > len(encoded):
            raise ValueError(f"position {pos} out of range")
        try:
            return start + len(encoded[: col - 1].decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError(f"position {pos} is inside a character") from None

    def display_column(self, offset: int, tab_size: int = DEFAULT_TAB_SIZE) -> int:
        """0-based display column of `offset` within its line."""
        start = self.line_starts[self.line_of(offset) - 1]
        return display_width(self.text[start:offset], 0, tab_size)
