"""LSP server: conversion helpers and integration tests over stdio."""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap
from collections.abc import Coroutine, Iterator
from pathlib import Path
from typing import Any, TypeVar

import pytest
from lsprotocol import types as lsp
from pygls.lsp.client import BaseLanguageClient

from chplfmt.api import TextEdit, format_text
from chplfmt.config import FormatOptions
from chplfmt.lsp import (
    UTF8,
    UTF16,
    lsp_line_starts,
    offset_to_position,
    position_to_offset,
    range_to_lines,
    to_lsp_edits,
)

T = TypeVar("T")
TIMEOUT = 60.0

MESSY = "proc f() {\n      var x   =   1;\n  var y=2;\n}\n"


def P(line: int, char: int) -> lsp.Position:
    return lsp.Position(line, char)


def R(a: tuple[int, int], b: tuple[int, int]) -> lsp.Range:
    return lsp.Range(P(*a), P(*b))


def apply(text: str, edits: list[lsp.TextEdit] | None, enc: str = UTF16) -> str:
    starts = lsp_line_starts(text)
    spans = [
        (
            position_to_offset(text, e.range.start, enc, starts),
            position_to_offset(text, e.range.end, enc, starts),
            e.new_text,
        )
        for e in edits or []
    ]
    for a, b, new in sorted(spans, reverse=True):
        text = text[:a] + new + text[b:]
    return text


# --- conversion helpers -----------------------------------------------------


def test_line_starts() -> None:
    assert lsp_line_starts("") == [0]
    assert lsp_line_starts("a\nb") == [0, 2]
    assert lsp_line_starts("a\r\nb\rc\n") == [0, 3, 5, 7]


def test_positions_utf16_and_utf8() -> None:
    text = "x = '\U0001f600é';\nz"
    end = text.index(";")
    assert offset_to_position(text, end) == P(0, 9)
    assert offset_to_position(text, end, UTF8) == P(0, 12)
    assert position_to_offset(text, P(0, 9)) == end
    assert position_to_offset(text, P(0, 12), UTF8) == end
    assert offset_to_position(text, len(text)) == P(1, 1)


def test_positions_clamp() -> None:
    text = "ab\r\ncd"
    assert position_to_offset(text, P(0, 99)) == 2  # before "\r\n"
    assert position_to_offset(text, P(5, 0)) == len(text)
    assert offset_to_position(text, 4) == P(1, 0)


@pytest.mark.parametrize(
    ("rng", "lines"),
    [
        (R((1, 0), (1, 0)), (2, 2)),  # empty range
        (R((1, 3), (2, 1)), (2, 3)),  # partial lines expand
        (R((0, 0), (2, 0)), (1, 2)),  # end at column 0 excludes that line
        (R((0, 2), (9, 9)), (1, 3)),  # clamped to the end of the document
        (R((2, 1), (1, 0)), (3, 3)),  # inverted
    ],
)
def test_range_to_lines(rng: lsp.Range, lines: tuple[int, int]) -> None:
    assert range_to_lines("a\nbbbb\nc\n", rng) == lines


def test_range_to_lines_crlf() -> None:
    assert range_to_lines("a\r\nb\r\nc", R((0, 0), (2, 0))) == (1, 2)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("a\nb", "a\nB\n"),  # no final newline
        ("a\n", "a\nb\n"),  # append at EOF
        ("a\nb\nc\n", "a\nc\n"),
        ("a\r\nb\r\n", "A\r\nb\r\n"),
        ("", "x\n"),
        ("x \u2028y\n", "x\u2028y\n"),  # splitlines/LSP line mismatch
    ],
)
def test_to_lsp_edits(old: str, new: str) -> None:
    from chplfmt.api import compute_edits

    edits = to_lsp_edits(old, compute_edits(old, new))
    assert apply(old, edits) == new


def test_to_lsp_edits_positions() -> None:
    [e] = to_lsp_edits("a\nb", [TextEdit(1, 2, "B\n")])
    assert e.range == R((1, 0), (1, 1))
    assert e.new_text == "B\n"


# --- integration ------------------------------------------------------------


