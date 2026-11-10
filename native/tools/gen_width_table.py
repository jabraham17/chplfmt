"""Generate the native width table with the minimum supported Python."""

import sys
import tomllib
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MIN_PYTHON = (3, 12)
requires_python = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
    "requires-python"
]
if requires_python != f">={MIN_PYTHON[0]}.{MIN_PYTHON[1]}":
    raise SystemExit(f"unexpected minimum Python: {requires_python}")
if sys.version_info[:2] != MIN_PYTHON:
    raise SystemExit(f"run with Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}")

ranges = []
lo = None
for code in range(0x1100, 0x110000):
    wide = unicodedata.east_asian_width(chr(code)) in ("W", "F")
    if wide and lo is None:
        lo = code
    elif not wide and lo is not None:
        ranges.append((lo, code - 1))
        lo = None
if lo is not None:
    ranges.append((lo, 0x10FFFF))

lines = [
    f'pub const PYTHON_VERSION: &str = "{MIN_PYTHON[0]}.{MIN_PYTHON[1]}";',
    f'pub const UNICODE_VERSION: &str = "{unicodedata.unidata_version}";',
    "pub const WIDE_RANGES: &[(u32, u32)] = &[",
    *(f"    (0x{start:04X}, 0x{end:04X})," for start, end in ranges),
    "];",
    "",
]
target = ROOT / "native/core/src/width/width_table.rs"
generated = "\n".join(lines)
if sys.argv[1:] == ["--check"]:
    if target.read_text() != generated:
        raise SystemExit(f"outdated width table: {target}")
elif not sys.argv[1:]:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(generated)
else:
    raise SystemExit("usage: gen_width_table.py [--check]")
