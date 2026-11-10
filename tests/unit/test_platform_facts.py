"""Version guard: pins the chapel-py facts of design section 6 that chplfmt relies on."""

import os
import re
from pathlib import Path
from typing import Any

import pytest

from chplfmt._chapel import (
    CHAPEL_VERSION,
    chapel,
    chapel_py_dir,
    parse_text,
    parse_version,
)


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


def test_chapel_py_lives_in_chpldeps() -> None:
    home = os.environ.get("CHPL_HOME")
    if not home:
        pytest.skip("CHPL_HOME not set")
    directory = chapel_py_dir(home, {}, [])
    assert directory is not None
    assert os.path.isfile(os.path.join(directory, "chapel", "__init__.py"))
    if "chpl-frontend-py-deps" not in directory:  # e.g. a source build
        assert "chpl-venv" in directory or "chpldeps" in directory, directory


def test_no_native_parse_text_yet() -> None:
    # When this fails, the shim starts using the real API (section 7.1).
    if parse_version(CHAPEL_VERSION) < (2, 11, 0):  # type: ignore[operator]
        assert not hasattr(chapel.Context(), "parse_text")


def test_comments_in_expressions_are_dropped() -> None:
    text = "var x = f(1, /* a */ 2);\nproc g(x: int /* b */, y) { h(/* c */); }\n"
    with parse_text(text, "c.chpl") as res:
        assert res.errors == []
        assert nodes(res.asts, chapel.Comment) == []


def test_style_info() -> None:
    text = (
        "var a = [1, 2,];\nvar b = [1, 2];\n"
        "var c = a[1]; var d = f(1);\n"
        "var s1 = 'x'; var s2 = \"x\"; var s3 = '''x'''; var s4 = \"\"\"x\"\"\";\n"
        "var i = 0x1F;\n"
    )
    with parse_text(text, "s.chpl") as res:
        assert res.errors == []
        arrays = nodes(res.asts, chapel.Array)
        assert [a.has_trailing_comma() for a in arrays] == [True, False]
        calls = nodes(res.asts, chapel.FnCall)
        assert [c.used_square_brackets() for c in calls] == [True, False]
        strings = nodes(res.asts, chapel.StringLiteral)
        assert [s.quote_style() for s in strings] == [
            "'",
            '"',
            "'''",
            '"""',
        ]
        assert "0x1F" in [n.text() for n in nodes(res.asts, chapel.IntLiteral)]
    # has_trailing_comma exists only on arrays.
    for kind in (chapel.Tuple, chapel.Domain, chapel.FnCall, chapel.Enum):
        assert not hasattr(kind, "has_trailing_comma")


def parse_errors(text: str) -> list[str]:
    with parse_text(text, "t.chpl") as res:
        return [d.message for d in res.errors]


TRAILING_COMMA_LEGAL = {
    "array": "var a = [1, 2,];",
    "associative": "var a = [1 => 2, 3 => 4,];",
    "domain": "var d = {1..2, 1..3,};",
    "tuple": "var t = (1, 2,);",
    "1-tuple": "var t = (1,);",
    "enum": "enum E { a, b, }",
    "tuple-decl": "var (x, y,) = (1, 2);",
}
TRAILING_COMMA_ILLEGAL = {
    "call": "f(1, 2,);",
    "index": "var x = a[1, 2,];",
    "new": "var c = new C(1,);",
    "formals": "proc g(x: int,) { }",
    "with": "forall i in 1..3 with (ref a,) { }",
    "zip": "for (i, j) in zip(1..2, 1..2,) { }",
    "use": "use IO, Math,;",
    "import": "import IO.{open, file,};",
    "attribute": '@deprecated(since="1", notes="x",) proc h() { }',
    "multi-decl": "var a = 1, b = 2,;",
    "inheritance": "interface I { } interface J { } record R: I, J, { }",
}


@pytest.mark.parametrize(
    "text", TRAILING_COMMA_LEGAL.values(), ids=TRAILING_COMMA_LEGAL
)
def test_trailing_comma_legal(text: str) -> None:
    assert parse_errors(text + "\n") == []


@pytest.mark.parametrize(
    "text", TRAILING_COMMA_ILLEGAL.values(), ids=TRAILING_COMMA_ILLEGAL
)
def test_trailing_comma_illegal(text: str) -> None:
    assert parse_errors(text + "\n") != []


def test_one_tuple_requires_comma() -> None:
    with parse_text("var t = (1,);\nvar u = (1);\n", "t.chpl") as res:
        assert len(nodes(res.asts, chapel.Tuple)) == 1


DO_BODIES = {
    "proc": ("proc f() do return 1;", chapel.Function),
    "iter": ("iter g() do yield 1;", chapel.Function),
    "for": ("for i in 1..3 do f(i);", chapel.For),
    "for-param": ("for param i in 1..3 do f(i);", chapel.For),
    "forall": ("forall i in 1..3 do f(i);", chapel.Forall),
    "foreach": ("foreach i in 1..3 do f(i);", chapel.Foreach),
    "coforall": ("coforall i in 1..3 do f(i);", chapel.Coforall),
    "while": ("while c do f();", chapel.While),
    "if": ("if c then f();", chapel.Conditional),
    "on": ("on here do f();", chapel.On),
    "local": ("local do f();", chapel.Local),
    "serial": ("serial do f();", chapel.Serial),
    "manage": ("manage m do f();", chapel.Manage),
    "when": ("select x { when 1 do f(); }", chapel.When),
    "otherwise": ("select x { otherwise do f(); }", chapel.When),
}


