import time

import pytest

from chplfmt.config import FormatOptions
from chplfmt.doc import (
    ALL_LINES,
    FIRST_LINE,
    DocLike,
    GroupId,
    LineRecord,
    align,
    align_trailing_comments,
    break_parent,
    column_text,
    concat,
    conditional_group,
    dump,
    fill,
    flat_width,
    group,
    hardline,
    if_break,
    indent,
    line,
    line_suffix,
    literalline,
    on_render,
    render,
    softline,
    suffix_break,
    text,
    trailing_comment,
    verbatim,
)
from chplfmt.doc.render import _Printer  # pyright: ignore[reportPrivateUsage]


def r(doc: DocLike, n: int = 80, tab: int = 2, base: int = 0) -> str:
    return render(doc, FormatOptions(line_length=n, tab_size=tab), base).text


def test_on_render_runs_only_in_the_chosen_layout() -> None:
    calls: list[str] = []
    flat = concat("a", on_render(lambda: calls.append("flat")))
    broken = concat("a", hardline, on_render(lambda: calls.append("broken")))
    assert r(conditional_group([flat, broken], check=ALL_LINES), n=80) == "a"
    assert calls == ["flat"]


def test_flat_width() -> None:
    opts = FormatOptions(line_length=5)
    assert flat_width(group(concat("abc", line, "defgh")), opts) == 9
    assert flat_width(concat("a", hardline, "b"), opts) is None


# Builders shaped like the printer's (design section 7.7).


def bracket_list(
    open_: str, items: list[DocLike], close: str, trailing_comma: bool = False
) -> DocLike:
    # The comma belongs to the content so that fill measures it.
    parts: list[DocLike] = []
    for i, it in enumerate(items):
        if i:
            parts.append(line)
        parts.append(concat(it, ",") if i < len(items) - 1 else it)
    body = fill(parts)
    return group(
        conditional_group(
            [
                concat(open_, align(body), close),
                concat(
                    open_,
                    indent(
                        concat(softline, body, if_break("," if trailing_comma else "")),
                        2,
                    ),
                    softline,
                    close,
                ),
            ],
            ALL_LINES,
        )
    )


def chain(operands: list[DocLike], op: str) -> DocLike:
    parts: list[DocLike] = []
    for i, o in enumerate(operands):
        if i:
            parts.append(line)
        parts.append(concat(o, f" {op}") if i < len(operands) - 1 else o)
    return fill(parts)


def assign(lhs: str, rhs: DocLike) -> DocLike:
    return conditional_group(
        [concat(lhs, " = ", rhs), concat(lhs, " =", indent(concat(hardline, rhs), 2))],
        FIRST_LINE,
    )


def if_expr(cond: DocLike, a: str, b: str) -> DocLike:
    return group(concat("if ", align(concat(cond, line, "then ", a, line, "else ", b))))


def lines(*ls: str) -> str:
    return "\n".join(ls)


# Basic nodes


def test_text_and_concat() -> None:
    assert r(concat("a", text("b"), concat("c", "d"))) == "abcd"
    with pytest.raises(ValueError):
        text("a\nb")


def test_group_fits_at_exact_width() -> None:
    doc = group(concat("aaaa", line, "bbbb"))
    assert r(doc, 9) == "aaaa bbbb"
    assert r(doc, 8) == "aaaa\nbbbb"


def test_softline_and_indent() -> None:
    doc = group(concat("[", indent(concat(softline, "x"), 2), softline, "]"))
    assert r(doc, 3) == "[x]"
    assert r(doc, 2) == "[\n  x\n]"


def test_hardline_propagates_to_enclosing_groups() -> None:
    doc = group(concat("a", line, group(concat("b", hardline, "c"))))
    assert r(doc) == "a\nb\nc"
    assert r(group(concat("a", line, "b", break_parent))) == "a\nb"
    assert r(group(concat("a", line, "b"), should_break=True)) == "a\nb"


