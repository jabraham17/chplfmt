"""Version guard: pins the chapel-py facts of design section 6 that chplfmt relies on."""

import os
import re
from pathlib import Path
from typing import Any

import pytest

from chplfmt._chapel import CHAPEL_VERSION, chapel, parse_text


def nodes(asts: list[Any], kind: type) -> list[Any]:
    return [n for root in asts for n in chapel.preorder(root) if isinstance(n, kind)]


def test_compiler_version_format() -> None:
    version = chapel.Context().get_compiler_version()
    assert version == CHAPEL_VERSION
    assert re.match(r"^\d+\.\d+\.\d+( |$)", version), version


def test_context_requires_chpl_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHPL_HOME")
    with pytest.raises(RuntimeError, match="CHPL_HOME must be set"):
        chapel.Context()


def test_parse_takes_a_path_only() -> None:
    ctx = chapel.Context()
    # Extra arguments are silently ignored; the text is never parsed.
    with ctx.track_errors() as errs:
        ctx.parse("no-such-file.chpl", "var x = 1;")  # type: ignore[call-arg]
    [err] = errs
    assert "error reading file" in err.message()
    with ctx.track_errors() as errs:
        ctx.parse("var x = 1;")
    [err] = errs
    assert err.kind() == "error"
    assert "error reading file" in err.message()
    assert err.location().start() == (-1, -1)


def test_track_errors_yields_error_objects(tmp_path: Path) -> None:
    path = tmp_path / "bad.chpl"
    path.write_text("var x = ;\n")
    ctx = chapel.Context()
    with ctx.track_errors() as errs:
        ctx.parse(str(path))
    assert isinstance(errs, list)
    [err] = errs
    assert isinstance(err, chapel.Error)
    assert type(err).__name__ == "BisonSyntaxError"
    assert err.type() == "BisonSyntaxError"
    assert err.kind() == "syntax"
    assert err.message() == "near ';'"
    loc = err.location()
    assert isinstance(loc, chapel.Location)
    assert loc.path() == str(path)
    assert (loc.start(), loc.end()) == ((1, 9), (1, 10))
    assert err.notes() == []


def test_warning_kind(tmp_path: Path) -> None:
    path = tmp_path / "w.chpl"
    path.write_text("module A { }\nmodule B { }\nvar y = 1;\n")
    ctx = chapel.Context()
    with ctx.track_errors() as errs:
        ctx.parse(str(path))
    assert [(e.type(), e.kind()) for e in errs] == [("ImplicitFileModule", "warning")]


def test_location_is_one_based_with_exclusive_end() -> None:
    with parse_text("var x = 1;\n", "loc.chpl") as res:
        [var] = nodes(res.asts, chapel.Variable)
        assert var.location().start() == (1, 1)
        assert var.location().end() == (1, 10)  # the ';' is not included


def test_columns_are_utf8_bytes_and_tab_is_one() -> None:
    text = 'var s = "\u00e9\u4e2d"; var y = 1;\n\tvar z = 2;\n'
    with parse_text(text, "cols.chpl") as res:
        s, y, z = nodes(res.asts, chapel.Variable)
        assert s.location().end() == (1, 16)  # code points would give 13
        assert y.location().start() == (1, 18)
        assert z.location().start() == (2, 2)


def test_implicit_module_named_after_basename() -> None:
    with parse_text("var x = 1;\n", os.path.join("a", "b", "my-file.chpl")) as res:
        [mod] = res.asts
        assert isinstance(mod, chapel.Module)
        assert mod.name() == "my-file"
        assert mod.kind() == "implicit"


def test_comment_nodes_have_no_location() -> None:
    with parse_text("// hello\nvar x = 1;\n", "c.chpl") as res:
        comments = nodes(res.asts, chapel.Comment)
        assert comments
        for c in comments:
            assert c.location().start() == (-1, -1)


def test_non_ascii_identifier_message_is_not_utf8(tmp_path: Path) -> None:
    # dyno quotes a single byte of a multi-byte character; parse_text copes.
    path = tmp_path / "u.chpl"
    path.write_text("var \u00e9 = 1;\n", encoding="utf-8")
    ctx = chapel.Context()
    with ctx.track_errors() as errs:
        ctx.parse(str(path))
    assert errs
    with pytest.raises(UnicodeDecodeError):
        errs[0].message()


