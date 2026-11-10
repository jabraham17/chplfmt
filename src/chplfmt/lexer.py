"""Chapel tokenizer (design section 7.3), following dyno's flex rules (`chpl.lex`)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from chplfmt import _native
from chplfmt._native import Token as Token
from chplfmt._native import TokenKind as TokenKind
from chplfmt.source import SourceText

COMMENT_KINDS = frozenset({TokenKind.LINE_COMMENT, TokenKind.BLOCK_COMMENT})


class LexError(Exception):
    """The text can't be tokenized, or the lexer disagrees with the parser."""

    def __init__(self, source: SourceText, offset: int, message: str) -> None:
        self.offset = offset
        self.pos = source.pos(min(offset, len(source.text)))
        super().__init__(f"{self.pos[0]}:{self.pos[1]}: {message}")


WHITESPACE = " \t\r\n\f"
OPEN_BRACKETS = {"(": ")", "[": "]", "{": "}"}
CLOSE_BRACKETS = {v: k for k, v in OPEN_BRACKETS.items()}

PUNCTUATION = frozenset(
    {
        *("**=", "&&=", "||=", "<<=", ">>=", "<=>", "..<", "..."),
        *("+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "=>", ".."),
        *("&&", "||", "<<", ">>", "==", "!=", "<=", ">=", "--", "++", "**"),
        *"=#!&|^~<>+-*/%:;,.()[]{}?@",
    }
)


def tokenize(source: SourceText, opaque: Iterable[tuple[int, int]] = ()) -> list[Token]:
    """Tokenize `source`, ending with an EOF token.

    `opaque` lists `(start_offset, end_offset)` ranges (from `ExternBlock`
    nodes) that become single OPAQUE tokens without being looked into.
    """
    try:
        return _native.lex(source.text, sorted(opaque))
    except _native.NativeLexError as error:
        message = error.reason
        if error.char is not None:
            message += f" {error.char!r}"
        raise LexError(source, error.offset, message) from None


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
