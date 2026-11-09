from pathlib import Path
from typing import Any

import pytest

from chplfmt import api, verify
from chplfmt._chapel import chapel, parse_text
from chplfmt.cli import main
from chplfmt.comments import expected_comment_text, space_line_comment
from chplfmt.config import FormatOptions
from chplfmt.errors import VerificationError
from chplfmt.offregions import find_off_regions, verbatim_spans
from chplfmt.source import SourceText
from chplfmt.tokens import TokenIndex

ALL_OFF: dict[str, Any] = {
    "comment_spacing": False,
    "trailing_comma": False,
    "single_statement_body": "preserve",
    "remove_redundant_parens": False,
    "remove_empty_statements": False,
}


def run(inp: str, out: str, **opts: Any) -> VerificationError | None:
    try:
        verify.verify(inp, out, "t.chpl", FormatOptions(**opts))
    except VerificationError as e:
        return e
    return None


def ok(inp: str, out: str, **opts: Any) -> None:
    err = run(inp, out, **opts)
    assert err is None, str(err)


def fails(inp: str, out: str, check: str, **opts: Any) -> VerificationError:
    err = run(inp, out, **opts)
    assert err is not None, "verification passed"
    assert err.check == check, str(err)
    return err


SAMPLE = """\
// leading comment
module M {
  /* block
     comment */
  proc f(in x: int, ref y) throws where x > 0 {
    var a = [1, 2, 3];
    for i in 1..10 do y += (x + i) * 2; // trailing
    return "s\\n" + b"b" + '''t''';
  }
  record R { var v = 1_000; }
  enum E { a, b }
  begin { f(1, y=2); }
}
"""


# Table


def _ast_classes() -> list[type]:
    return [
        c
        for c in vars(chapel).values()
        if isinstance(c, type) and issubclass(c, chapel.AstNode)
    ]


def test_attribute_tables_cover_every_class_and_method() -> None:
    problems: list[str] = []
    for cls in _ast_classes():
        name = cls.__name__
        own = sorted(m for m in vars(cls) if not m.startswith("_"))
        listed = sorted(m for t in verify.ATTRIBUTE_TABLES for m in t.get(name, ()))
        if not own and name not in verify.NO_OWN_ATTRS:
            problems.append(f"{name}: not in NO_OWN_ATTRS")
        if own and name in verify.NO_OWN_ATTRS:
            problems.append(f"{name}: has methods {own}")
        if listed != own:
            problems.append(f"{name}: methods {own} but tables list {listed}")
    known = {c.__name__ for c in _ast_classes()}
    for table in verify.ATTRIBUTE_TABLES:
        problems += [f"{n}: unknown class" for n in table if n not in known]
    assert problems == []


def test_fingerprint_ignores_comments_and_locations() -> None:
    a = "var x = (1); // c\n"
    b = "\n\n  var   x =\n (1)  ;\n"
    with parse_text(a, "t.chpl") as ra, parse_text(b, "t.chpl") as rb:
        ia = TokenIndex.build(SourceText.from_text(a), ra.asts)
        ib = TokenIndex.build(SourceText.from_text(b), rb.asts)
        assert verify.fingerprint(ra.asts[0], ia) == verify.fingerprint(rb.asts[0], ib)


# Basic checks


@pytest.mark.parametrize("opts", [{}, ALL_OFF], ids=["defaults", "all-off"])
def test_identity_passes(opts: dict[str, Any]) -> None:
    ok(SAMPLE, SAMPLE, **opts)


def test_whitespace_only_changes_pass() -> None:
    ok("var x=1;\nproc f(){return x;}\n", "var x = 1;\nproc f() {\n  return x;\n}\n")


def test_reparse() -> None:
    err = fails("var x = 1;\n", "var x = ;\n", "reparse")
    assert err.input_pos == (0, 0)
    assert err.output_pos[0] == 1


@pytest.mark.parametrize(
    ("inp", "out"),
    [
        ("x = a + b;\n", "x = a - b;\n"),
        ("x = a + b;\n", "x = a + c;\n"),
        ("var x = 1_000;\n", "var x = 1000;\n"),
        ("var x = 0x1F;\n", "var x = 0x1f;\n"),
        ('var s = "a";\n', "var s = 'a';\n"),
        ('var s = "\\x41";\n', 'var s = "A";\n'),
        ("proc f(in x) { }\n", "proc f(const x) { }\n"),
        ("var x: int;\n", "var x = int;\n"),
        ("f(a=1);\n", "f(b=1);\n"),
        ("x = (a + b) * c;\n", "x = a + b * c;\n"),
        ("var t = (1,);\n", "var t = (1);\n"),
    ],
)
def test_ast_changes_fail(inp: str, out: str) -> None:
    fails(inp, out, "ast")
    fails(inp, out, "ast", **ALL_OFF)


def test_ast_error_positions() -> None:
    err = fails("var x =\n  a + b;\n", "var x = a - b;\n", "ast")
    assert (err.input_pos, err.output_pos) == ((2, 3), (1, 9))
    assert str(err) == (
        "t.chpl: internal error: formatter output failed verification (ast) "
        "at input 2:3 / output 1:9"
    )


