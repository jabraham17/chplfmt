import io
import sys
from collections.abc import Callable

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Rewrite tests/golden/**/*.good from the current output.",
    )


@pytest.fixture
def set_stdin(monkeypatch: pytest.MonkeyPatch) -> Callable[[bytes], None]:
    def _set(data: bytes) -> None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))

    return _set
