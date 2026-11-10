from pathlib import Path

import pytest

from chplfmt import api
from corpus import corpus_params, parsed

pytestmark = pytest.mark.corpus


@pytest.mark.parametrize("path", corpus_params())
def test_no_printer_fallbacks(path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    res = api.format_text(
        text, path=str(path), debug=api.DebugOptions(skip_verify=True)
    )
    assert not res.report.fallbacks
