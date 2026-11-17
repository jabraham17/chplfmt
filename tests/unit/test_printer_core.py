from typing import Any

import pytest

from chplfmt import api
from chplfmt._chapel import chapel, parse_text
from chplfmt.config import FormatOptions
from chplfmt.doc import Doc, concat, hardline, indent, render, text
from chplfmt.printer import REGISTRY, Printer
from chplfmt.source import SourceText
from chplfmt.tokens import Node, TokenIndex


def fmt(source: str, **options: Any) -> str:
    return api.format_text(source, options=FormatOptions(**options)).text


def printer_for(source: str, **kwargs: Any) -> tuple[Printer, TokenIndex]:
    with parse_text(source, "t.chpl") as parsed:
        assert not parsed.errors
        index = TokenIndex.build(SourceText.from_text(source), parsed.asts)
    return Printer(index, FormatOptions(), **kwargs), index


@pytest.fixture
def no_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loops fall back, so they can serve as fallback examples."""
    for cls in (chapel.While, chapel.Foreach):
        monkeypatch.delitem(REGISTRY, cls)


# Fallback re-indentation


@pytest.mark.usefixtures("no_loops")
def test_fallback_reindents_relative_to_first_line() -> None:
    src = "  while x {\n      if x {\n        g();\n      }\n    }\n"
    assert fmt(src) == "while x {\n    if x {\n      g();\n    }\n  }\n"


@pytest.mark.usefixtures("no_loops")
def test_fallback_never_goes_below_column_zero() -> None:
    src = "    while x {\n  g();\n}\n"
    assert fmt(src) == "while x {\ng();\n}\n"


@pytest.mark.usefixtures("no_loops")
def test_tabs_become_spaces_by_display_width() -> None:
    src = "\twhile x {\n\t\tvar x\t= 1;\n\t}\n"
    # Indentation moves by the first line's (4); the inner tab fills to col 16.
    assert fmt(src, tab_size=4) == "while x {\n    var x   = 1;\n}\n"


def test_crlf_and_trailing_whitespace() -> None:
    assert fmt("var x;  \r\nproc f() { \t\r\n  g();\r\n  h();\r\n}\r\n") == (
        "var x;\nproc f() {\n  g();\n  h();\n}\n"
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


@pytest.mark.usefixtures("no_loops")
def test_module_members_fall_back_individually() -> None:
    src = "module M {\n  while  x { f(); }\n}\n"
    result = api.format_text(src)
    assert result.text == src
    assert result.report.fallbacks == ["While@2:3"]


@pytest.mark.usefixtures("no_loops")
def test_fallback_keeps_attributes() -> None:
    src = "@gpu.assertEligible\nforeach  i in 1..2 { }\n"
    result = api.format_text(src)
    assert result.text == src
    assert result.report.fallbacks == ["Foreach@1:1"]


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


@pytest.mark.parametrize(
    "source",
    [
        "var a = [1, 2; 3, 4; ; 5, 6; 7, 8;];\n",
        "var a = [1, 2; 3, 4; ; 5, 6; 7, 8; ; ; "
        "9, 10; 11, 12; ; 13, 14; 15, 16;];\n",
    ],
)
def test_multidimensional_array_rows_preserve_dimensions(source: str) -> None:
    for opts in ({}, {"line_length": 20}, {"bracket_spacing": True}):
        once = fmt(source, **opts)
        assert fmt(once, **opts) == once
        assert "1, 2; 3, 4;" in once
        assert "5, 6; 7, 8;" in once


def test_multidecl_end_of_line_block_comments_are_stable() -> None:
    source = (
        "const first = 1, /* long comment about first */\n"
        "      second = 2, third = 3, /* long comment about third */\n"
        "      fourth = 4, fifth = 5;\n"
    )
    once = fmt(source, line_length=55)
    assert fmt(once, line_length=55) == once
    assert "/* long comment about first */\n" in once
    assert "/* long comment about third */\n" in once


def test_multiline_typed_assignment_wraps_initializer() -> None:
    source = (
        "const gammaCoef: 4*(8*real) = "
        "((1.0, 1.0, -1.0, -1.0, 1.0, 1.0, -1.0, -1.0), "
        "(1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0));\n"
    )
    once = fmt(source, line_length=60)
    assert fmt(once, line_length=60) == once
    assert max(map(len, once.splitlines())) <= 60


def test_header_block_comment_stays_put_with_broken_brace() -> None:
    source = "class C /* : B */ { var x: int; }\n"
    once = fmt(source, brace_style="break")
    assert "class C /* : B */\n{" in once
    assert fmt(once, brace_style="break") == once


@pytest.mark.parametrize("separator", [" ", "\n"])
def test_function_header_comment_is_emitted_once(separator: str) -> None:
    source = f"proc f() /* throws */{separator}{{ first(); second(); }}\n"
    once = fmt(source, brace_style="break")
    assert once.index("/* throws */") < once.index("{")
    assert once.count("/* throws */") == 1
    assert fmt(once, brace_style="break") == once


@pytest.mark.parametrize(
    "source",
    [
        "module M { record R { "
        "var sendBufs: [locDom.NeighDom] [locDom.bufDom] eltType; } }\n",
        "proc f() { return + reduce [loc in targetLocDom] "
        "locDoms[loc].myInds.size; }\n",
        "module M { proc f() { if true { if true { "
        "var (hasElt, elt): (bool, eltType) = "
        "targetSegment.stealElement(); } } } }\n",
        "proc f() { return try! (parent._value:LocaleModel)._node_id; }\n",
        "module M { proc f() { try { f(); } "
        "catch (e: UnexpectedEofError) { return 1; } } }\n",
        "module M { inline proc (borrowed RootClass?).hash(): uint "
        "{ var x = 1; return x; } }\n",
    ],
)
def test_nested_expressions_fit_narrow_lines(source: str) -> None:
    once = fmt(source, line_length=40)
    assert max(map(len, once.splitlines())) <= 40
    assert fmt(once, line_length=40) == once


def test_commented_named_arguments_fit_with_increased_indentation() -> None:
    source = (
        "module M { proc type BlockCyclic1dom.dsiPrivatize1d"
        "(privDist, privatizeData) { return new BlockCyclic1dom("
        "wholeR=privatizeData(0), storagePerCycle=privatizeData(2),\n"
        " // could include these in privatizeData\n"
        " blockSizePos=privDist.blockSizePos, "
        "numLocalesPos=privDist.numLocalesPos, "
        "cycleSizePos=privDist.cycleSizePos); } }\n"
    )
    for opts in ({"continuation_indent": 4}, {"indent_width": 4}):
        once = fmt(source, **opts)
        assert max(map(len, once.splitlines())) <= 80
        assert "blockSizePos=privDist.blockSizePos,\n" in once
        assert fmt(once, **opts) == once


def test_multiline_string_can_move_after_call_bracket() -> None:
    source = (
        "module M { record R { proc f() { if true { "
        'compilerError("lowerBound is not available on types that can'
        "'t be \\\n"
        '                      default-initialized, here: " + eltType:string);'
        " } } } }\n"
    )
    once = fmt(source, indent_width=4)
    assert max(map(len, once.splitlines())) <= 80
    assert "compilerError(\n" in once
    assert fmt(once, indent_width=4) == once


@pytest.mark.parametrize(
    "line_length, continuation_indent, expected",
    [
        (80, 2, "const result = combine(alpha, beta);\n"),
        (0, 2, "const result = combine(alpha, beta);\n"),
        (30, 2, "const result =\n  combine(alpha, beta);\n"),
        (30, 4, "const result =\n    combine(alpha, beta);\n"),
    ],
)
def test_assignment_breaks_after_equals(
    line_length: int, continuation_indent: int, expected: str
) -> None:
    options = dict(line_length=line_length, continuation_indent=continuation_indent)
    assert fmt("const result = combine(alpha, beta);\n", **options) == expected
    assert fmt(expected, **options) == expected


def test_assignment_with_wrapped_call_comment_is_idempotent() -> None:
    source = (
        "err = qio_channel_advance_past_byte(false, ch_internal, firstByte, "
        "maxToRead, /* consume */ false);\n"
    )
    once = fmt(source)
    assert fmt(once) == once


@pytest.mark.parametrize("opening, closing", [("[", "]"), ("(", ")")])
@pytest.mark.parametrize("line_length", [35, 80])
@pytest.mark.parametrize("prefix", ["", "firstArgument, "])
def test_outer_call_breaks_before_single_item_delimiters(
    opening: str, closing: str, line_length: int, prefix: str
) -> None:
    receiver = "aVeryLongArrayReceiverName"
    if line_length == 80:
        receiver = receiver * 2 + "WithLongerNameExtra"
    inner = f"{receiver}{opening}i{closing}"
    first = "  firstArgument,\n" if prefix else ""
    expected = f"consume(\n{first}  {inner}\n);\n"
    assert fmt(f"consume({prefix}{inner});\n", line_length=line_length) == expected
    assert fmt(expected, line_length=line_length) == expected


@pytest.mark.parametrize("opening, closing", [("[", "]"), ("(", ")")])
def test_single_item_delimiters_can_split_as_last_resort(
    opening: str, closing: str
) -> None:
    receiver = "longReceiverlongReceiverWithName"
    source = f"{receiver}{opening}i{closing};\n"
    expected = f"{receiver}{opening}\n  i\n{closing};\n"
    assert fmt(source, line_length=35) == expected
    assert all(len(line) <= 35 for line in expected.splitlines())
    assert fmt(expected, line_length=35) == expected


@pytest.mark.parametrize("opening, closing", [("[", "]"), ("(", ")")])
def test_single_item_delimiters_keep_required_comment_breaks(
    opening: str, closing: str
) -> None:
    source = f"consume(values{opening}// index\nidx{closing});\n"
    result = fmt(source, line_length=35)
    assert "// index\n" in result
    assert fmt(result, line_length=35) == result


def test_zip_bin_packs_comprehension_iterands() -> None:
    source = (
        "const packed = [entry in zip(firstArray, secondArray, thirdArray, "
        "fourthArray, fifthArray)] entry;\n"
    )
    result = fmt(source, line_length=50)
    assert result.startswith("const packed =\n  [entry in zip(")
    assert "firstArray, secondArray," in result
    assert ")] entry;\n" in result
    assert all(len(line) <= 50 for line in result.splitlines())
    assert fmt(result, line_length=50) == result


@pytest.mark.parametrize("separator", [" ", "\n"])
def test_assignment_with_wrapped_argument_comment_is_idempotent(separator: str) -> None:
    source = (
        "proc f() { while true { while true { "
        "err = qio_channel_advance_past_byte(false, ch_internal, firstByte, maxToRead,"
        f"{separator}/* consume */ false);"
        " } } }\n"
    )
    result = fmt(source)
    assert "      err =\n        qio_channel_advance_past_byte(" in result
    assert fmt(result) == result


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


@pytest.mark.usefixtures("no_loops")
def test_off_region_inside_fallback() -> None:
    region = "  // chplfmt: off\n\tvar  x ;  \n  // chplfmt: on"
    src = f"  while x {{\n{region}\n      var y;\n  }}\n"
    assert fmt(src) == f"while x {{\n{region}\n    var y;\n}}\n"


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

    reg: dict[type, Any] = {chapel.Variable: print_var}
    p, index = printer_for("var x = ((1));\n", registry=reg)
    assert _render(p) == "var x = 1;\n"
    opts = FormatOptions(remove_redundant_parens=False)
    assert _render(Printer(index, opts, registry=reg)) == "var x = ((1));\n"
    # An expression's fallback doesn't take the statement's `;`.
    p, _ = printer_for("var x = 1 +\n  2;\n", registry=reg)
    assert _render(p) == "var x = 1 +\n  2;\n"
    assert p.report.fallbacks == ["OpCall@1:9"]


@pytest.mark.usefixtures("no_loops")
def test_nested_tracks_indent_for_fallback() -> None:
    p, index = printer_for("while x {\ng();\n    }\n")
    (fn,) = index.children(index.roots[0])
    with p.nested() as n:
        assert p.indent == 2
        body = p.print(fn)
    assert p.indent == 0
    doc = concat("{", indent(concat(hardline, body), n), hardline, "}", hardline)
    assert render(doc, p.options).text == "{\n  while x {\n  g();\n      }\n}\n"


def test_off_region_node_prints_verbatim() -> None:
    p, index = printer_for("// chplfmt: off\nvar  x ;\n")
    (var,) = index.children(index.roots[0])
    assert render(p.print(var), p.options).text == "var  x ;"
    assert p.report.fallbacks == []


@pytest.mark.parametrize("src", ["var x;\n", "/* a */\n", "// chplfmt: off\n"])
def test_idempotent_examples(src: str) -> None:
    assert fmt(fmt(src)) == fmt(src)
