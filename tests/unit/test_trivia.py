from typing import Any

import pytest

from chplfmt import api
from chplfmt._chapel import chapel, parse_text
from chplfmt.config import FormatOptions
from chplfmt.doc import Doc, concat, hardline, indent, text
from chplfmt.errors import InternalError
from chplfmt.printer import REGISTRY, Printer
from chplfmt.source import SourceText
from chplfmt.tokens import Node, TokenIndex
from chplfmt.trivia import attach


def table(src: str) -> list[tuple[str, str, str, str, str]]:
    """(comment, node, role, placement, anchor) for each comment, in order."""
    with parse_text(src, "t.chpl") as parsed:
        assert not parsed.errors
        index = TokenIndex.build(SourceText.from_text(src), parsed.asts)
        a = attach(index)
        rows: list[tuple[str, str, str, str, str]] = []
        for i in a.comments:
            node, role = a.where[i]
            name = "FILE" if node is None else node.tag()
            if isinstance(node, chapel.NamedDecl):
                name += ":" + node.name()
            nc = a.of(node)
            cs = nc.leading + nc.trailing + [d.comment for d in nc.dangling]
            (c,) = [c for c in cs if c.token == i]
            anchor = ""
            if role == "dangling":
                (d,) = [d for d in nc.dangling if d.comment.token == i]
                anchor = d.anchor.kind if d.anchor else "-"
            rows.append((index.tokens[i].text, name, role, c.placement, anchor))
        return rows


EOL = "end-of-line"
OWN = "own-line"
INL = "inline"


CASES: list[tuple[str, list[tuple[str, str, str, str, str]]]] = [
    # Before/after statements; file start and end.
    (
        "// a\nvar x = 1; // b\n// c\nvar y = 2;\n// d\n",
        [
            ("// a", "Variable:x", "leading", OWN, ""),
            ("// b", "Variable:x", "trailing", EOL, ""),
            ("// c", "Variable:y", "leading", OWN, ""),
            ("// d", "Variable:y", "trailing", OWN, ""),
        ],
    ),
    ("// only\n", [("// only", "Module:t", "dangling", OWN, "-")]),
    (
        "/* a */ /* b */ var x;\n",
        [
            ("/* a */", "Variable:x", "leading", OWN, ""),
            ("/* b */", "Variable:x", "leading", INL, ""),
        ],
    ),
    (
        "// a\n// b\nvar x;\n",
        [
            ("// a", "Variable:x", "leading", OWN, ""),
            ("// b", "Variable:x", "leading", OWN, ""),
        ],
    ),
    (
        "var x; // a\n// b\n",
        [
            ("// a", "Variable:x", "trailing", EOL, ""),
            ("// b", "Variable:x", "trailing", OWN, ""),
        ],
    ),
    # Between header and `{`: end-of-line moves after `{`.
    ("proc f() // c\n{\n  g();\n}\n", [("// c", "Block", "dangling", EOL, "{")]),
    (
        "proc f() // a\n// b\n{\n}\n",
        [
            ("// a", "Block", "dangling", EOL, "{"),
            ("// b", "Block", "dangling", OWN, "{"),
        ],
    ),
    ("proc f() /* c */ {\n  g();\n}\n", [("/* c */", "Block", "leading", INL, "")]),
    ("proc f() { // c\n  g();\n}\n", [("// c", "Block", "dangling", EOL, "{")]),
    ("module M { // c\n  var x;\n}\n", [("// c", "Module:M", "dangling", EOL, "{")]),
    ("if x { // c\n  a();\n}\n", [("// c", "Block", "dangling", EOL, "{")]),
    ("if x then // c\n  a();\n", [("// c", "Conditional", "dangling", EOL, "then")]),
    # Empty blocks and lists: dangling.
    ("proc f() {\n  // c\n}\n", [("// c", "Block", "dangling", OWN, "{")]),
    ("proc f() { /* c */ }\n", [("/* c */", "Block", "dangling", INL, "{")]),
    ("module M {\n  // c\n}\n", [("// c", "Module:M", "dangling", OWN, "{")]),
    ("for i in 1..3 {\n  // c\n}\n", [("// c", "Block", "dangling", OWN, "{")]),
    ("f(/* c */);\n", [("/* c */", "FnCall", "dangling", INL, "(")]),
    ("proc f(/* c */) {}\n", [("/* c */", "Function:f", "dangling", INL, "(")]),
    # Before `else`: leading of the else branch.
    (
        "if x {\n  a();\n}\n// c\nelse {\n  b();\n}\n",
        [
            ("// c", "Block", "leading", OWN, ""),
        ],
    ),
    (
        "if x {\n  a();\n} // c\nelse {\n  b();\n}\n",
        [
            ("// c", "Block", "leading", EOL, ""),
        ],
    ),
    ("if x then a(); /* c */ else b();\n", [("/* c */", "Block", "leading", INL, "")]),
    # Own-line after the last statement of a block.
    ("proc f() {\n  g();\n  // c\n}\n", [("// c", "FnCall", "trailing", OWN, "")]),
    (
        "proc f() {\n  g();\n\n\n  // c\n\n}\n",
        [
            ("// c", "FnCall", "trailing", OWN, ""),
        ],
    ),
    ("proc f() {}\n// c\n", [("// c", "Function:f", "trailing", OWN, "")]),
    # Inside expressions.
    ("f(a, /*c*/ b);\n", [("/*c*/", "Identifier", "leading", INL, "")]),
    ("x = /*c*/ 1;\n", [("/*c*/", "IntLiteral", "leading", INL, "")]),
    ("var x = 1 /* c */;\n", [("/* c */", "IntLiteral", "trailing", INL, "")]),
    ("f(a, // c\n  b);\n", [("// c", "Identifier", "trailing", EOL, "")]),
    ("f( // c\n  a);\n", [("// c", "Identifier", "leading", EOL, "")]),
    ("while x /* c */ do f();\n", [("/* c */", "Block", "leading", INL, "")]),
    # Formals.
    ("proc f(a: int, /*c*/ b: int) {}\n", [("/*c*/", "Formal:b", "leading", INL, "")]),
    ("proc f(a: int /*c*/) {}\n", [("/*c*/", "Formal:a", "trailing", INL, "")]),
    ("proc f /*c*/ (a) {}\n", [("/*c*/", "Formal:a", "leading", INL, "")]),
    # Records, enums, select/when.
    (
        "record R {\n  // a\n  var x: int; // b\n  // c\n}\n",
        [
            ("// a", "Variable:x", "leading", OWN, ""),
            ("// b", "Variable:x", "trailing", EOL, ""),
            ("// c", "Variable:x", "trailing", OWN, ""),
        ],
    ),
    ("record R {\n  // c\n}\n", [("// c", "Record:R", "dangling", OWN, "{")]),
    ("record R { /* c */ }\n", [("/* c */", "Record:R", "dangling", INL, "{")]),
    (
        "enum E {\n  a, // c1\n  // c2\n  b\n}\n",
        [
            ("// c1", "EnumElement:a", "trailing", EOL, ""),
            ("// c2", "EnumElement:b", "leading", OWN, ""),
        ],
    ),
    (
        "select x {\n  // c1\n  when 1 do f(); // c2\n  // c3\n"
        "  otherwise do g();\n}\n",
        [
            ("// c1", "When", "leading", OWN, ""),
            ("// c2", "When", "trailing", EOL, ""),
            ("// c3", "When", "leading", OWN, ""),
        ],
    ),
    (
        "select x {\n  when 1 {\n    // c\n  }\n}\n",
        [
            ("// c", "Block", "dangling", OWN, "{"),
        ],
    ),
]