def test_indent_and_literalline() -> None:
    assert r(concat("x", indent(concat(hardline, "y"), 4))) == "x\n    y"
    doc = concat("x", indent(concat(hardline, "a", literalline, "b"), 4))
    assert r(doc) == "x\n    a\nb"


def test_align_to_start_column_and_nesting() -> None:
    doc = concat(
        "abc", align(concat("d", indent(concat(hardline, "e"), 2), hardline, "f"))
    )
    assert r(doc) == "abcd\n     e\n   f"
    doc = concat(
        "ab", align(concat("c", align(concat("d", hardline, "e")), hardline, "f"))
    )
    assert r(doc) == "abcd\n   e\n  f"
    doc = indent(concat("{", hardline, "x = ", align(concat("a", hardline, "b"))), 2)
    assert r(doc) == "{\n  x = a\n      b"


def test_trailing_whitespace_trimmed() -> None:
    assert r(concat("a  ", hardline, "b ")) == "a\nb"
    assert r(indent(concat("x", hardline, hardline, "y"), 2)) == "x\n\n  y"


def test_line_length_zero_is_unlimited() -> None:
    doc = group(concat("a" * 500, line, "b"))
    assert r(doc, 0) == "a" * 500 + " b"


def test_if_break_enclosing_group() -> None:
    doc = group(
        concat("[", indent(concat(softline, "a", if_break(",")), 2), softline, "]")
    )
    assert r(doc) == "[a]"
    assert r(doc, 2) == "[\n  a,\n]"


def test_if_break_with_group_id() -> None:
    g = GroupId("g")
    doc = concat(
        group(concat("aaaa", line, "bbbb"), id=g),
        if_break(" broken", " flat", group_id=g),
    )
    assert r(doc, 20) == "aaaa bbbb flat"
    assert r(doc, 9) == "aaaa\nbbbb broken"


def test_line_suffix_deferred_and_ignored_by_fits() -> None:
    assert r(concat("a", line_suffix(";"), "b", hardline, "c")) == "ab;\nc"
    doc = group(concat("aaaa", line_suffix(" // long comment"), line, "bbbb"))
    assert r(doc, 9) == "aaaa bbbb // long comment"


def test_trailing_comment_records_and_alignment() -> None:
    doc = concat(
        "var count = 1;",
        trailing_comment("// trailing comments in consecutive lines"),
        hardline,
        "var limit = 100;",
        trailing_comment("// are aligned"),
    )
    res = render(doc, FormatOptions())
    assert res.lines == [
        LineRecord("var count = 1;", "// trailing comments in consecutive lines"),
        LineRecord("var limit = 100;", "// are aligned"),
    ]
    assert res.text == lines(
        "var count = 1;   // trailing comments in consecutive lines",
        "var limit = 100; // are aligned",
    )


def test_trailing_comments_never_force_breaks() -> None:
    doc = concat(
        group(concat("f(a,", line, "b);")), trailing_comment("// " + "x" * 40), hardline
    )
    assert r(doc, 10) == "f(a, b); // " + "x" * 40 + "\n"


def test_comment_runs_end_at_blank_plain_and_verbatim_lines() -> None:
    recs = [
        LineRecord("a;", "// 1"),
        LineRecord("bbbb;", "// 2"),
        LineRecord(""),
        LineRecord("c;", "// 3"),
        LineRecord("dddd;"),
        LineRecord("e;", "// 4"),
        LineRecord("ffffffff;", "// 5", verbatim=True),
        LineRecord("g;", "// 6"),
    ]
    assert align_trailing_comments(recs, 80, 2) == [
        "a;    // 1",
        "bbbb; // 2",
        "",
        "c; // 3",
        "dddd;",
        "e; // 4",
        "ffffffff; // 5",
        "g; // 6",
    ]


