"""Idempotence on the corpus; identity up to whitespace where everything falls back."""

import gc
import weakref
from pathlib import Path

import pytest

from chplfmt import _native as native
from chplfmt import api
from chplfmt._chapel import chapel
from chplfmt.config import FormatOptions
from chplfmt.printer import REGISTRY, Printer
from chplfmt.tokens import TokenIndex
from corpus import corpus_params, parsed, preorder
from reference.doc import to_reference
from reference.render import render as reference_render

pytestmark = pytest.mark.corpus

RULES_OFF = FormatOptions(
    comment_spacing=False,
    trailing_comma=False,
    single_statement_body="preserve",
    remove_redundant_parens=False,
    remove_empty_statements=False,
)


def normalize(text: str, max_blank_lines: int = 1) -> list[str]:
    """The text up to whitespace the identity printer may change.

    CRLF becomes LF; in every line, runs of whitespace become one space and
    leading/trailing whitespace is removed; runs of blank lines are cut to
    `max_blank_lines`; blank lines at the start and end are dropped.
    """
    out: list[str] = []
    blank = 0
    for line in text.replace("\r\n", "\n").split("\n"):
        line = " ".join(line.split())
        if not line:
            blank += 1
            continue
        if out:
            out += [""] * min(blank, max_blank_lines)
        blank = 0
        out.append(line)
    return out


def _has_printed_kinds(asts: list[chapel.AstNode]) -> bool:
    """Whether a node has a registered printer (output may then differ from input)."""
    kinds = tuple(REGISTRY)
    return any(
        isinstance(n, kinds)
        and not (isinstance(n, chapel.Module) and n.kind() == "implicit")
        for n in preorder(asts)
    )


@pytest.mark.parametrize("path", corpus_params())
def test_corpus_formats_idempotently(path: Path) -> None:
    with parsed(path) as (source, result):
        text = source.text
        printed = _has_printed_kinds(list(result.asts))
    once = api.format_text(text, path=str(path)).text
    assert api.format_text(once, path=str(path)).text == once
    plain = api.format_text(text, path=str(path), options=RULES_OFF).text
    assert api.format_text(plain, path=str(path), options=RULES_OFF).text == plain
    if not printed:
        # Everything falls back: the output is the input up to whitespace.
        assert normalize(plain) == normalize(text)


@pytest.mark.parametrize("path", corpus_params())
def test_native_renderer_on_printer_docs(path: Path) -> None:
    options = FormatOptions()
    with parsed(path) as (source, parsed_result):
        index = TokenIndex.build(source, parsed_result.asts)
        reference_printer = Printer(index, options, path=str(path))
        reference = reference_render(
            to_reference(reference_printer.print_file()), options
        )

        was_enabled = gc.isenabled()
        gc.disable()
        try:
            printer = Printer(index, options, path=str(path))
            doc = printer.print_file()
            actual = native.render(doc, options.line_length, options.tab_size)
            assert actual.text == reference.text
            assert [
                (line.code, line.trailing_comment, line.verbatim)
                for line in actual.lines
            ] == [
                (line.code, line.trailing_comment, line.verbatim)
                for line in reference.lines
            ]
            printer_ref = weakref.ref(printer)
            del doc, printer
            assert printer_ref() is None
        finally:
            if was_enabled:
                gc.enable()
