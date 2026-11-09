"""Chapel tokenizer (design section 7.3), following dyno's flex rules (`chpl.lex`)."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from enum import StrEnum
from typing import NamedTuple

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


COMMENT_KINDS = frozenset({TokenKind.LINE_COMMENT, TokenKind.BLOCK_COMMENT})


class Token(NamedTuple):
    # A NamedTuple: building ~10^5 tokens per file is much cheaper than a dataclass.
    kind: TokenKind
    text: str
    start_offset: int  # code-point offsets into SourceText.text; end is exclusive
    end_offset: int
    start: Pos  # dyno convention: 1-based (line, byte_col); end is exclusive
    end: Pos
    nl_before: int  # newlines in the whitespace gap before this token
    ws_before: bool  # the gap before this token is non-empty
    match: int | None = None  # index of the partner bracket

    @property
    def is_comment(self) -> bool:
        return self.kind in COMMENT_KINDS


class LexError(Exception):
    """The text can't be tokenized, or the lexer disagrees with the parser."""

    def __init__(self, source: SourceText, offset: int, message: str) -> None:
        self.offset = offset
        self.pos = source.pos(min(offset, len(source.text)))
        super().__init__(f"{self.pos[0]}:{self.pos[1]}: {message}")


WHITESPACE = " \t\r\n\f"
OPEN_BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSE_BRACKETS = {v: k for k, v in OPEN_BRACKETS.items()}