def test_error_message_format() -> None:
    err = api.VerificationError("a/b.chpl", "tokens", (3, 4), (5, 6))
    assert str(err) == (
        "a/b.chpl: internal error: formatter output failed verification "
        "(tokens) at input 3:4 / output 5:6"
    )
    assert isinstance(err, api.FormatError)


def test_multiline_string_must_match_exactly() -> None:
    inp = 'var s = """a\r\nb""";\n'
    fails(inp, 'var s = """a\nb""";\n', "ast")


# Rules


def test_redundant_parens() -> None:
    inp = "x = (a);\nproc f() { return ((b + c)); }\n"
    out = "x = a;\nproc f() { return b + c; }\n"
    ok(inp, out)
    fails(inp, out, "tokens", remove_redundant_parens=False)


def test_body_braces() -> None:
    inp = "if c { f(); }\nfor i in D { g(i); }\nbegin { h(); }\n"
    out = "if c then f();\nfor i in D do g(i);\nbegin h();\n"
    ok(inp, out)
    ok(out, inp, single_statement_body="prefer-braces")
    fails(inp, out, "ast", single_statement_body="preserve")
    ok("if c then { f(); }\n", "if c { f(); }\n")
    fails("if c then { f(); }\n", "if c { f(); }\n", "ast", **ALL_OFF)


def test_braces_of_non_bodies_are_kept() -> None:
    fails("cobegin { f(); g(); }\n", "cobegin f(); g();\n", "reparse")


def test_trailing_comma() -> None:
    ok("var A = [1, 2];\n", "var A = [1, 2,];\n")
    ok("var A = [1, 2,];\n", "var A = [1, 2];\n")
    ok("enum E { a, b, }\n", "enum E { a, b }\n")
    ok("var t = (1, 2,);\n", "var t = (1, 2);\n")
    fails("var A = [1, 2];\n", "var A = [1, 2,];\n", "ast", trailing_comma=False)
    fails("enum E { a, b, }\n", "enum E { a, b }\n", "tokens", trailing_comma=False)
    fails("f(a, b);\n", "f(a, b,);\n", "reparse")


def test_one_tuple_comma_is_kept() -> None:
    fails("var (a,) = t;\n", "var (a) = t;\n", "tokens")


def test_empty_statements() -> None:
    inp, out = "x = 1;;\nproc f() { };\n", "x = 1;\nproc f() { }\n"
    ok(inp, out)
    fails(inp, out, "ast", remove_empty_statements=False)
    # `do ;` may become `{ }` when single-statement-body adds braces.
    ok("for i in D do ;\n", "for i in D { }\n", single_statement_body="prefer-braces")


def test_empty_statement_rule_does_not_allow_other_changes() -> None:
    fails("x = 1;;\n", "x = 2;\n", "ast")


# Comments


def test_comment_changes_fail() -> None:
    inp = "// a\nvar x; // b\n/* c */ var y;\n"
    fails(inp, "// a\nvar x;\n/* c */ var y;\n", "comments")
    fails(inp, "// a\nvar x; /* c */ // b\nvar y;\n", "comments")
    fails(inp, "// A\nvar x; // b\n/* c */ var y;\n", "comments")
    ok(inp, "// a\nvar x; // b\n/* c */\nvar y;\n")


def test_comment_spacing() -> None:
    inp, out = "//foo\n//1\n//\n// x\n//---\n//!x\n///x\n//é\n", ""
    out = "// foo\n// 1\n//\n// x\n//---\n//!x\n///x\n// é\n"
    ok(inp + "var x;\n", out + "var x;\n")
    fails(inp + "var x;\n", out + "var x;\n", "comments", comment_spacing=False)
    fails(inp + "var x;\n", inp + "var x;\n", "comments")
    ok(inp + "var x;\n", inp + "var x;\n", comment_spacing=False)


def test_tabs_in_comments_expand_from_source_column() -> None:
    inp = "var x = 1;\t//\ta\n"
    # Tab size 8: the comment starts at column 16, its tab at 18 -> 24.
    ok(inp, "var x = 1; //      a\n", tab_size=8)
    # Tab size 4: the comment starts at 12, its tab at 14 -> 16.
    ok(inp, "var x = 1; //  a\n", tab_size=4)
    fails(inp, "var x = 1; //      a\n", "comments", tab_size=4)
    # The comment starts at 11, its tab at 13 (from column 0 it would be 2 -> 4).
    inp = "var x = 1; //\ta\n"
    ok(inp, "var x = 1;    //   a\n", tab_size=4)
    fails(inp, "var x = 1;    //  a\n", "comments", tab_size=4)


def test_trailing_whitespace_in_comments_is_removed() -> None:
    ok("// a  \nvar x;\n", "// a\nvar x;\n")
    fails("// a  \nvar x;\n", "// a  \nvar x;\n", "comments")


def test_block_comment_reindent() -> None:
    inp = "proc f() {\n      /* a\n         b */\n  return;\n}\n"
    ok(inp, "proc f() {\n  /* a\n     b */\n  return;\n}\n")
    fails(inp, "proc f() {\n  /* a\n         b */\n  return;\n}\n", "comments")
    # Never below column 0.
    inp = "proc f() {\n    /* a\n b */\n  return;\n}\n"
    ok(inp, "proc f() {\n  /* a\nb */\n  return;\n}\n")


