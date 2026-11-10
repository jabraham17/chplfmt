from typing import Any

import pytest

from chplfmt import api
from chplfmt._chapel import chapel, parse_text
from chplfmt.config import FormatOptions
from chplfmt.doc import Doc, concat, hardline, indent, render, text
from chplfmt.printer import Printer
from chplfmt.source import SourceText
from chplfmt.tokens import Node, TokenIndex


def fmt(source: str, **options: Any) -> str:
    return api.format_text(source, options=FormatOptions(**options)).text


def printer_for(source: str, **kwargs: Any) -> tuple[Printer, TokenIndex]:
    with parse_text(source, "t.chpl") as parsed:
        assert not parsed.errors
        index = TokenIndex.build(SourceText.from_text(source), parsed.asts)
    return Printer(index, FormatOptions(), **kwargs), index


# Fallback re-indentation


def test_fallback_reindents_relative_to_first_line() -> None:
    src = "  proc f() {\n      if x {\n        g();\n      }\n    }\n"
    assert fmt(src) == "proc f() {\n    if x {\n      g();\n    }\n  }\n"


def test_fallback_never_goes_below_column_zero() -> None:
    src = "    proc f() {\n  g();\n}\n"
    assert fmt(src) == "proc f() {\ng();\n}\n"


def test_tabs_become_spaces_by_display_width() -> None:
    src = "\tproc f() {\n\t\tvar x\t= 1;\n\t}\n"
    # Indentation moves by the first line's (4); the inner tab fills to col 16.
    assert fmt(src, tab_size=4) == "proc f() {\n    var x   = 1;\n}\n"


def test_crlf_and_trailing_whitespace() -> None:
    assert fmt("var x;  \r\nproc f() { \t\r\n  g();\r\n}\r\n") == (
        "var x;\nproc f() {\n  g();\n}\n"
    )


def test_multiline_strings_are_untouched() -> None:
    src = '    proc f() {\n      writeln("""a  \n\t b""");\n    }\n'
    assert fmt(src) == 'proc f() {\n  writeln("""a  \n\t b""");\n}\n'
    src = 'var s = """a \r\nb""";\r\n'
    assert fmt(src) == 'var s = """a \r\nb""";\n'


def test_tabs_in_single_line_strings_are_kept() -> None:
    assert fmt('var s = "a\tb";\n') == 'var s = "a\tb";\n'


def test_block_comment_moves_with_its_line() -> None:
    src = "  proc f() {\n    /* a\n       b */\n    g(); /* c\n  d */\n  }\n"
    assert fmt(src) == "proc f() {\n  /* a\n     b */\n  g(); /* c\nd */\n}\n"


def test_comments_are_normalized() -> None:
    src = "//x\t \nproc f() {\n  //y  \n  g(); //z\n}\n"
    result = api.format_text(src)
    assert result.text == "// x\nproc f() {\n  // y\n  g(); // z\n}\n"
    assert result.report.rule_counts() == {"comment-spacing": 3}
    assert fmt(src, comment_spacing=False) == (
        "//x\nproc f() {\n  //y\n  g(); //z\n}\n"
    )


def test_tab_in_comment_expands_from_source_column() -> None:
    # The tab is at source column 11 (-> 12), but would be at 9 in the output.
    assert fmt("  var x; /*\ta */\n", tab_size=4) == "var x; /* a */\n"


def test_blank_lines_inside_fallback_collapse() -> None:
    assert fmt("proc f() {\n  g();\n\n\n\n  h();\n}\n") == (
        "proc f() {\n  g();\n\n  h();\n}\n"
    )


def test_module_members_fall_back_individually() -> None:
    src = "module M {\n  var x;\n}\n"
    result = api.format_text(src)
    assert result.text == src
    assert result.report.fallbacks == ["Variable@2:3"]


def test_fallback_keeps_attributes() -> None:
    src = "@chpldoc.nodoc\nvar  x = 1;\n@unstable  proc f() { }\n"
    result = api.format_text(src)
    assert result.text == src
    assert "Function@3:1" in result.report.fallbacks


# Top-level statement list


def test_blank_lines_collapse_to_max() -> None:
    src = "var a;\n\n\n\nvar b;\n"
    assert fmt(src) == "var a;\n\nvar b;\n"
    assert fmt(src, max_blank_lines=0) == "var a;\nvar b;\n"
    assert fmt(src, max_blank_lines=2) == "var a;\n\n\nvar b;\n"