def span(node: Any) -> tuple[tuple[int, int], tuple[int, int]]:
    loc = node.location()
    return loc.start(), loc.end()


def loc_pair(loc: Any) -> tuple[tuple[int, int], tuple[int, int]] | None:
    return None if loc is None else (loc.start(), loc.end())


def test_paren_location_is_innermost_pair_only() -> None:
    with parse_text("var x = ((a));\n", "p.chpl") as res:
        [ident] = nodes(res.asts, chapel.Identifier)
        assert loc_pair(ident.paren_location()) == ((1, 10), (1, 13))
        assert span(ident) == ((1, 11), (1, 12))


def test_statement_span_quirks() -> None:
    text = "proc f() { return 1; }\nvar x = 1;\nf();\n"
    with parse_text(text, "s.chpl") as res:
        [fn] = nodes(res.asts, chapel.Function)
        [ret] = nodes(res.asts, chapel.Return)
        [var] = nodes(res.asts, chapel.Variable)
        [call] = nodes(res.asts, chapel.FnCall)
        assert span(ret) == ((1, 12), (1, 21))  # includes ';'
        assert span(var) == ((2, 1), (2, 10))  # doesn't
        assert span(call) == ((3, 1), (3, 4))  # doesn't
        body = fn.body()
        assert body is not None
        assert span(body) == span(fn) == ((1, 1), (1, 23))
        assert body.curly_braces_location() is None
        assert loc_pair(fn.curly_braces_location()) == ((1, 10), (1, 23))


def test_identifier_location_covers_type_constructor_call() -> None:
    text = "class C {}\nvar a: owned C?;\nvar d: domain(2);\n"
    with parse_text(text, "w.chpl") as res:
        owned, domain = (
            n for n in nodes(res.asts, chapel.Identifier) if n.name() != "C"
        )
        assert span(owned) == ((2, 8), (2, 16))
        assert span(domain) == ((3, 8), (3, 17))


def test_sub_locations_exist() -> None:
    text = (
        "proc f() throws { }\n"
        "for i in 1..3 { }\n"
        "if c then f(); else { f(); }\n"
        "var y = r.fld;\n"
    )
    with parse_text(text, "l.chpl") as res:
        [fn] = nodes(res.asts, chapel.Function)
        [loop] = nodes(res.asts, chapel.For)
        [cond] = nodes(res.asts, chapel.Conditional)
        [dot] = nodes(res.asts, chapel.Dot)
        assert loc_pair(fn.name_location()) == ((1, 6), (1, 7))
        assert loc_pair(fn.header_location()) == ((1, 1), (1, 16))
        assert loc_pair(fn.throws_location()) == ((1, 10), (1, 16))
        assert loc_pair(loop.header_location()) == ((2, 1), (2, 14))
        assert loc_pair(loop.curly_braces_location()) == ((2, 15), (2, 18))
        assert loc_pair(cond.then_keyword_location()) == ((3, 6), (3, 10))
        assert loc_pair(cond.else_keyword_location()) == ((3, 16), (3, 20))
        assert loc_pair(dot.field_location()) == ((4, 11), (4, 14))


def test_block_style_values() -> None:
    text = (
        "for i in 1..3 do f(); for i in 1..3 { f(); }\n"
        "if c then f(); else { f(); }\nif c { }\n"
        "begin f(); begin { f(); }\n"
        "select x { when 1 do f(); when 2 { } }\n"
    )
    with parse_text(text, "b.chpl") as res:
        loops = nodes(res.asts, chapel.For)
        assert [n.block_style() for n in loops] == ["implicit", "explicit"]
        conds = nodes(res.asts, chapel.Conditional)
        assert [(n.then_block_style(), n.else_block_style()) for n in conds] == [
            ("implicit", "explicit"),
            ("explicit", "implicit"),  # no `else` reports "implicit"
        ]
        begins = nodes(res.asts, chapel.Begin)
        assert [n.block_style() for n in begins] == ["implicit", "explicit"]
        whens = nodes(res.asts, chapel.When)
        assert [n.block_style() for n in whens] == ["implicit", "explicit"]
        # Body Blocks always say "explicit", even after `do`.
        assert {b.block_style() for b in nodes(res.asts, chapel.Block)} == {"explicit"}