@pytest.mark.parametrize(("src", "expected"), CASES)
def test_attachment(src: str, expected: list[tuple[str, ...]]) -> None:
    assert table(src) == expected


def test_comments_in_off_regions_are_not_attached() -> None:
    src = "// a\n// chplfmt: off\nvar x; // b\n// chplfmt: on\nvar y;\n"
    assert table(src) == [("// a", "Variable:x", "leading", OWN, "")]


# Blank lines


def fmt(source: str, **options: Any) -> str:
    return api.format_text(source, options=FormatOptions(**options)).text


def test_blank_lines_between_statements_collapse() -> None:
    src = "var a;\n\n\n\nvar b;\nvar c;\n\nvar d;\n"
    assert fmt(src) == "var a;\n\nvar b;\nvar c;\n\nvar d;\n"
    assert fmt(src, max_blank_lines=0) == "var a;\nvar b;\nvar c;\nvar d;\n"
    assert fmt(src, max_blank_lines=2) == "var a;\n\n\nvar b;\nvar c;\n\nvar d;\n"


def test_blank_lines_are_counted_before_leading_comments() -> None:
    src = "var a;\n\n\n// c\n\n\n\nvar b;\n"
    assert fmt(src) == "var a;\n\n// c\n\nvar b;\n"
    assert fmt(src, max_blank_lines=0) == "var a;\n// c\nvar b;\n"
    assert fmt(src, max_blank_lines=2) == "var a;\n\n\n// c\n\n\nvar b;\n"


def test_blank_lines_before_trailing_own_line_comments() -> None:
    assert fmt("var a;\n\n\n\n// c\n") == "var a;\n\n// c\n"
    assert fmt("var a;\n\n\n\n// c\n", max_blank_lines=0) == "var a;\n// c\n"


def test_file_start_and_end() -> None:
    assert fmt("\n\n\nvar a;\n\n\n") == "var a;\n"
    assert fmt("\n\n// c\n\n\nvar a;") == "// c\n\nvar a;\n"
    assert fmt("\n\n// a\n\n\n// b\n\n") == "// a\n\n// b\n"
    assert fmt("") == ""
    assert fmt("\n\n") == ""


# Off regions


