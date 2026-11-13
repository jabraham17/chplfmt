"""Option matrix: `tests/options/<option>/<value>/*.chpl` -> `.good`.

The matrix is generated from the `FormatOptions` registry. Each case is
formatted with that single option changed from the default. Every bool and
enum value needs a directory; int options need at least one value directory.
`pytest --update-goldens` rewrites the `.good` files.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from chplfmt import api
from chplfmt.config import FormatOptions, option_key, option_meta

OPTIONS = Path(__file__).parent

FIELDS = {option_key(f): f for f in dataclasses.fields(FormatOptions)}


def required_values(f: dataclasses.Field[Any]) -> list[str]:
    if isinstance(f.default, bool):
        return ["true", "false"]
    return list(option_meta(f).choices)


def parse_value(key: str, value: str) -> Any:
    """The option value named by a directory; raises ValueError if invalid."""
    f = FIELDS.get(key)
    if f is None:
        raise ValueError(f"unknown option {key!r}")
    if isinstance(f.default, bool):
        if value not in ("true", "false"):
            raise ValueError(f"{key}: expected true/false, got {value!r}")
        return value == "true"
    if isinstance(f.default, int):
        number = int(value, 10)
        minimum = option_meta(f).min
        if minimum is not None and number < minimum:
            raise ValueError(f"{key}: {value} < {minimum}")
        return number
    if value not in option_meta(f).choices:
        raise ValueError(f"{key}: unknown value {value!r}")
    return value


def options_for(key: str, value: str) -> FormatOptions:
    return dataclasses.replace(
        FormatOptions(), **{FIELDS[key].name: parse_value(key, value)}
    )


def value_dirs() -> list[Path]:
    return sorted(
        v
        for o in OPTIONS.iterdir()
        if o.is_dir() and not o.name.startswith(("_", "."))
        for v in o.iterdir()
        if v.is_dir()
    )


def cases() -> list[object]:
    return [
        pytest.param(p, id=str(p.relative_to(OPTIONS).with_suffix("")))
        for d in value_dirs()
        for p in sorted(d.glob("*.chpl"))
    ]


def test_matrix_complete() -> None:
    problems: list[str] = []
    for key, f in FIELDS.items():
        root = OPTIONS / key
        present = (
            {d.name for d in root.iterdir() if d.is_dir()} if root.is_dir() else set()
        )
        missing = [v for v in required_values(f) if v not in present]
        if not present:
            problems.append(f"{key}: no tests/options/{key}/<value>/ directory")
        elif missing:
            problems.append(f"{key}: missing values {missing}")
    for d in value_dirs():
        try:
            parse_value(d.parent.name, d.name)
        except ValueError as e:
            problems.append(f"{d.relative_to(OPTIONS)}: {e}")
        if not any(d.glob("*.chpl")):
            problems.append(f"{d.relative_to(OPTIONS)}: no .chpl cases")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("case", cases())
def test_option(case: Path, request: pytest.FixtureRequest) -> None:
    options = options_for(case.parent.parent.name, case.parent.name)
    path = str(case)
    result = api.format_text(
        case.read_text(encoding="utf-8"), path=path, options=options
    )
    good = case.with_suffix(".good")
    if request.config.getoption("--update-goldens"):
        good.write_text(result.text, encoding="utf-8")
    assert good.is_file(), f"missing {good.name}; run pytest --update-goldens"
    expected = good.read_text(encoding="utf-8")
    assert result.text == expected
    again = api.format_text(expected, path=path, options=options)
    assert again.text == expected, "not idempotent"