def test_comment_run_split_when_alignment_overflows() -> None:
    recs = [
        LineRecord("x;", "// first comment"),
        LineRecord("longer_name = 1;", "// c2"),
        LineRecord("y = 2;", "// c3"),
        LineRecord("z;", "// " + "w" * 30),
    ]
    out = align_trailing_comments(recs, 24, 2)
    # The last comment overflows even with one space, so it doesn't split the run.
    assert out == [
        "x; // first comment",
        "longer_name = 1; // c2",
        "y = 2;           // c3",
        "z;               // " + "w" * 30,
    ]
    again = [
        LineRecord(c.rstrip(), "//" + m) for c, m in (s.split("//", 1) for s in out)
    ]
    assert align_trailing_comments(again, 24, 2) == out


def test_tab_stops_measured_from_absolute_column() -> None:
    doc = group(concat('"\t"', line, "x"))
    assert r(doc, 7, tab=4) == '"\t" x'
    assert r(doc, 6, tab=4) == '"\t"\nx'
    doc = group(concat("\tq", line, "x"))
    assert r(doc, 7, tab=4, base=3) == "   \tq x"
    assert r(doc, 6, tab=4, base=3) == "   \tq\n   x"


def test_indentation_never_uses_tabs() -> None:
    assert r(indent(concat("a", hardline, "b"), 8), tab=4) == "a\n        b"


def test_wide_chars() -> None:
    doc = group(concat("日本", line, "x"))
    assert r(doc, 6) == "日本 x"
    assert r(doc, 5) == "日本\nx"


def test_base_indent() -> None:
    doc = group(concat("aaaa", line, "bbbb"))
    assert r(doc, 13, base=4) == "    aaaa bbbb"
    assert r(doc, 12, base=4) == "    aaaa\n    bbbb"
    doc = concat("{", indent(concat(hardline, "x"), 2), hardline, "}")
    assert r(doc, base=4) == "    {\n      x\n    }"


def test_verbatim_byte_for_byte() -> None:
    doc = concat("a = ", verbatim("x  \t\r\n\t y \n"), "z  ", hardline, "w ")
    res = render(doc, FormatOptions())
    assert res.text == "a = x  \t\r\n\t y \nz\nw"
    assert [rec.verbatim for rec in res.lines] == [True, True, False, False]


def test_verbatim_lines_are_not_aligned() -> None:
    doc = concat(
        verbatim("x;\t "),
        trailing_comment("// v"),
        hardline,
        "longer;",
        trailing_comment("// a"),
    )
    assert r(doc) == "x;\t  // v\nlonger; // a"


def test_verbatim_bol_starts_at_column_zero() -> None:
    region = "  x  ;\n\ty;"
    # Indentation already emitted is dropped.
    doc = concat("{", indent(concat(hardline, verbatim(region, bol=True)), 2))
    assert r(doc) == "{\n" + region
    # Code before it on the line, or a pending suffix, gets a newline first.
    assert r(concat("a;", verbatim(region, bol=True))) == "a;\n" + region
    doc = concat("a;", trailing_comment("// c"), verbatim(region, bol=True))
    assert r(doc) == "a; // c\n" + region
    assert "verbatim bol" in dump(verbatim(region, bol=True))


def test_column_text_gets_its_start_column() -> None:
    def make(col: int) -> str:
        return f"/* at {col}\n{' ' * col}*/"

    doc = concat("ab", indent(concat(hardline, "x = ", column_text(make)), 2))
    assert r(doc) == "ab\n  x = /* at 6\n      */"
    # Forced: it breaks enclosing groups; fits measures its first line only.
    assert r(group(concat("a", line, column_text(make)))) == "a\n/* at 0\n*/"
    assert "column_text" in dump(column_text(make))


def test_suffix_break_only_with_pending_suffix() -> None:
    doc = group(concat("f(a,", line, suffix_break, "b)"))
    assert r(doc) == "f(a, b)"
    doc = group(concat("f(a,", trailing_comment("// c"), line, suffix_break, "b)"))
    assert r(doc) == "f(a, // c\nb)"
    assert dump(suffix_break) == "suffix_break"


# fill


def test_fill_bin_packs() -> None:
    doc = fill(["aa", line, "bb", line, "cc", line, "dd"])
    assert r(doc, 8) == "aa bb cc\ndd"
    assert r(doc, 5) == "aa bb\ncc dd"
    assert r(doc, 1) == "aa\nbb\ncc\ndd"


