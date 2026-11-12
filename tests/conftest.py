import hashlib
import io
import os
import sys
from collections.abc import Callable
from pathlib import Path

import pytest


def _native_build_hash(root: Path) -> str:
    digest = hashlib.sha256()
    sources = []
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in {"target", "fuzz"}]
        sources.extend(
            Path(directory) / name
            for name in names
            if Path(name).suffix in {".rs", ".toml", ".lock"}
        )
    for path in sorted(sources, key=lambda source: source.relative_to(root).as_posix()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _check_native_build(root: Path, built_hash: str | None) -> None:
    if root.is_dir() and built_hash != _native_build_hash(root):
        pytest.exit(
            "Stale chplfmt._native extension: the native sources differ from the installed "
            "build (or the build hash is missing). Rebuild with maturin develop --release "
            "or pip install -e .",
            returncode=1,
        )


def pytest_sessionstart(session: pytest.Session) -> None:
    root = Path(__file__).resolve().parents[1] / "native"
    if root.is_dir():
        from chplfmt import _native

        _check_native_build(root, getattr(_native, "__build__", None))


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
