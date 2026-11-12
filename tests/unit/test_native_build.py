from pathlib import Path

import pytest
from _pytest.outcomes import Exit

from chplfmt import _native
from conftest import _check_native_build, _native_build_hash


def test_native_build_matches_checkout() -> None:
    root = Path(__file__).resolve().parents[2] / "native"
    assert _native.__build__ == _native_build_hash(root)


def test_native_build_hash_tracks_sources_and_lock(tmp_path: Path) -> None:
    root = tmp_path / "native"
    (root / "core" / "src").mkdir(parents=True)
    (root / "target").mkdir()
    source = root / "core" / "src" / "lib.rs"
    source.write_text("first")
    initial = _native_build_hash(root)
    (root / "target" / "output.rs").write_text("ignored")
    assert _native_build_hash(root) == initial
    (root / "fuzz").mkdir()
    (root / "fuzz" / "Cargo.lock").write_text("ignored fuzz lock")
    assert _native_build_hash(root) == initial
    source.write_text("second")
    changed = _native_build_hash(root)
    assert changed != initial
    (root / "Cargo.lock").write_text("dependency update")
    assert _native_build_hash(root) != changed


def test_native_build_guard_reports_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "native"
    root.mkdir()
    (root / "Cargo.toml").write_text("[workspace]\n")
    _check_native_build(root, _native_build_hash(root))
    with pytest.raises(Exit, match=r"Stale chplfmt\._native extension"):
        _check_native_build(root, "outdated")
    with pytest.raises(Exit, match=r"Stale chplfmt\._native extension"):
        _check_native_build(root, None)


def test_native_build_guard_skips_wheel_without_sources(tmp_path: Path) -> None:
    _check_native_build(tmp_path / "missing-native-tree", None)