def test_fill_measures_last_item_with_following_text() -> None:
    def proc(n: int) -> str:
        doc = concat(
            "f(",
            align(fill(["a,", line, "b,", line, "c"])),
            "): real throws {",
            indent(concat(hardline, "body;"), 2),
            hardline,
            "}",
        )
        return r(doc, n)

    assert proc(25) == "f(a, b, c): real throws {\n  body;\n}"
    assert proc(24) == "f(a, b,\n  c): real throws {\n  body;\n}"


# conditional_group


def test_conditional_group_flat_first() -> None:
    doc = conditional_group([concat("a", line, "b"), "zzz"])
    assert r(doc) == "a b"


def test_conditional_group_first_line_vs_all_lines() -> None:
    alts: list[DocLike] = [
        concat("aaa", hardline, "b" * 30),
        concat("ccc", hardline, "dd"),
    ]
    assert r(conditional_group(alts, FIRST_LINE), 20) == "aaa\n" + "b" * 30
    assert r(conditional_group(alts, ALL_LINES), 20) == "ccc\ndd"


def test_conditional_group_falls_back_to_last() -> None:
    for check in (FIRST_LINE, ALL_LINES):
        assert r(conditional_group(["x" * 30, "y" * 30], check), 20) == "y" * 30


def test_conditional_group_all_lines_counts_following_text() -> None:
    doc = concat(bracket_list("f(", ["aaaa", "bbbb"], ")"), ";;;;;;")
    assert r(doc, 13) == "f(aaaa,\n  bbbb);;;;;;"
    assert r(doc, 12) == "f(\n  aaaa, bbbb\n);;;;;;"


def test_conditional_group_alternative_hardline_does_not_force_parents() -> None:
    assert r(group(concat("a", line, assign("x", "y")))) == "a x = y"
    forced = conditional_group([concat("a", hardline, "b"), concat("c", hardline, "d")])
    assert r(group(concat("p", line, forced))) == "p\na\nb"


