from pathlib import Path

import pytest

from chplfmt import api
from chplfmt.config import FormatOptions
from corpus import corpus_params, parsed

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_identity_output_verifies(path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    # Interim output: the input with comment text normalized; must verify.
    api.format_text(text, path=str(path))
    api.format_text(
        text,
        path=str(path),
        options=FormatOptions(
            comment_spacing=False,
            trailing_comma=False,
            single_statement_body="preserve",
            remove_redundant_parens=False,
            remove_empty_statements=False,
        ),
    )