def test_leading_blank_lines_and_final_newline() -> None:
    assert fmt("\n\n  \n var a;") == "var a;\n"
    assert fmt("var a;\n\n\n") == "var a;\n"
    assert fmt("") == ""
    assert fmt("\n\n") == ""


def test_statements_go_on_their_own_lines() -> None:
    assert fmt("var a; var b;\n") == "var a;\nvar b;\n"


def test_top_level_comments_kept_in_order() -> None:
    src = "// a\n\n\n/* b */ var x; // c\nvar yy; // d\n/* e\n */\n\n// f"
    assert fmt(src) == (
        "// a\n\n/* b */ var x; // c\nvar yy;        // d\n/* e\n */\n\n// f\n"
    )


def test_empty_statements() -> None:
    result = api.format_text("x = 1;;\n;\nvar y;\n")
    assert result.text == "x = 1;\nvar y;\n"
    assert result.report.rule_counts() == {"remove-empty-statements": 2}
    assert fmt("x = 1;;\n", remove_empty_statements=False) == "x = 1;\n;\n"


# Off regions


def test_off_region_is_byte_identical() -> None:
    region = "// chplfmt: off\nvar  b ;  \t\r\n\tvar c;\r\n// chplfmt: on"
    src = f"var a;  \n\n\n{region}\r\n\n\n  var d;\n"
    assert fmt(src) == f"var a;\n\n{region}\n\nvar d;\n"


def test_off_region_to_end_of_file() -> None:
    region = "// chplfmt: off\n  var  b ;\t "
    assert fmt(f"var a;\n{region}\n\n") == f"var a;\n{region}\n"


def test_off_region_inside_fallback() -> None:
    region = "  // chplfmt: off\n\tvar  x ;  \n  // chplfmt: on"
    src = f"  proc f() {{\n{region}\n      var y;\n  }}\n"
    assert fmt(src) == f"proc f() {{\n{region}\n    var y;\n}}\n"


def test_extern_block_is_byte_identical() -> None:
    block = 'extern {\n\t#include "x.h"  \n  }'
    assert fmt(f"  {block}\nvar x;\n") == f"{block}\nvar x;\n"


# Dispatch


def _render(p: Printer) -> str:
    return render(p.print_file(), p.options).text


def test_registered_printer_is_used() -> None:
    calls: list[Node] = []

    def print_var(p: Printer, node: Node) -> Doc:
        calls.append(node)
        assert isinstance(node, chapel.Variable)
        return text(f"VAR {node.name()}")

    # Registered for a base class; applies to subclasses.
    p, _ = printer_for(
        "var x;\nproc f() { }\n", registry={chapel.VarLikeDecl: print_var}
    )
    assert _render(p) == "VAR x\nproc f() { }\n"
    assert len(calls) == 1
    assert p.report.fallbacks == ["Function@2:1"]


def test_print_adds_user_parens() -> None:
    def print_var(p: Printer, node: Node) -> Doc:
        assert isinstance(node, chapel.Variable)
        init = node.init_expression()
        assert init is not None
        return concat("var ", node.name(), " = ", p.print(init), ";")

    p, _ = printer_for("var x = ((1));\n", registry={chapel.Variable: print_var})
    assert _render(p) == "var x = ((1));\n"
    # An expression's fallback doesn't take the statement's `;`.
    p, _ = printer_for("var x = 1 +\n  2;\n", registry={chapel.Variable: print_var})
    assert _render(p) == "var x = 1 +\n  2;\n"
    assert p.report.fallbacks == ["OpCall@1:9"]


def test_nested_tracks_indent_for_fallback() -> None:
    p, index = printer_for("proc f() {\ng();\n    }\n")
    (fn,) = index.children(index.roots[0])
    with p.nested() as n:
        assert p.indent == 2
        body = p.print(fn)
    assert p.indent == 0
    doc = concat("{", indent(concat(hardline, body), n), hardline, "}", hardline)
    assert render(doc, p.options).text == "{\n  proc f() {\n  g();\n      }\n}\n"


def test_off_region_node_prints_verbatim() -> None:
    p, index = printer_for("// chplfmt: off\nvar  x ;\n")
    (var,) = index.children(index.roots[0])
    assert render(p.print(var), p.options).text == "var  x ;"
    assert p.report.fallbacks == []


@pytest.mark.parametrize("src", ["var x;\n", "/* a */\n", "// chplfmt: off\n"])
def test_idempotent_examples(src: str) -> None:
    assert fmt(fmt(src)) == fmt(src)
