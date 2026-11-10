"""Comment text transformations shared by the printer and the verifier.

Sections 7.5 (tabs in comments), 7.8 (`comment-spacing`), 8.11 (re-indent),
and 8.13 (no trailing whitespace, LF line endings).
"""

from __future__ import annotations

from chplfmt.rules.comment_spacing import apply as space_line_comment
from chplfmt.source import char_width

__all__ = ["expand_tabs", "expected_comment_text", "space_line_comment"]

_TRAILING_WS = " \t\f\r"


def expand_tabs(text: str, start_col: int, tab_size: int) -> str:
    """Replace tabs with spaces; `start_col` is the display column of `text[0]`."""
    if "\t" not in text:
        return text
    out: list[str] = []
    col = start_col
    for ch in text:
        if ch == "\t":
            n = tab_size - col % tab_size
            out.append(" " * n)
            col += n
            continue
        out.append(ch)
        col = 0 if ch == "\n" else col + char_width(ch)
    return "".join(out)


def _shift(line: str, shift: int) -> str:
    if shift >= 0:
        return " " * shift + line if line else line
    indent = len(line) - len(line.lstrip(" "))
    return line[min(-shift, indent) :]


def expected_comment_text(
    text: str,
    *,
    input_col: int,
    output_col: int,
    tab_size: int,
    comment_spacing: bool,
) -> str:
    """The output text of the comment token `text`.

    `input_col` and `output_col` are the 0-based display columns where the
    comment starts in the input and in the output. Continuation lines of a
    block comment move by `output_col - input_col` (never below column 0).
    Trailing whitespace is removed from every line.
    """
    is_block = text.startswith("/*")
    text = expand_tabs(text.replace("\r\n", "\n"), input_col, tab_size)
    if not is_block:
        if comment_spacing:
            text = space_line_comment(text)
        return text.rstrip(_TRAILING_WS)
    first, *rest = text.split("\n")
    shift = output_col - input_col
    lines = [first, *(_shift(line, shift) for line in rest)]
    return "\n".join(line.rstrip(_TRAILING_WS) for line in lines)