def test_top_level_off_region_is_byte_identical() -> None:
    region = "// chplfmt: off\nvar  x\t=  1;   \r\n  proc  f( ) { }\n// chplfmt: on\n"
    src = "  var a;\n\n\n" + region + "\n\n\n  var b;\n"
    assert fmt(src) == "var a;\n\n" + region + "\nvar b;\n"


def test_off_region_first_and_last_in_file() -> None:
    src = "// chplfmt: off\n  var  x;\n// chplfmt: on\n  var y;\n"
    assert fmt(src) == "// chplfmt: off\n  var  x;\n// chplfmt: on\nvar y;\n"
    src = "  var y;\n// chplfmt: off\nvar  x;  \n"
    assert fmt(src) == "var y;\n// chplfmt: off\nvar  x;  \n"


def test_nested_off_region_is_byte_identical() -> None:
    region = "  // chplfmt: off\n    var  x\t=  1;  \n  // chplfmt: on\n"
    src = "proc f() {\n" + region + "  g( );\n}\n"
    assert fmt(src) == "proc f() {\n" + region + "  g();\n}\n"


def test_off_region_first_after_brace_gets_no_blank_line() -> None:
    src = "proc f() {\n// chplfmt: off\n  var  x;\n// chplfmt: on\n}\n"
    assert fmt(src) == src


def _module(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.Module)
    tokens = p.tokens
    brace = next(i for i in p.index.own_tokens(node) if tokens[i].text == "{")
    sp = p.index.node_span(node)
    assert sp is not None
    with p.nested() as n:
        body = p.statement_list(p.index.children(node), brace + 1, sp[1])
        dangling = p.dangling_comments(node, "{")
    return concat(
        f"module {node.name()} {{",
        dangling,
        indent(concat(hardline, body), n),
        hardline,
        "}",
    )


@pytest.fixture
def module_printer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REGISTRY, chapel.Module, _module)


@pytest.mark.usefixtures("module_printer")
def test_nested_statement_list_off_region_first_after_brace() -> None:
    src = (
        "module M {\n"
        "// chplfmt: off\n"
        "    var  x;\n"
        "// chplfmt: on\n"
        "\n\n\n"
        "      var y;\n"
        "}\n"
    )
    assert fmt(src) == (
        "module M {\n// chplfmt: off\n    var  x;\n// chplfmt: on\n\n  var y;\n}\n"
    )


@pytest.mark.usefixtures("module_printer")
def test_nested_statement_list_comments_and_blank_lines() -> None:
    src = "module M { // a\n\n    // b\n\n\n    var x; // c\n\n\n    // d\n\n}\n"
    assert fmt(src) == "module M { // a\n  // b\n\n  var x; // c\n\n  // d\n}\n"
    assert fmt(src, max_blank_lines=0) == (
        "module M { // a\n  // b\n  var x; // c\n  // d\n}\n"
    )


def test_misplaced_directive_warns() -> None:
    src = "f(a,\n  // chplfmt: off\n  b);\n"
    result = api.format_text(src, path="t.chpl")
    assert result.text == src
    (w,) = result.report.warnings
    assert (w.line, w.col) == (2, 3)
    assert "chplfmt directive ignored" in w.message


def test_cli_prints_directive_warning(tmp_path: Any, capsys: Any) -> None:
    from chplfmt.cli import main

    p = tmp_path / "t.chpl"
    p.write_text("var x;\n// chplfmt: on\n")
    assert main([str(p)]) == 0
    err = capsys.readouterr().err
    assert err == (
        f"{p}:2:1: warning: chplfmt directive ignored (no matching `chplfmt: off`)\n"
    )


# Exactly-once guarantee


def _drop_comments(p: Printer, node: Node) -> Doc:
    return text("var x = 1;")


def _print_init_twice(p: Printer, node: Node) -> Doc:
    assert isinstance(node, chapel.Variable)
    init = node.init_expression()
    assert init is not None
    return concat("var x = ", p.print(init), p.print(init), ";")


@pytest.fixture
def no_verify(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("verification must not run")

    monkeypatch.setattr(api, "verify", fail)


@pytest.mark.usefixtures("no_verify")
def test_dropped_comment_is_an_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REGISTRY, chapel.Variable, _drop_comments)
    with pytest.raises(
        InternalError, match=r"t.chpl: .*comment at 1:9 printed 0 times"
    ):
        api.format_text("var x = /*c*/ 1;\n", path="t.chpl")


@pytest.mark.usefixtures("no_verify")
def test_duplicated_comment_is_an_internal_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(REGISTRY, chapel.Variable, _print_init_twice)
    with pytest.raises(InternalError, match=r"comment at 1:9 printed 2 times"):
        api.format_text("var x = /*c*/ 1;\n")


def test_printer_with_all_comments_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    def var(p: Printer, node: Node) -> Doc:
        assert isinstance(node, chapel.Variable)
        init = node.init_expression()
        assert init is not None
        return concat("var x = ", p.print(init), ";")

    monkeypatch.setitem(REGISTRY, chapel.Variable, var)
    assert fmt("var  x = /*c*/ 1;  // d\n") == "var x = /*c*/ 1; // d\n"