@pytest.mark.parametrize(("text", "kind"), DO_BODIES.values(), ids=DO_BODIES)
def test_do_then_bodies(text: str, kind: type) -> None:
    with parse_text(text + "\n", "d.chpl") as res:
        assert res.errors == []
        [node] = nodes(res.asts, kind)
        if kind is chapel.Conditional:
            assert node.then_block_style() == "implicit"
        elif kind is not chapel.Function:
            assert node.block_style() == "implicit"


@pytest.mark.parametrize("kw", ["begin", "sync", "defer"])
def test_bare_or_block_statement_bodies(kw: str) -> None:
    kind = {"begin": chapel.Begin, "sync": chapel.Sync, "defer": chapel.Defer}[kw]
    with parse_text(f"{kw} f();\n{kw} {{ f(); }}\n", "b.chpl") as res:
        assert res.errors == []
        styles = [n.block_style() for n in nodes(res.asts, kind)]
        assert styles == ["implicit", "explicit"]


def test_cobegin_requires_block() -> None:
    assert parse_errors("cobegin { f(); g(); }\n") == []
    assert parse_errors("cobegin f();\n") != []
    assert not hasattr(chapel.Cobegin, "block_style")


def test_bracket_loops() -> None:
    text = (
        "[i in 1..3] f(i);\n[i in 1..3] { f(i); }\n"
        "var a = [i in 1..3] i * 2;\nvar b: [1..3] int;\n"
    )
    with parse_text(text, "k.chpl") as res:
        assert res.errors == []
        loops = nodes(res.asts, chapel.BracketLoop)
        assert [(n.is_expression_level(), n.block_style()) for n in loops[:2]] == [
            (False, "implicit"),
            (False, "explicit"),
        ]
        # Expression-level loops and array types have no braced body: dyno
        # wraps the element expression in an implicit Block.
        for n in loops[2:]:
            assert n.is_expression_level()
            assert n.block_style() == "implicit"
            assert n.curly_braces_location() is None


def test_bracket_loop_empty_block_is_an_error() -> None:
    # `[i in D] { }` reads as a generic array type with an empty domain.
    assert parse_errors("[i in 1..3] { }\n") != []
    assert parse_errors("[i in 1..3] { f(i); }\n") == []


def test_empty_statements() -> None:
    text = "proc f() { };\nif c then ;\nfor i in 1..3 do ;\n"
    with parse_text(text, "e.chpl") as res:
        assert res.errors == []
        [mod] = res.asts
        assert [type(s).__name__ for s in mod] == [
            "Function",
            "EmptyStmt",
            "Conditional",
            "For",
        ]
        [cond] = nodes(res.asts, chapel.Conditional)
        [loop] = nodes(res.asts, chapel.For)
        for body in (cond.then_block(), loop.body()):
            assert isinstance(body, chapel.Block)
            assert [type(s).__name__ for s in body] == ["EmptyStmt"]


@pytest.mark.parametrize(
    "clauses",
    [
        "where x > 0 lifetime this < x, this = x, return x",
        "lifetime this < x, this = x, return x where x > 0",
    ],
)
def test_where_and_lifetime_clauses(clauses: str) -> None:
    text = f"record R {{ proc m(x: int) {clauses} {{ }} }}\n"
    with parse_text(text, "w.chpl") as res:
        assert res.errors == []
        [fn] = nodes(res.asts, chapel.Function)
        assert fn.where_clause() is not None
        kinds = [type(c).__name__ for c in fn.lifetime_clauses()]
        assert kinds == ["OpCall", "OpCall", "Return"]
        ops = [c.op() for c in fn.lifetime_clauses() if isinstance(c, chapel.OpCall)]
        assert ops == ["<", "="]


def test_with_clauses() -> None:
    text = (
        "forall i in 1..3 with (ref a) { }\ncoforall i in 1..3 with (ref a) { }\n"
        "foreach i in 1..3 with (ref a) { }\n[i in 1..3 with (ref a)] f(i);\n"
        "begin with (ref a) { }\ncobegin with (ref a) { f(); g(); }\n"
        "forall i in 1..3 with(ref a) { }\n"
    )
    with parse_text(text, "w.chpl") as res:
        assert res.errors == []
        kinds = (chapel.Forall, chapel.Coforall, chapel.Foreach, chapel.BracketLoop)
        found = [
            n
            for k in (*kinds, chapel.Begin, chapel.Cobegin)
            for n in nodes(res.asts, k)
        ]
        assert len(found) == 7
        assert all(n.with_clause() is not None for n in found)
    assert hasattr(chapel.For, "with_clause")
