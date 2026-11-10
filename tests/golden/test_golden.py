"""Golden tests (design section 10): `tests/golden/<area>/<case>.chpl` -> `<case>.good`.

Options come from `<case>.cfg` if present, else `chplfmt.cfg` in the area
directory, passed as an explicit `-c`. `pytest --update-goldens` rewrites
the `.good` files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chplfmt import api
from chplfmt.config import FormatOptions, load_options

GOLDEN = Path(__file__).parent

# Kinds with a printer: a golden case must not fall back for them.
COVERED = frozenset(
    {
        "Module",
        "Class",
        "Record",
        "Union",
        "Interface",
        "Enum",
        "EnumElement",
        "Block",
        "AttributeGroup",
        "Attribute",
        "Variable",
        "MultiDecl",
        "TupleDecl",
        "ForwardingDecl",
        "Formal",
        "AnonFormal",
        "VarArgFormal",
        "Function",
        "FunctionSignature",
        "Identifier",
        "BoolLiteral",
        "IntLiteral",
        "UintLiteral",
        "RealLiteral",
        "ImagLiteral",
        "StringLiteral",
        "BytesLiteral",
        "CStringLiteral",
        "FnCall",
        "PrimCall",
        "Dot",
        "New",
        "Range",
        "Domain",
        "Array",
        "ArrayRow",
        "Tuple",
        "TypeQuery",
        "Reduce",
        "Scan",
        "Let",
        "OpCall",
        "Conditional",
        "Return",
        "Yield",
        "Throw",
        "Break",
        "Continue",
        "Delete",
        "Label",
        "Use",
        "Import",
        "VisibilityClause",
        "As",
        "Include",
        "Require",
        "Implements",
        "ExternBlock",
        "Init",
        "EmptyStmt",
    }
)


def fallback_kinds(result: api.FormatResult) -> set[str]:
    """Node kinds printed by the fallback (`"Tag@line:col"` -> `"Tag"`)."""
    return {f.split("@", 1)[0] for f in result.report.fallbacks}


def case_config(case: Path) -> Path | None:
    for cfg in (case.with_suffix(".cfg"), case.parent / "chplfmt.cfg"):
        if cfg.is_file():
            return cfg
    return None


def case_options(case: Path, cwd: Path) -> FormatOptions:
    cfg = case_config(case)
    return load_options(str(cwd), ["-c", str(cfg)] if cfg else [])


def cases() -> list[object]:
    return [
        pytest.param(p, id=str(p.relative_to(GOLDEN).with_suffix("")))
        for p in sorted(GOLDEN.rglob("*.chpl"))
    ]


@pytest.mark.parametrize("case", cases())
def test_golden(case: Path, tmp_path: Path, request: pytest.FixtureRequest) -> None:
    options = case_options(case, tmp_path)
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
    assert not fallback_kinds(result) & COVERED
