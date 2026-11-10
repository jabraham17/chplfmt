"""LSP server for document and range formatting (section 7.14)."""

from __future__ import annotations

import logging
import os
import threading

from lsprotocol import types as lsp
from pygls.server import LanguageServer
from pygls.workspace import TextDocument

from chplfmt import __version__
from chplfmt.api import TextEdit, format_text, load_options
from chplfmt.config import ConfigError, FormatOptions
from chplfmt.errors import ChplParseError

log = logging.getLogger(__name__)

UTF8 = lsp.PositionEncodingKind.Utf8
UTF16 = lsp.PositionEncodingKind.Utf16
UTF32 = lsp.PositionEncodingKind.Utf32


# Position conversion. Offsets are code-point indices into the text; LSP lines
# end at "\n", "\r\n", or a lone "\r".


def lsp_line_starts(text: str) -> list[int]:
    starts = [0]
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "\n" or (c == "\r" and (i + 1 == n or text[i + 1] != "\n")):
            starts.append(i + 1)
        i += 1
    return starts


def _units(s: str, encoding: str) -> int:
    if encoding == UTF8:
        return len(s.encode("utf-8"))
    if encoding == UTF32:
        return len(s)
    return len(s.encode("utf-16-le")) // 2


def _content_end(text: str, starts: list[int], line: int) -> int:
    if line + 1 == len(starts):
        return len(text)
    end = starts[line + 1] - 1
    if text[end] == "\n" and end > starts[line] and text[end - 1] == "\r":
        end -= 1
    return end


def offset_to_position(
    text: str, offset: int, encoding: str = UTF16, starts: list[int] | None = None
) -> lsp.Position:
    starts = lsp_line_starts(text) if starts is None else starts
    lo, hi = 0, len(starts) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if starts[mid] <= offset:
            lo = mid
        else:
            hi = mid - 1
    return lsp.Position(lo, _units(text[starts[lo] : offset], encoding))


def position_to_offset(
    text: str, pos: lsp.Position, encoding: str = UTF16, starts: list[int] | None = None
) -> int:
    """Clamped like the spec says: past the line end means the line end."""
    starts = lsp_line_starts(text) if starts is None else starts
    if pos.line >= len(starts):
        return len(text)
    start = starts[pos.line]
    end = _content_end(text, starts, pos.line)
    units = 0
    for i in range(start, end):
        if units >= pos.character:
            return i
        units += _units(text[i], encoding)
    return end


def range_to_lines(text: str, rng: lsp.Range, encoding: str = UTF16) -> tuple[int, int]:
    """Inclusive 1-based `\\n`-delimited lines covered by `rng`."""
    starts = lsp_line_starts(text)
    a = position_to_offset(text, rng.start, encoding, starts)
    b = max(a, position_to_offset(text, rng.end, encoding, starts))
    first = text.count("\n", 0, a) + 1
    last = text.count("\n", 0, b) + 1
    if b > a and text[b - 1] == "\n":
        last -= 1  # an end at column 0 excludes that line
    return first, max(first, last)


def to_lsp_edits(
    text: str, edits: list[TextEdit], encoding: str = UTF16
) -> list[lsp.TextEdit]:
    """Convert line edits (lines as split by `str.splitlines`) to LSP edits."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    starts = lsp_line_starts(text)

    def pos(line: int) -> lsp.Position:
        off = offsets[min(line, len(offsets) - 1)]
        return offset_to_position(text, off, encoding, starts)

    return [
        lsp.TextEdit(lsp.Range(pos(e.start_line), pos(e.end_line)), e.new_text)
        for e in edits
    ]


class ChplfmtServer(LanguageServer):
    def __init__(self) -> None:
        super().__init__(  # pyright: ignore[reportUnknownMemberType]
            "chplfmt",
            __version__,
            text_document_sync_kind=lsp.TextDocumentSyncKind.Full,
        )
        self.format_lock = threading.Lock()
        self.reported: set[tuple[str, int | None]] = set()

    def log(self, message: str, kind: lsp.MessageType) -> None:
        self.show_message_log(message, kind)  # pyright: ignore[reportUnknownMemberType]

    def report_once(self, doc: TextDocument, message: str) -> None:
        self.log(message, lsp.MessageType.Error)
        key = (doc.uri, doc.version)
        if key not in self.reported:
            self.reported.add(key)
            self.show_message(  # pyright: ignore[reportUnknownMemberType]
                message, lsp.MessageType.Error
            )

    def run_format(
        self, uri: str, rng: lsp.Range | None = None
    ) -> list[lsp.TextEdit] | None:
        doc = self.workspace.get_text_document(uri)
        text = doc.source
        encoding = str(self.workspace.position_encoding or UTF16)
        try:
            options = _load_options()
        except ConfigError as e:
            self.report_once(doc, f"chplfmt: configuration error: {e}")
            return None
        path = doc.path or uri
        try:
            span = range_to_lines(text, rng, encoding) if rng is not None else None
            with self.format_lock:
                result = format_text(text, path=path, options=options, lines=span)
        except ChplParseError as e:
            self.log(f"chplfmt: not formatting {path}:\n{e}", lsp.MessageType.Warning)
            return None
        except Exception as e:
            log.exception("formatting %s failed", path)
            self.report_once(doc, f"chplfmt: internal error formatting {path}: {e}")
            return None
        return to_lsp_edits(text, result.edits, encoding)


def _load_options() -> FormatOptions:
    try:
        return load_options(os.getcwd(), [])
    except SystemExit as e:  # argparse rejected a config value
        raise ConfigError(f"invalid configuration (exit {e.code})") from e


def create_server() -> ChplfmtServer:
    server = ChplfmtServer()

    @server.feature(lsp.TEXT_DOCUMENT_FORMATTING)
    def _formatting(  # pyright: ignore[reportUnusedFunction]
        ls: ChplfmtServer, params: lsp.DocumentFormattingParams
    ) -> list[lsp.TextEdit] | None:
        return ls.run_format(params.text_document.uri)

    @server.feature(lsp.TEXT_DOCUMENT_RANGE_FORMATTING)
    def _range_formatting(  # pyright: ignore[reportUnusedFunction]
        ls: ChplfmtServer, params: lsp.DocumentRangeFormattingParams
    ) -> list[lsp.TextEdit] | None:
        return ls.run_format(params.text_document.uri, params.range)

    @server.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
    def _did_close(  # pyright: ignore[reportUnusedFunction]
        ls: ChplfmtServer, params: lsp.DidCloseTextDocumentParams
    ) -> None:
        uri = params.text_document.uri
        ls.reported = {key for key in ls.reported if key[0] != uri}

    return server


def main() -> int:
    create_server().start_io()
    return 0
