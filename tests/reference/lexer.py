"""Python lexer retained as a differential oracle during the native migration."""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import NamedTuple

from chplfmt.lexer import PUNCTUATION, LexError
from chplfmt.source import Pos, SourceText


class TokenKind(StrEnum):
    IDENT = "IDENT"
    NUMBER = "NUMBER"
    STRING = "STRING"
    LINE_COMMENT = "LINE_COMMENT"
    BLOCK_COMMENT = "BLOCK_COMMENT"
    PUNCT = "PUNCT"
    OPAQUE = "OPAQUE"
    EOF = "EOF"


class Token(NamedTuple):
    kind: TokenKind
    text: str
    start_offset: int
    end_offset: int
    start: Pos
    end: Pos
    nl_before: int
    ws_before: bool
    match: int | None = None


_PUNCT_BY_LEN = tuple(
    frozenset(p for p in PUNCTUATION if len(p) == n) for n in (3, 2, 1)
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENT_START = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_")
_DIGITS = frozenset("0123456789")
_STRING_RES = {
    '"': re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"', re.S),
    "'": re.compile(r"'[^'\\]*(?:\\.[^'\\]*)*'", re.S),
}
_D = r"[0-9][0-9_]*"
_H = r"[0-9a-fA-F][0-9a-fA-F_]*"
_EXP = rf"[eE][+-]?{_D}"
_PEXP = rf"[pP][+-]?{_D}"
_NUMBER_RES = tuple(
    re.compile(p)
    for p in (
        r"0[bB][01][01_]*",
        r"0[oO][0-7][0-7_]*",
        _D,
        rf"0[xX]{_H}",
        rf"(?:{_D})?\.{_D}(?:{_EXP})?",
        rf"{_D}\.{_EXP}",
        rf"{_D}{_EXP}",
        rf"0[xX](?:{_H})?\.{_H}(?:{_PEXP})?",
        rf"0[xX]{_H}\.{_PEXP}",
        rf"0[xX]{_H}{_PEXP}",
    )
)
_GLUED = {"try": "!", "init": "=", "reduce": "="}
_SLOW_WORDS = frozenset({"b", *_GLUED})
_GUARDS = {
    "/": "(?![/*])",
    ".": "(?![0-9])",
    "?": "(?![A-Za-z_])",
    "@": "(?![A-Za-z_])",
}
_FAST_RE = re.compile(
    r"([ \t\r\n\f]*)(?:([A-Za-z_][A-Za-z0-9_]*)|("
    + "|".join(
        re.escape(p) + _GUARDS.get(p, "")
        for p in sorted(PUNCTUATION, key=len, reverse=True)
    )
    + "))?"
)


def _match_end(regex: re.Pattern[str], text: str, pos: int) -> int:
    match = regex.match(text, pos)
    assert match is not None
    return match.end()


def _number_end(text: str, pos: int) -> int:
    end = max(
        (match.end() for regex in _NUMBER_RES if (match := regex.match(text, pos))),
        default=pos,
    )
    if text.startswith("i", end):
        end += 1
    return end


def _block_comment_end(source: SourceText, pos: int) -> int:
    text = source.text
    close = text.find("*/", pos + 2)
    nested = text.find("/*", pos + 2)
    if close != -1 and (nested == -1 or nested > close):
        return close + 2
    depth, index, current, previous = 1, pos + 2, "", ""
    while depth > 0:
        if index >= len(text):
            raise LexError(source, pos, "unterminated block comment")
        previous_previous, previous, current = previous, current, text[index]
        index += 1
        if previous == "*" and current == "/" and previous_previous != "/":
            depth -= 1
        elif previous == "/" and current == "*":
            depth += 1
    return index


def _string_end(source: SourceText, pos: int, quote_pos: int) -> int:
    text = source.text
    quote = text[quote_pos]
    if text.startswith(quote * 3, quote_pos):
        close = text.find(quote * 3, quote_pos + 3)
        if close == -1:
            raise LexError(source, pos, "unterminated string literal")
        return close + 3
    match = _STRING_RES[quote].match(text, quote_pos)
    if match is None:
        raise LexError(source, pos, "unterminated string literal")
    return match.end()


def _scan(source: SourceText, pos: int) -> tuple[TokenKind, int]:
    text = source.text
    char = text[pos]
    next_char = text[pos + 1 : pos + 2]
    if char in _IDENT_START:
        end = _match_end(_IDENT_RE, text, pos)
        word = text[pos:end]
        after = text[end : end + 1]
        if word == "b" and after in ('"', "'"):
            return TokenKind.STRING, _string_end(source, pos, end)
        if after and _GLUED.get(word) == after:
            kind = TokenKind.PUNCT if word == "reduce" else TokenKind.IDENT
            return kind, end + 1
        return TokenKind.IDENT, end
    if char in _DIGITS or (char == "." and next_char in _DIGITS):
        return TokenKind.NUMBER, _number_end(text, pos)
    if char in "\"'":
        return TokenKind.STRING, _string_end(source, pos, pos)
    if char == "/" and next_char == "/":
        end = text.find("\n", pos)
        if end == -1:
            return TokenKind.LINE_COMMENT, len(text)
        if text[end - 1] == "\r":
            end -= 1
        return TokenKind.LINE_COMMENT, end
    if char == "/" and next_char == "*":
        return TokenKind.BLOCK_COMMENT, _block_comment_end(source, pos)
    if char in "?@" and next_char in _IDENT_START:
        return TokenKind.IDENT, _match_end(_IDENT_RE, text, pos + 1)
    for length, table in zip((3, 2, 1), _PUNCT_BY_LEN, strict=True):
        if text[pos : pos + length] in table:
            return TokenKind.PUNCT, pos + length
    raise LexError(source, pos, f"invalid character {char!r}")


def tokenize(source: SourceText, opaque: Iterable[tuple[int, int]] = ()) -> list[Token]:
    text = source.text
    length = len(text)
    ranges = sorted(opaque)
    range_index = 0
    fast = _FAST_RE.match
    raw: list[tuple[TokenKind, int, int, int]] = []
    pos = 0
    while True:
        gap_start = pos
        match = fast(text, pos)
        assert match is not None
        pos = match.end(1)
        next_opaque = (
            ranges[range_index][0] if range_index < len(ranges) else length + 1
        )
        if next_opaque < pos:
            raise LexError(source, next_opaque, "opaque range starts inside whitespace")
        if pos >= length:
            break
        if next_opaque == pos:
            kind, end = TokenKind.OPAQUE, ranges[range_index][1]
            range_index += 1
        else:
            group = match.lastindex
            if group == 2 and match.group(2) not in _SLOW_WORDS:
                kind, end = TokenKind.IDENT, match.end()
            elif group == 3:
                kind, end = TokenKind.PUNCT, match.end()
            else:
                kind, end = _scan(source, pos)
            if end > next_opaque:
                raise LexError(
                    source, next_opaque, "opaque range starts inside a token"
                )
        raw.append((kind, gap_start, pos, end))
        pos = end
    if range_index < len(ranges):
        raise LexError(source, ranges[range_index][0], "opaque range outside the text")
    raw.append((TokenKind.EOF, gap_start, length, length))

    matches: list[int | None] = [None] * len(raw)
    stack: list[int] = []
    for index, (kind, _, start, end) in enumerate(raw):
        if kind is not TokenKind.PUNCT or end - start != 1:
            continue
        char = text[start]
        if char in "([{":
            stack.append(index)
        elif char in ")]}":
            opening = {")": "(", "]": "[", "}": "{"}[char]
            if not stack or text[raw[stack[-1]][2]] != opening:
                raise LexError(source, start, f"unmatched {char!r}")
            partner = stack.pop()
            matches[index], matches[partner] = partner, index
    if stack:
        start = raw[stack[-1]][2]
        raise LexError(source, start, f"unmatched {text[start]!r}")

    starts = [token[2] for token in raw]
    ends = [token[3] for token in raw]
    start_pos = source.positions(starts)
    end_pos = source.positions(ends)
    nl_before = [
        start[0] - end[0]
        for start, end in zip(start_pos, [(1, 1), *end_pos], strict=False)
    ]
    return list(
        map(
            Token,
            [token[0] for token in raw],
            [text[start:end] for start, end in zip(starts, ends, strict=True)],
            starts,
            ends,
            start_pos,
            end_pos,
            nl_before,
            [token[2] > token[1] for token in raw],
            matches,
        )
    )