def test_block_comment_crlf() -> None:
    ok("/* a\r\n b */\r\nvar x;\r\n", "/* a\n b */\nvar x;\n")
    fails("/* a\r\n b */\r\nvar x;\r\n", "/* a\r\n b */\nvar x;\n", "comments")


def test_expected_comment_text() -> None:
    assert space_line_comment("//x") == "// x"
    assert space_line_comment("//  x") == "//  x"
    assert (
        expected_comment_text(
            "/*\ta\n\t b */",
            input_col=2,
            output_col=0,
            tab_size=4,
            comment_spacing=True,
        )
        == "/*    a\n   b */"
    )


# Off regions and extern blocks

OFF = "var a  =  1;\n// chplfmt: off\nvar   x = 1;\n// chplfmt: on\nvar y   = 2;\n"


def test_off_region_is_verbatim() -> None:
    ok(OFF, OFF.replace("a  =  1", "a = 1").replace("y   =", "y ="))
    err = fails(OFF, OFF.replace("var   x = 1;", "var   x = 1; "), "verbatim")
    assert err.input_pos == (3, 13)
    fails(OFF, OFF.replace("var   x", "var x"), "verbatim")


def test_off_region_comments_are_not_rewritten() -> None:
    inp = "// chplfmt: off\n//x\t\n// chplfmt: on\nvar y;\n"
    ok(inp, inp)
    fails(inp, inp.replace("//x\t", "// x"), "verbatim")


def test_crlf_inside_off_region_is_kept() -> None:
    crlf = OFF.replace("\n", "\r\n")
    lines = crlf.split("\r\n")
    out = "\n".join([lines[0], "\r\n".join(lines[1:4]), *lines[4:]])
    ok(crlf, out)
    fails(crlf, OFF, "verbatim")


def test_extern_block_is_verbatim() -> None:
    inp = "extern {\n  int  x;\n}\nvar y;\n"
    ok(inp, inp.replace("var y;", "var  y;"))
    fails(inp, inp.replace("int  x", "int x"), "tokens")


def _regions(text: str) -> tuple[list[str], list[int]]:
    with parse_text(text, "t.chpl") as r:
        index = TokenIndex.build(SourceText.from_text(text), r.asts)
        off = find_off_regions(index)
        return [text[s:e] for s, e in verbatim_spans(index, off)], off.misplaced


def test_off_region_detection() -> None:
    assert _regions(OFF)[0] == ["// chplfmt: off\nvar   x = 1;\n// chplfmt: on"]
    # No `on`: to the end of the statement list.
    text = "proc f() {\n  // chplfmt: off\n  a( );\n  b( ); // t\n}\nc( );\n"
    assert _regions(text) == (["  // chplfmt: off\n  a( );\n  b( ); // t"], [])
    text = "// chplfmt: off\na( );\n"
    assert _regions(text)[0] == ["// chplfmt: off\na( );"]
    # The `on` must be in the same list.
    text = "// chplfmt: off\nproc f() {\n  // chplfmt: on\n}\nb( );\n"
    assert _regions(text)[0] == [text[:-1]]
    # Not at statement level; not alone on its line; `on` without `off`.
    text = "f(a,\n  // chplfmt: off\n  b);\nx; // chplfmt: off\n// chplfmt: on\n"
    regions, misplaced = _regions(text)
    assert regions == []
    assert len(misplaced) == 2


# API and CLI


def test_format_text_verifies_and_dumps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(api, "_identity_print", lambda index, options: "var y;\n")
    with pytest.raises(VerificationError) as info:
        api.format_text("var x;\n", path="d/a.chpl")
    assert info.value.check == "ast"
    assert not (tmp_path / "a.chpl.failed").exists()
    with pytest.raises(VerificationError):
        api.format_text(
            "var x;\n",
            path="d/a.chpl",
            debug=api.DebugOptions(dump_failed_dir=str(tmp_path)),
        )
    assert (tmp_path / "a.chpl.failed").read_text() == "var y;\n"
    result = api.format_text(
        "var x;\n", path="a.chpl", debug=api.DebugOptions(skip_verify=True)
    )
    assert result.text == "var y;\n"


def test_format_text_normalizes_comments() -> None:
    assert api.format_text("//x\t \nvar x;\n").text == "// x\nvar x;\n"


def test_cli_debug_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    Path("a.chpl").write_text("var x;\n")
    monkeypatch.setattr(api, "_identity_print", lambda index, options: "var y;\n")
    assert main(["a.chpl", "--debug-dump-failed", "dump"]) == 4
    assert "failed verification (ast) at input 1:1 / output 1:1" in (
        capsys.readouterr().err
    )
    assert Path("dump/a.chpl.failed").read_text() == "var y;\n"
    assert main(["a.chpl", "--debug-skip-verify"]) == 0
    assert capsys.readouterr().out == "var y;\n"
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--debug" not in capsys.readouterr().out
