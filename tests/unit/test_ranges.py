import gc
import weakref
from pathlib import Path
from typing import Any

import pytest

from chplfmt import api
from chplfmt.cli import main
from chplfmt.config import FormatOptions
from chplfmt.printer import Printer

SRC = """\
proc f(x:int) {
  var a=1;
  for i in 1..x {
    writeln(i,
            a+1);
    var c=i;

    c+=1;
  }
  // note
  var b  =  2;
  return a+b;
}
var z=   3;
"""


def fmt(text: str, a: int, b: int, **options: Any) -> str:
    return api.format_text(text, lines=(a, b), options=FormatOptions(**options)).text


def changed_lines(old: str, new: str) -> list[int]:
    """1-based lines of `old` replaced in `new` (same line count assumed)."""
    a, b = old.splitlines(), new.splitlines()
    assert len(a) == len(b)
    return [k + 1 for k, (x, y) in enumerate(zip(a, b, strict=True)) if x != y]


def test_single_statement() -> None:
    out = fmt(SRC, 2, 2)
    assert changed_lines(SRC, out) == [2]
    assert out.splitlines()[1] == "  var a = 1;"


def test_inside_expression_takes_statement() -> None:
    out = fmt(SRC, 5, 5)
    assert out.splitlines()[3:5] == ["    writeln(i, a + 1);", "    var c=i;"]
    assert out.count("\n") == SRC.count("\n") - 1


def test_multiple_statements_nested_block() -> None:
    out = fmt(SRC, 6, 8)
    lines = out.splitlines()
    assert lines[5:8] == ["    var c = i;", "", "    c += 1;"]
    assert changed_lines(SRC, out) == [6, 8]


def test_partial_lines_and_leading_comment() -> None:
    # Line 10 is a comment leading `var b`; the statement is formatted too.
    out = fmt(SRC, 10, 10)
    assert changed_lines(SRC, out) == [11]


def test_blank_line_unchanged() -> None:
    assert fmt(SRC, 7, 7) == SRC


def test_range_past_end_and_top_level() -> None:
    out = fmt(SRC, 14, 99)
    assert changed_lines(SRC, out) == [14]
    assert out.splitlines()[13] == "var z = 3;"


def test_spanning_close_brace() -> None:
    # From inside the loop to after it: the enclosing list's run (loop..var b).
    out = fmt(SRC, 6, 10).splitlines()
    whole = api.format_text(SRC).text.splitlines()
    assert out[:2] == SRC.splitlines()[:2]
    assert out[2:10] == whole[2:10]
    assert out[10:] == SRC.splitlines()[11:]


def test_whole_file_range_equals_whole_file() -> None:
    assert fmt(SRC, 1, 14) == api.format_text(SRC).text


def test_off_region_unchanged() -> None:
    src = "var a=1;\n// chplfmt: off\nvar  b=2;\n// chplfmt: on\nvar c=3;\n"
    assert fmt(src, 3, 3) == src
    assert fmt(src, 5, 5) == src.replace("var c=3;", "var c = 3;")


def test_odd_indentation_kept() -> None:
    src = "proc f() {\n     var a=1;\n     if a {\n     a=2;\n     }\n}\n"
    out = fmt(src, 2, 5)
    assert out == "proc f() {\n     var a = 1;\n     if a then a = 2;\n}\n"


def test_tab_indentation_becomes_spaces() -> None:
    src = "proc f() {\n\tvar a=1;\n\tvar b=2;\n}\n"
    assert fmt(src, 2, 2, tab_size=4) == "proc f() {\n    var a = 1;\n\tvar b=2;\n}\n"


def test_nested_block_relative_to_base() -> None:
    src = "proc f() {\n   for i in 1..3 {\n   var x=i;\n   writeln(x);\n   }\n}\n"
    out = fmt(src, 2, 2)
    assert out.splitlines()[1:5] == [
        "   for i in 1..3 {",
        "     var x = i;",
        "     writeln(x);",
        "   }",
    ]


def test_crlf_outside_untouched() -> None:
    src = "var a=1;  \r\nvar b=2;\r\nvar c=3;  \r\n"
    out = fmt(src, 2, 2)
    assert out == "var a=1;  \r\nvar b = 2;\r\nvar c=3;  \r\n"


def test_no_final_newline() -> None:
    assert fmt("var a=1;\nvar b=2;", 2, 2) == "var a=1;\nvar b = 2;"


def test_comments_outside_not_normalized() -> None:
    src = "//a\nvar a=1;\n//b\nvar b=2;\n"
    assert fmt(src, 4, 4) == "//a\nvar a=1;\n// b\nvar b = 2;\n"


def test_trailing_comments_align_with_unchanged_neighbors() -> None:
    src = "var a = 1;   // a\nvar bb=2; // b\nvar ccc = 3; // c\n\nvar d=4; // d\n"
    whole = api.format_text(src).text
    out = fmt(src, 2, 2)
    assert out.splitlines()[:3] == whole.splitlines()[:3]
    assert out.splitlines()[1] == "var bb = 2;  // b"
    assert out.splitlines()[3:] == src.splitlines()[3:]


def test_edits_minimal() -> None:
    r = api.format_text(SRC, lines=(2, 2))
    assert r.edits == [api.TextEdit(1, 2, "  var a = 1;\n")]
    assert r.changed


@pytest.mark.parametrize(
    "source",
    ["/* hello\n world */\nvar x=1;\n", "var x=[1,2,3];\n"],
)
@pytest.mark.parametrize("fail", [False, True])
def test_range_releases_printer(
    source: str, fail: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    refs: list[weakref.ReferenceType[Printer]] = []

    def tracked(*args: Any, **kwargs: Any) -> Printer:
        printer = Printer(*args, **kwargs)
        refs.append(weakref.ref(printer))
        return printer

    def failing_splice(*args: Any, **kwargs: Any) -> str:
        raise LookupError("render failed")

    monkeypatch.setattr(api, "Printer", tracked)
    if fail:
        monkeypatch.setattr(api.ranges, "splice", failing_splice)
    for _ in range(3):
        if fail:
            with pytest.raises(LookupError, match="render failed"):
                api.format_text(source, lines=(1, source.count("\n")))
        else:
            api.format_text(source, lines=(1, source.count("\n")))
    gc.collect()
    assert all(ref() is None for ref in refs)


def test_cli_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "a.chpl"
    p.write_text(SRC, encoding="utf-8")
    assert main(["--lines", "2:2", "a.chpl"]) == 0
    assert capsys.readouterr().out == fmt(SRC, 2, 2)
    assert main(["--check", "--lines", "2:2", "a.chpl"]) == 1
    assert main(["--check", "--lines", "7:7", "a.chpl"]) == 0
    assert main(["-i", "--lines", "2:2", "a.chpl"]) == 0
    assert p.read_text(encoding="utf-8") == fmt(SRC, 2, 2)
    assert main(["--check", "--lines", "2:2", "a.chpl"]) == 0
