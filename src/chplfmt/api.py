"""Stable library interface (section 7.11). Not thread-safe."""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass

from chplfmt._chapel import Diagnostic, parse_text
from chplfmt.comments import expected_comment_text
from chplfmt.config import FormatOptions, load_options
from chplfmt.errors import ChplParseError, FormatError, VerificationError
from chplfmt.offregions import verbatim_spans
from chplfmt.source import SourceText, display_width
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


@dataclass(frozen=True)
class DebugOptions:
    """Development-only switches (hidden CLI flags)."""

    dump_failed_dir: str | None = None  # save output that fails verification
    skip_verify: bool = False


def compute_edits(old: str, new: str) -> list[TextEdit]:
    """Minimal line-level edits that turn `old` into `new`."""
    a = old.splitlines(keepends=True)
    b = new.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    return [
        TextEdit(i1, i2, "".join(b[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


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
    with parse_text(text, logical) as parsed:
        if parsed.errors:
            raise ChplParseError(parsed.errors)
        index = TokenIndex.build(SourceText.from_text(text), parsed.asts)
        result = _identity_print(index, options)
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
    return FormatResult(result, result != text, edits)


def _identity_print(index: TokenIndex, options: FormatOptions) -> str:
    """Until the printer exists: the input with only comment text normalized."""
    source = index.source
    text = source.text
    spans = verbatim_spans(index)
    out: list[str] = []
    pos = 0
    line = ""  # output text since the last newline
    for tok in index.tokens:
        if not tok.is_comment or any(s <= tok.start_offset < e for s, e in spans):
            continue
        before = text[pos : tok.start_offset]
        line = line + before if "\n" not in before else before.rsplit("\n", 1)[1]
        comment = expected_comment_text(
            tok.text,
            input_col=source.display_column(tok.start_offset, options.tab_size),
            output_col=display_width(line, 0, options.tab_size),
            tab_size=options.tab_size,
            comment_spacing=options.comment_spacing,
        )
        out += [before, comment]
        line = line + comment if "\n" not in comment else comment.rsplit("\n", 1)[1]
        pos = tok.end_offset
    out.append(text[pos:])
    return "".join(out)


def _dump_failed(directory: str, path: str, text: str) -> None:
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(path) + ".failed")
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(text)
