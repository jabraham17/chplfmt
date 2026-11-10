"""Corpus properties per option profile (design section 10).

Profiles: each non-default option value on its own, plus "all rules off".
Each profile must verify, be idempotent, and respect `line-length`. Files
come from `sample_params()` crossed with every profile, plus `PINNED`
(profile, file) pairs that once failed (the full cross product of the
corpus with CHPLFMT_FULL_CORPUS=1).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest
from test_corpus_line_length import classify

from chplfmt import api
from chplfmt.config import FormatOptions, option_key, option_meta
from corpus import chpl_home, parsed, sample_files

pytestmark = pytest.mark.corpus

# One representative non-default value per int option.
INT_VALUES = {
    "line_length": 40,
    "indent_width": 4,
    "continuation_indent": 4,
    "tab_size": 8,
    "max_blank_lines": 0,
}

RULES_OFF = FormatOptions(
    comment_spacing=False,
    trailing_comma=False,
    single_statement_body="preserve",
    remove_redundant_parens=False,
    remove_empty_statements=False,
)


def _non_default(f: dataclasses.Field[Any]) -> list[Any]:
    if isinstance(f.default, bool):
        return [not f.default]
    if isinstance(f.default, int):
        return [INT_VALUES.get(f.name, f.default + 1)]
    return [c for c in option_meta(f).choices if c != f.default]


def profiles() -> dict[str, FormatOptions]:
    out = {
        f"{option_key(f)}={str(v).lower()}": dataclasses.replace(
            FormatOptions(), **{f.name: v}
        )
        for f in dataclasses.fields(FormatOptions)
        for v in _non_default(f)
    }
    out["rules-off"] = RULES_OFF
    return out


PINNED = [
    ("line-length=40", "modules/internal/ChapelRange.chpl"),
    ("line-length=40", "modules/internal/DefaultSparse.chpl"),
    ("line-length=40", "modules/packages/Python.chpl"),
    ("line-length=40", "modules/packages/Zarr.chpl"),
    ("indent-width=4", "modules/internal/DefaultSparse.chpl"),
]


def cases() -> list[object]:
    home = chpl_home()
    files = sample_files()
    if home is None or not files:
        return [
            pytest.param(None, None, marks=pytest.mark.skip(reason="no Chapel corpus"))
        ]
    profs = profiles()
    pairs = {(name, p) for name in profs for p in files}
    pairs |= {(name, home / rel) for name, rel in PINNED if (home / rel).is_file()}
    return [
        pytest.param(profs[name], p, id=f"{name}-{p.relative_to(home)}")
        for name, p in sorted(pairs, key=lambda np: (np[0], str(np[1])))
    ]


@pytest.mark.parametrize(("options", "path"), cases())
def test_profile(options: FormatOptions, path: Path) -> None:
    with parsed(path) as (source, _):
        text = source.text
    # format_text runs the verifier.
    once = api.format_text(text, path=str(path), options=options).text
    assert (
        api.format_text(once, path=str(path), options=options).text == once
    ), "not idempotent"
    lines = once.split("\n")
    bad = [
        f"{n}: {lines[n - 1]}"
        for n, reason in classify(once, str(path), options)
        if not reason
    ]
    assert not bad, "\n".join(bad[:10])