class Client(BaseLanguageClient):
    def __init__(self) -> None:
        super().__init__("chplfmt-test", "0")
        self.logs: list[lsp.LogMessageParams] = []
        self.shown: list[lsp.ShowMessageParams] = []

        @self.feature(lsp.WINDOW_LOG_MESSAGE)
        def _log(
            params: lsp.LogMessageParams,
        ) -> None:  # pyright: ignore[reportUnusedFunction]
            self.logs.append(params)

        @self.feature(lsp.WINDOW_SHOW_MESSAGE)
        def _show(
            params: lsp.ShowMessageParams,
        ) -> None:  # pyright: ignore[reportUnusedFunction]
            self.shown.append(params)


class Session:
    """A `chplfmt --lsp` subprocess driven from a private event loop."""

    def __init__(self, cwd: Path, preamble: str = "") -> None:
        self.cwd = cwd
        self.loop = asyncio.new_event_loop()
        self.client = Client()
        self.versions: dict[str, int] = {}
        if preamble:
            code = preamble + "\nimport sys, chplfmt.lsp\nsys.exit(chplfmt.lsp.main())"
            args = ["-c", code]
        else:
            args = ["-m", "chplfmt", "--lsp"]
        self._plain(self.client.start_io(sys.executable, *args, cwd=str(cwd)))
        params = lsp.InitializeParams(
            capabilities=lsp.ClientCapabilities(),
            process_id=os.getpid(),
            root_uri=cwd.as_uri(),
        )
        self.init = self.run(self.client.initialize_async(params))
        self.client.initialized(lsp.InitializedParams())

    def _plain(self, coro: Coroutine[Any, Any, T]) -> T:
        return self.loop.run_until_complete(asyncio.wait_for(coro, TIMEOUT))

    def run(self, coro: Coroutine[Any, Any, T]) -> T:
        return self.loop.run_until_complete(self._guard(coro))

    async def _guard(self, coro: Coroutine[Any, Any, T]) -> T:
        """Await `coro`, failing fast if the server exits or hangs."""
        task = asyncio.ensure_future(coro)
        proc = self.client._server
        assert proc is not None
        dead = asyncio.ensure_future(proc.wait())
        done, _ = await asyncio.wait(
            {task, dead}, timeout=TIMEOUT, return_when=asyncio.FIRST_COMPLETED
        )
        dead.cancel()
        if task in done:
            return task.result()
        task.cancel()
        raise AssertionError(
            f"server exited with {proc.returncode}" if dead in done else "timeout"
        )

    def close(self) -> None:
        try:
            self.run(self.client.shutdown_async(None))
            self.client.exit(None)
        finally:
            self._plain(self.client.stop())
            self.loop.close()

    def uri(self, name: str) -> str:
        return (self.cwd / name).as_uri()

    def open(self, name: str, text: str) -> lsp.TextDocumentIdentifier:
        uri = self.uri(name)
        self.versions[uri] = 1
        item = lsp.TextDocumentItem(uri, "chapel", 1, text)
        self.client.text_document_did_open(lsp.DidOpenTextDocumentParams(item))
        return lsp.TextDocumentIdentifier(uri)

    def close_doc(self, doc: lsp.TextDocumentIdentifier) -> None:
        self.client.text_document_did_close(lsp.DidCloseTextDocumentParams(doc))

    def change(self, doc: lsp.TextDocumentIdentifier, text: str) -> None:
        self.versions[doc.uri] += 1
        ident = lsp.VersionedTextDocumentIdentifier(self.versions[doc.uri], doc.uri)
        change = lsp.TextDocumentContentChangeEvent_Type2(text)
        self.client.text_document_did_change(
            lsp.DidChangeTextDocumentParams(ident, [change])
        )

    def format(
        self, doc: lsp.TextDocumentIdentifier, tab_size: int = 2
    ) -> list[lsp.TextEdit] | None:
        opts = lsp.FormattingOptions(tab_size, insert_spaces=True)
        params = lsp.DocumentFormattingParams(doc, opts)
        return self.run(self.client.text_document_formatting_async(params))

    def format_range(
        self, doc: lsp.TextDocumentIdentifier, rng: lsp.Range
    ) -> list[lsp.TextEdit] | None:
        opts = lsp.FormattingOptions(2, insert_spaces=True)
        params = lsp.DocumentRangeFormattingParams(doc, rng, opts)
        return self.run(self.client.text_document_range_formatting_async(params))

    def settle(self) -> None:
        self.run(asyncio.sleep(0.05))


