import io
import sys
from collections.abc import Callable

import pytest


@pytest.fixture
def set_stdin(monkeypatch: pytest.MonkeyPatch) -> Callable[[bytes], None]:
    def _set(data: bytes) -> None:
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))

    return _set