def test_conditional_group_memoized(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    real = _Printer._all_lines_fit  # pyright: ignore[reportPrivateUsage]

    def counting(*args: object) -> bool:
        nonlocal calls
        calls += 1
        return real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(_Printer, "_all_lines_fit", counting)

    def nest(k: int) -> DocLike:
        if k == 0:
            return "leafArgumentValue"
        return bracket_list("someFunction(", [nest(k - 1), "otherArgument"], ")")

    start = time.perf_counter()
    out = r(nest(25))
    assert time.perf_counter() - start < 1.0
    assert calls < 500
    assert max(len(s) for s in out.split("\n")) <= 80


# Layouts from design section 8


def test_section_8_4_lists() -> None:
    doc = concat(
        "var ",
        assign("x", bracket_list("foo(", ["alpha", "beta", "gamma"], ")")),
        ";",
        hardline,
        "var ",
        assign(
            "y",
            bracket_list(
                "someFunction(",
                [
                    "firstValue",
                    "secondValue",
                    "thirdValue",
                    "fourthValue",
                    "fifthValue",
                ],
                ")",
            ),
        ),
        ";",
        hardline,
        "var ",
        assign(
            "z",
            bracket_list(
                "aVeryLongFunctionNameThatPushesTheOpenBracketVeryFarRight(",
                ["firstArgumentValue", "secondArgumentValue"],
                ")",
            ),
        ),
        ";",
        hardline,
        "const ",
        assign(
            "messages",
            bracket_list(
                "[",
                [
                    '"the first message in the list"',
                    '"the second message"',
                    '"a third message that is quite a bit longer than all the others"',
                ],
                "]",
                trailing_comma=True,
            ),
        ),
        ";",
    )
    assert r(doc) == lines(
        "var x = foo(alpha, beta, gamma);",
        "var y = someFunction(firstValue, secondValue, thirdValue, fourthValue,",
        "                     fifthValue);",
        "var z = aVeryLongFunctionNameThatPushesTheOpenBracketVeryFarRight(",
        "  firstArgumentValue, secondArgumentValue",
        ");",
        "const messages = [",
        '  "the first message in the list", "the second message",',
        '  "a third message that is quite a bit longer than all the others",',
        "];",
    )


def test_section_8_5_operators() -> None:
    total = concat(
        "const total = ",
        align(
            chain(
                [
                    group(chain(["firstValue", "scaleFactor"], "*")),
                    group(chain(["secondValue", "otherScale"], "*")),
                    group(chain(["thirdValue", "lastScale"], "*")),
                ],
                "+",
            )
        ),
        ";",
    )
    cond = chain(
        [
            "isValid(index)",
            "index < limit",
            "!visited[index]",
            "index != sentinelValue",
        ],
        "&&",
    )
    if_stmt = concat(
        "if ",
        align(cond),
        " {",
        indent(
            concat(hardline, "visited[index] = true;", hardline, "visit(index);"), 2
        ),
        hardline,
        "}",
    )
    scales = chain([f"scale == {k}" for k in (0, 1, 2, 4, 8, 16, 32)], "||")
    if_then = concat(
        "if !(",
        align(scales),
        ") then",
        indent(concat(hardline, 'halt("bad scale");'), 2),
    )
    doc = concat(total, hardline, hardline, if_stmt, hardline, hardline, if_then)
    assert r(doc) == lines(
        "const total = firstValue * scaleFactor + secondValue * otherScale +",
        "              thirdValue * lastScale;",
        "",
        "if isValid(index) && index < limit && !visited[index] &&",
        "   index != sentinelValue {",
        "  visited[index] = true;",
        "  visit(index);",
        "}",
        "",
        "if !(scale == 0 || scale == 1 || scale == 2 || scale == 4 || scale == 8 ||",
        "     scale == 16 || scale == 32) then",
        '  halt("bad scale");',
    )


def test_section_8_6_formals_with_return_type() -> None:
    formals = bracket_list(
        "proc scale(",
        ["ref A: [?D] real", "alpha: real", "beta: real", "gamma: real", "delta: real"],
        ")",
    )
    doc = concat(
        formals,
        ": real throws {",
        indent(concat(hardline, "A *= alpha;", hardline, "return beta;"), 2),
        hardline,
        "}",
    )
    assert r(doc) == lines(
        "proc scale(ref A: [?D] real, alpha: real, beta: real, gamma: real,",
        "           delta: real): real throws {",
        "  A *= alpha;",
        "  return beta;",
        "}",
    )


def test_section_8_9_if_expression() -> None:
    cond = bracket_list("someLongConditionExpression(", ["withArguments"], ")")
    doc = concat(
        "const y = ",
        align(if_expr("cond", "a", "b")),
        ";",
        hardline,
        "const z = ",
        align(if_expr(cond, "firstAlternative", "secondAlternative")),
        ";",
    )
    assert r(doc) == lines(
        "const y = if cond then a else b;",
        "const z = if someLongConditionExpression(withArguments)",
        "             then firstAlternative",
        "             else secondAlternative;",
    )


def test_dump() -> None:
    g = GroupId("g1")
    doc = group(concat("a", line, if_break(",", "", group_id=g)), id=g)
    assert dump(doc) == lines(
        "group id=g1",
        "  concat",
        "    text 'a'",
        "    line",
        "    if_break id=g1",
        "      broken:",
        "        text ','",
        "      flat:",
        "        text ''",
    )


def test_large_document_renders_quickly() -> None:
    stmts: list[DocLike] = []
    for i in range(5000):
        call = bracket_list(f"compute{i}(", [f"alpha{i}", f"beta{i}", f"gamma{i}"], ")")
        rhs = align(chain([call, f"offset{i}", f"scale{i}"], "+"))
        stmts.append(
            concat("var ", assign(f"v{i}", rhs), ";", trailing_comment("// c"))
        )
        stmts.append(hardline)
    doc = concat(*stmts)
    start = time.perf_counter()
    out = r(doc)
    assert time.perf_counter() - start < 1.0
    assert out.count("\n") >= 5000