@pytest.fixture(scope="module")
def session(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Session]:
    s = Session(tmp_path_factory.mktemp("lsp"))
    yield s
    s.close()


def test_capabilities(session: Session) -> None:
    caps = session.init.capabilities
    assert caps.document_formatting_provider
    assert caps.document_range_formatting_provider
    sync = caps.text_document_sync
    assert isinstance(sync, lsp.TextDocumentSyncOptions)
    assert sync.change == lsp.TextDocumentSyncKind.Full


def test_formatting(session: Session) -> None:
    doc = session.open("a.chpl", MESSY)
    edits = session.format(doc, tab_size=8)
    assert edits
    assert apply(MESSY, edits) == format_text(MESSY).text
    expected = format_text(MESSY).text
    session.change(doc, expected)
    assert session.format(doc) in (None, [])


def test_range_formatting(session: Session) -> None:
    doc = session.open("b.chpl", MESSY)
    edits = session.format_range(doc, R((1, 3), (2, 0)))
    out = apply(MESSY, edits)
    assert out == format_text(MESSY, lines=(2, 2)).text
    assert out.splitlines()[2] == "  var y=2;"
    assert out != MESSY


@pytest.mark.parametrize(
    "text",
    [
        "proc f() {\r\n      var x   =   1;\r\n}\r\n",
        "proc f() {\n      var x   =   1;\n}",
        "var s = '\U0001f600';   var t=1;",
    ],
    ids=["crlf", "no-final-newline", "astral"],
)
def test_line_endings(session: Session, text: str) -> None:
    doc = session.open(f"le{abs(hash(text))}.chpl", text)
    assert apply(text, session.format(doc)) == format_text(text).text


def test_parse_error(session: Session) -> None:
    before = len(session.client.logs)
    doc = session.open("bad.chpl", "proc f( {\n")
    assert session.format(doc) in (None, [])
    session.settle()
    new = session.client.logs[before:]
    assert any("not formatting" in m.message for m in new)
    assert not session.client.shown


def test_config_file_honored(tmp_path: Path) -> None:
    (tmp_path / "chplfmt.cfg").write_text("indent-width: 4\n")
    s = Session(tmp_path)
    try:
        doc = s.open("c.chpl", MESSY)
        out = apply(MESSY, s.format(doc, tab_size=8))
    finally:
        s.close()
    assert out == format_text(MESSY, options=FormatOptions(indent_width=4)).text
    assert "\n    var x = 1;\n" in out


@pytest.mark.parametrize("cfg", ["brace-style: bogus\n", "no-such-option: 1\n"])
def test_config_error(tmp_path: Path, cfg: str) -> None:
    (tmp_path / "chplfmt.cfg").write_text(cfg)
    s = Session(tmp_path)
    try:
        doc = s.open("e.chpl", MESSY)
        assert s.format(doc) in (None, [])
        assert s.format(doc) in (None, [])
        s.settle()
        assert len(s.client.shown) == 1
        assert "configuration" in s.client.shown[0].message
    finally:
        s.close()


def test_internal_error_shown_once_per_version(tmp_path: Path) -> None:
    preamble = textwrap.dedent("""
        import chplfmt.lsp
        from chplfmt.errors import VerificationError
        def boom(*args, **kwargs):
            raise VerificationError("x.chpl", "tokens", (1, 1), (1, 1))
        chplfmt.lsp.format_text = boom
        """)
    s = Session(tmp_path, preamble)
    try:
        doc = s.open("d.chpl", MESSY)
        assert s.format(doc) in (None, [])
        assert s.format_range(doc, R((0, 0), (1, 0))) in (None, [])
        s.settle()
        assert len(s.client.shown) == 1
        assert s.client.shown[0].type == lsp.MessageType.Error
        assert "verification" in s.client.shown[0].message
        s.change(doc, MESSY + "\n")
        assert s.format(doc) in (None, [])
        s.settle()
        assert len(s.client.shown) == 2
        # Reopening restarts at version 1, which must be reported again.
        s.close_doc(doc)
        doc = s.open("d.chpl", MESSY)
        assert s.format(doc) in (None, [])
        s.settle()
        assert len(s.client.shown) == 3
    finally:
        s.close()