# Every operator and punctuation token in chpl.lex. `<~>` is not one.
PUNCTUATION = frozenset(
    {
        *("**=", "&&=", "||=", "<<=", ">>=", "<=>", "..<", "..."),
        *("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "=>", ".."),
        *("&&", "||", "<<", ">>", "==", "!=", "<=", ">=", "--", "++", "**"),
        *"=#!&|^~<>+-*/%:;,.()[]{}?@",
    }
)
_PUNCT_BY_LEN = tuple(
    frozenset(p for p in PUNCTUATION if len(p) == n) for n in (3, 2, 1)
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")  # chpl.lex has no `$`
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
# The literal rules of chpl.lex; flex takes the longest match among them.
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

# Keywords that dyno lexes together with the next character (`proc(` is split).
_GLUED = {"try": "!", "init": "=", "reduce": "="}

# Whitespace, then (in the common cases) an identifier or punctuation that
# `_scan` would return unchanged; anything else goes through `_scan`.
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
    m = regex.match(text, pos)
    assert m is not None
    return m.end()


def _number_end(text: str, pos: int) -> int:
    end = max((m.end() for r in _NUMBER_RES if (m := r.match(text, pos))), default=pos)
    if text.startswith("i", end):
        end += 1  # imaginary literal
    return end


def _block_comment_end(source: SourceText, pos: int) -> int:
    text = source.text
    close = text.find("*/", pos + 2)
    nested = text.find("/*", pos + 2)
    if close != -1 and (nested == -1 or nested > close):
        return close + 2
    # Port of dyno's processBlockComment, including its `/*/` handling.
    depth, i, c, lastc = 1, pos + 2, "", ""
    while depth > 0:
        if i >= len(text):
            raise LexError(source, pos, "unterminated block comment")
        lastlastc, lastc, c = lastc, c, text[i]
        i += 1
        if lastc == "*" and c == "/" and lastlastc != "/":
            depth -= 1
        elif lastc == "/" and c == "*":
            depth += 1
    return i


def _string_end(source: SourceText, pos: int, quote_pos: int) -> int:
    text = source.text
    q = text[quote_pos]
    if text.startswith(q * 3, quote_pos):
        # Triple-quoted strings have no escapes; the first closing triple ends them.
        close = text.find(q * 3, quote_pos + 3)
        if close == -1:
            raise LexError(source, pos, "unterminated string literal")
        return close + 3
    m = _STRING_RES[q].match(text, quote_pos)
    if m is None:
        raise LexError(source, pos, "unterminated string literal")
    return m.end()


def _scan(source: SourceText, pos: int) -> tuple[TokenKind, int]:
    """Return the kind and end offset of the token starting at `pos`."""
    text = source.text
    c = text[pos]
    nxt = text[pos + 1 : pos + 2]
    if c in _IDENT_START:
        end = _match_end(_IDENT_RE, text, pos)
        word = text[pos:end]
        after = text[end : end + 1]
        if word == "b" and after in ('"', "'"):
            return TokenKind.STRING, _string_end(source, pos, end)
        if after and _GLUED.get(word) == after:
            kind = TokenKind.PUNCT if word == "reduce" else TokenKind.IDENT
            return kind, end + 1
        return TokenKind.IDENT, end
    if c in _DIGITS or (c == "." and nxt in _DIGITS):
        return TokenKind.NUMBER, _number_end(text, pos)
    if c in "\"'":
        return TokenKind.STRING, _string_end(source, pos, pos)
    if c == "/" and nxt == "/":
        end = text.find("\n", pos)
        if end == -1:
            return TokenKind.LINE_COMMENT, len(text)
        if text[end - 1] == "\r":
            end -= 1
        return TokenKind.LINE_COMMENT, end
    if c == "/" and nxt == "*":
        return TokenKind.BLOCK_COMMENT, _block_comment_end(source, pos)
    if c in "?@" and nxt in _IDENT_START:
        # `?t` (type query) and `@attr` are single tokens in dyno.
        return TokenKind.IDENT, _match_end(_IDENT_RE, text, pos + 1)
    for n, table in zip((3, 2, 1), _PUNCT_BY_LEN, strict=True):
        if text[pos : pos + n] in table:
            return TokenKind.PUNCT, pos + n
    raise LexError(source, pos, f"invalid character {c!r}")


def tokenize(source: SourceText, opaque: Iterable[tuple[int, int]] = ()) -> list[Token]:
    """Tokenize `source`, ending with an EOF token.

    `opaque` lists `(start_offset, end_offset)` ranges (from `ExternBlock`
    nodes) that become single OPAQUE tokens without being looked into.
    """
    text = source.text
    n = len(text)
    ranges = sorted(opaque)
    ri = 0
    fast = _FAST_RE.match
    raw: list[tuple[TokenKind, int, int, int]] = []
    pos = 0
    while True:
        gap_start = pos
        m = fast(text, pos)
        assert m is not None
        pos = m.end(1)
        next_opaque = ranges[ri][0] if ri < len(ranges) else n + 1
        if next_opaque < pos:
            raise LexError(source, next_opaque, "opaque range starts inside whitespace")
        if pos >= n:
            break
        if next_opaque == pos:
            kind, end = TokenKind.OPAQUE, ranges[ri][1]
            ri += 1
        else:
            g = m.lastindex
            if g == 2 and m.group(2) not in _SLOW_WORDS:
                kind, end = TokenKind.IDENT, m.end()
            elif g == 3:
                kind, end = TokenKind.PUNCT, m.end()
            else:
                kind, end = _scan(source, pos)
            if end > next_opaque:
                raise LexError(
                    source, next_opaque, "opaque range starts inside a token"
                )
        raw.append((kind, gap_start, pos, end))
        pos = end
    if ri < len(ranges):
        raise LexError(source, ranges[ri][0], "opaque range outside the text")
    raw.append((TokenKind.EOF, gap_start, n, n))

    matches: list[int | None] = [None] * len(raw)
    stack: list[int] = []
    for i, (kind, _, start, end) in enumerate(raw):
        if kind is not TokenKind.PUNCT or end - start != 1:
            continue
        ch = text[start]
        if ch in OPEN_BRACKETS:
            stack.append(i)
        elif ch in CLOSE_BRACKETS:
            if not stack or text[raw[stack[-1]][2]] != CLOSE_BRACKETS[ch]:
                raise LexError(source, start, f"unmatched {ch!r}")
            j = stack.pop()
            matches[i], matches[j] = j, i
    if stack:
        raise LexError(
            source, raw[stack[-1]][2], f"unmatched {text[raw[stack[-1]][2]]!r}"
        )

    starts = [r[2] for r in raw]
    ends = [r[3] for r in raw]
    start_pos = source.positions(starts)
    end_pos = source.positions(ends)
    # The gap begins at the previous token's end, so this counts its newlines.
    nl_before = [
        p[0] - q[0] for p, q in zip(start_pos, [(1, 1), *end_pos], strict=False)
    ]
    return list(
        map(
            Token,
            [r[0] for r in raw],
            [text[s:e] for s, e in zip(starts, ends, strict=True)],
            starts,
            ends,
            start_pos,
            end_pos,
            nl_before,
            [r[2] > r[1] for r in raw],
            matches,
        )
    )


def check_invariants(source: SourceText, tokens: Sequence[Token]) -> list[str]:
    """Return violations of the lexer invariants (empty if all hold)."""
    text = source.text
    problems: list[str] = []
    pos = 0
    for i, t in enumerate(tokens):
        gap = text[pos : t.start_offset]
        where = f"token {i} at {t.start}"
        if t.start_offset < pos or t.end_offset < t.start_offset:
            problems.append(f"{where}: offsets out of order")
        if gap.strip(WHITESPACE):
            problems.append(f"{where}: non-whitespace gap {gap!r}")
        if t.nl_before != gap.count("\n") or t.ws_before != bool(gap):
            problems.append(f"{where}: wrong nl_before/ws_before")
        if text[t.start_offset : t.end_offset] != t.text:
            problems.append(f"{where}: text {t.text!r} differs from the source")
        if source.pos(t.start_offset) != t.start or source.pos(t.end_offset) != t.end:
            problems.append(f"{where}: wrong position")
        if t.match is not None:
            other = tokens[t.match]
            pair = (t.text, other.text) if t.match > i else (other.text, t.text)
            if other.match != i or OPEN_BRACKETS.get(pair[0]) != pair[1]:
                problems.append(f"{where}: bad bracket match")
        elif t.kind is TokenKind.PUNCT and (
            t.text in OPEN_BRACKETS or t.text in CLOSE_BRACKETS
        ):
            problems.append(f"{where}: unmatched bracket")
        pos = t.end_offset
    if not tokens or tokens[-1].kind is not TokenKind.EOF or pos != len(text):
        problems.append("missing EOF token at the end of the text")
    elif any(t.kind is TokenKind.EOF for t in tokens[:-1]):
        problems.append("EOF token before the end")
    rebuilt = "".join(
        text[(tokens[i - 1].end_offset if i else 0) : t.start_offset] + t.text
        for i, t in enumerate(tokens)
    )
    if rebuilt != text:
        problems.append("gaps and tokens don't reproduce the source")
    return problems


def format_tokens(tokens: Iterable[Token]) -> str:
    """One line per token, for golden files and debugging."""
    lines: list[str] = []
    for i, t in enumerate(tokens):
        (l1, c1), (l2, c2) = t.start, t.end
        match = "" if t.match is None else f" match={t.match}"
        ws = f" nl={t.nl_before}" if t.nl_before else (" ws" if t.ws_before else "")
        lines.append(f"{i} {t.kind} {l1}:{c1}-{l2}:{c2}{ws}{match} {t.text!r}")
    return "\n".join(lines) + "\n"
