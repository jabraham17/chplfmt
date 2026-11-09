"""Stable library interface (section 7.11). Not thread-safe."""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from chplfmt._chapel import Diagnostic, parse_text
from chplfmt.config import FormatOptions, load_options

__all__ = [
    "ChplParseError",
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


class FormatError(Exception):
    pass


class ChplParseError(FormatError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(d) for d in diagnostics))


class VerificationError(FormatError):
    def __init__(
        self,
        path: str,
        check: str,
        input_pos: tuple[int, int],
        output_pos: tuple[int, int],
    ) -> None:
        self.path = path
        self.check = check
        self.input_pos = input_pos
        self.output_pos = output_pos
        super().__init__(
            f"{path}: internal error: formatter output failed verification "
            f"({check}) at input {input_pos[0]}:{input_pos[1]} / "
            f"output {output_pos[0]}:{output_pos[1]}"
        )


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
) -> FormatResult:
    """Format `text`; `lines` is an inclusive 1-based line range."""
    logical = path or STDIN_PATH
    if lines is not None and not 1 <= lines[0] <= lines[1]:
        raise ValueError(f"invalid line range {lines[0]}:{lines[1]}")
    with parse_text(text, logical) as parsed:
        if parsed.errors:
            raise ChplParseError(parsed.errors)
        # Milestone 0: the formatter is the identity.
        result = text
    edits = compute_edits(text, result)
    return FormatResult(result, result != text, edits)
