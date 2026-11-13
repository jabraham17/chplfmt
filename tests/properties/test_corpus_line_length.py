"""No output line exceeds `line-length` except unbreakable content.

A line longer than the limit is allowed only for one of these reasons
(checked in order, on the default-options output):

- `verbatim`: it overlaps an off region or extern block.
- `comment`: its code (all tokens but comments) ends within the limit, so
  only a trailing or own-line comment overflows.
- `multiline-token`: it continues a token that starts on an earlier line
  (a block comment or multi-line string).
- `no-break-point`: no break point precedes the first token that ends past
  the limit (a multi-line token counts up to the line end). Unspaced
  operators (`a=1`, `lo..#n`, `-x`) and the `else` of `} else` are not
  break points.
- `long-token`: that token alone does not fit on a continuation line
  (line indentation + `indent-width` + its width exceeds the limit).

`ALLOWED` lists further known classes of violations, by reason.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from pathlib import Path

import pytest

from chplfmt import api
from chplfmt._chapel import parse_text
from chplfmt.config import FormatOptions
from chplfmt.lexer import Token, TokenKind
from chplfmt.offregions import verbatim_spans
from chplfmt.source import SourceText, display_width
from chplfmt.tokens import TokenIndex
from corpus import corpus_params, parsed

pytestmark = pytest.mark.corpus

# Tokens the printer may break after (or before); `in` is not one (loop
# headers wrap inside the iterand).
BREAKS = frozenset(
    [
        ",",
        "(",
        "[",
        "{",
        "=",
        "+=",
        "-=",
        "*=",
        "/=",
        "%=",
        "**=",
        "&=",
        "|=",
        "^=",
        "<<=",
        ">>=",
        "<=>",
        "&&",
        "||",
        "+",
        "-",
        "*",
        "/",
        "%",
        "**",
        "==",
        "!=",
        "<",
        ">",
        "<=",
        ">=",
        "&",
        "|",
        "^",
        "<<",
        ">>",
        "..",
        "..<",
        "#",
        "by",
        "align",
        "then",
        "else",
        "do",
        "with",
        "where",
        "reduce",
        "scan",
    ]
)
OPENERS = frozenset(["(", "[", "{"])
KEYWORDS = frozenset(
    [
        "return",
        "yield",
        "in",
        "then",
        "else",
        "do",
        "if",
        "while",
        "for",
        "forall",
        "foreach",
        "coforall",
        "when",
        "by",
        "align",
        "on",
        "with",
        "throw",
        "const",
        "var",
        "ref",
        "param",
        "type",
    ]
)

ALLOWED: dict[str, str] = {}


def classify(text: str, path: str, options: FormatOptions) -> list[tuple[int, str]]:
    """`(line, reason)` for each line of `text` over the limit; reason "" if none applies."""
    limit = options.line_length
    source = SourceText.from_text(text)
    lines = text.split("\n")
    over = [
        n
        for n, s in enumerate(lines, 1)
        if limit and display_width(s, tab_size=options.tab_size) > limit
    ]
    if not over:
        return []
    with parse_text(text, path) as result:
        assert not result.errors
        index = TokenIndex.build(source, result.asts)
    spans = verbatim_spans(index)

    def col(offset: int) -> int:
        ls = source.line_start(source.line_of(offset))
        return display_width(text[ls:offset], tab_size=options.tab_size)

    toks = [t for t in index.tokens if t.kind is not TokenKind.EOF]
    starts = [t.start_offset for t in toks]

    def is_break(i: int) -> bool:
        t = toks[i]
        if t.text not in BREAKS:
            return False
        if t.text not in OPENERS:
            if t.text == "else" and (j := index.prev_code(i)) is not None:
                # `} else if ...` keeps `else` on the `}` line.
                return toks[j].text != "}"
            # Unspaced operators (`a=1`, `lo..#n`, unary `-x`) don't break.
            return t.text == "," or text[t.end_offset : t.end_offset + 1] in " \n"
        # An open bracket breaks a call/index list or a list with commas;
        # `()` and a parenthesized expression `(a.b: T)` have no break point.
        close = t.match
        if close is None or close == index.next_code(i):
            return False
        prev = index.prev_code(i)
        if prev is not None and (
            (toks[prev].kind is TokenKind.IDENT and toks[prev].text not in KEYWORDS)
            or toks[prev].text in (")", "]", "?")
        ):
            return True
        return any(toks[j].text == "," for j in range(i + 1, close))

    out: list[tuple[int, str]] = []
    for n in over:
        start, end = source.line_start(n), source.line_end(n)
        lo = max(bisect_right(starts, start) - 1, 0)
        hi = bisect_left(starts, end)
        mine = [i for i in range(lo, hi) if toks[i].end_offset > start]
        code = [i for i in mine if not toks[i].is_comment]
        indent = len(lines[n - 1]) - len(lines[n - 1].lstrip())
        overflow = next(
            (
                k
                for k, i in enumerate(code)
                if toks[i].start_offset >= start
                and col(min(toks[i].end_offset, end)) > limit
            ),
            None,
        )
        reason = ""
        if any(a < end and b > start for a, b in spans):
            reason = "verbatim"
        elif any(toks[i].start_offset < start for i in mine):
            reason = "multiline-token"
        elif (
            _without_comments(text, start, end, [toks[i] for i in mine], options)
            <= limit
        ):
            reason = "comment"
        elif overflow is not None and not any(map(is_break, code[1:overflow])):
            reason = "no-break-point"
        elif overflow is not None and (
            indent
            + options.indent_width
            + col(min(toks[code[overflow]].end_offset, end))
            - col(toks[code[overflow]].start_offset)
            > limit
        ):
            reason = "long-token"
        out.append((n, reason))
    return out


def _without_comments(
    text: str, start: int, end: int, toks: list[Token], options: FormatOptions
) -> int:
    parts: list[str] = []
    pos = start
    for t in toks:
        if t.is_comment:
            parts.append(text[pos : t.start_offset].rstrip(" "))
            pos = t.end_offset
    parts.append(text[pos:end])
    return display_width("".join(parts).rstrip(), tab_size=options.tab_size)


@pytest.mark.parametrize("path", corpus_params())
def test_line_length(path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    options = FormatOptions()
    res = api.format_text(
        text, path=str(path), options=options, debug=api.DebugOptions(skip_verify=True)
    )
    lines = res.text.split("\n")
    bad = [
        f"{n}: {lines[n - 1]}"
        for n, reason in classify(res.text, str(path), options)
        if not reason
    ]
    assert not bad, "\n".join(bad[:10])
