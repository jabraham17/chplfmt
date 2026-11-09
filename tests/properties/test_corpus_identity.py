"""Milestone 3 exit criterion: with every printer falling back, the corpus formats to itself."""

from pathlib import Path

import pytest

from chplfmt import api
from chplfmt.config import FormatOptions
from corpus import corpus_params, parsed

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


@pytest.mark.parametrize("path", corpus_params())
def test_corpus_formats_to_itself(path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    once = api.format_text(text, path=str(path)).text
    assert api.format_text(once, path=str(path)).text == once
    plain = api.format_text(text, path=str(path), options=RULES_OFF).text
    assert normalize(plain) == normalize(text)
