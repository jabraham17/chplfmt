"""FormatOptions wrappers for the native renderer."""

from collections.abc import Sequence

from chplfmt import _native
from chplfmt.config import FormatOptions
from chplfmt.doc.ir import DocLike

LineRecord = _native.LineRecord
RenderResult = _native.RenderResult
RenderStats = _native.RenderStats


def render(doc: DocLike, options: FormatOptions, base_indent: int = 0) -> RenderResult:
    return _native.render(doc, options.line_length, options.tab_size, base_indent)


def render_text(doc: DocLike, options: FormatOptions, base_indent: int = 0) -> str:
    return _native.render_text(doc, options.line_length, options.tab_size, base_indent)


def flat_width(doc: DocLike, options: FormatOptions) -> int | None:
    return _native.flat_width(doc, options.tab_size)


def align_trailing_comments(
    lines: Sequence[LineRecord], line_length: int, tab_size: int
) -> list[str]:
    return _native.align_trailing_comments(lines, line_length, tab_size)
