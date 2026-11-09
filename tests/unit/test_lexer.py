import pytest

from chplfmt._chapel import chapel, parse_text
from chplfmt.lexer import (
    PUNCTUATION,
    LexError,
    Token,
    TokenKind,
    check_invariants,
    format_tokens,
    tokenize,
)
from chplfmt.source import SourceText

K = TokenKind


def lex(text: str, opaque: list[tuple[int, int]] | None = None) -> list[Token]:
    src = SourceText.from_text(text)
    tokens = tokenize(src, opaque or [])
    assert check_invariants(src, tokens) == []
    assert tokens[-1].kind is K.EOF
    return tokens


def pairs(text: str) -> list[tuple[TokenKind, str]]:
    return [(t.kind, t.text) for t in lex(text)[:-1]]


def texts(text: str) -> list[str]:
    return [t.text for t in lex(text)[:-1]]


def dyno_leaves(text: str) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
    """(class name, start, end) of every Identifier and literal dyno reports."""
    with parse_text(text, "t.chpl") as r:
        assert r.errors == []
        return [
            (type(n).__name__, n.location().start(), n.location().end())
            for root in r.asts
            for n in chapel.preorder(root)
            if isinstance(n, chapel.Identifier | chapel.Literal)
        ]


def assert_leaves_are_tokens(text: str) -> None:
    tokens = lex(text)
    spans = {(t.start, t.end) for t in tokens}
    leaves = dyno_leaves(text)
    assert leaves
    for name, start, end in leaves:
        assert (start, end) in spans, (name, start, end)


# Round trip and whitespace


@pytest.mark.parametrize(
    "text",
    [
        "",
        "\n",
        "  \t\n",
        "var x = 1;",
        "var x = 1;\n",
        "proc f(a: int, b) {\n\treturn a + b; // sum\n}\n\n",
        "/* c */\r\nvar s = '''x\r\ny''';\r\n",
        "x\f;\n",
    ],
)
def test_round_trip(text: str) -> None:
    tokens = lex(text)
    rebuilt = ""
    pos = 0
    for t in tokens:
        gap = text[pos : t.start_offset]
        assert set(gap) <= set(" \t\r\n\f")
        rebuilt += gap + t.text
        pos = t.end_offset
    assert rebuilt == text


def test_empty_input_is_just_eof() -> None:
    (eof,) = lex("")
    assert (eof.kind, eof.start, eof.end, eof.nl_before, eof.ws_before) == (
        K.EOF,
        (1, 1),
        (1, 1),
        0,
        False,
    )


def test_nl_before_and_ws_before() -> None:
    tokens = lex("a b\n\n  c\td\n")
    assert [(t.text, t.nl_before, t.ws_before) for t in tokens] == [
        ("a", 0, False),
        ("b", 0, True),
        ("c", 2, True),
        ("d", 0, True),
        ("", 1, True),
    ]
    assert not lex("a(b)")[1].ws_before


# Identifiers


def test_identifiers() -> None:
    assert pairs("x _y z9 proc forall") == [
        (K.IDENT, "x"),
        (K.IDENT, "_y"),
        (K.IDENT, "z9"),
        (K.IDENT, "proc"),
        (K.IDENT, "forall"),
    ]


def test_dollar_is_not_an_identifier_character() -> None:
    with pytest.raises(LexError, match="invalid character"):
        lex("x$y")


def test_non_ascii_outside_strings_is_invalid() -> None:
    with pytest.raises(LexError, match=r"1:5: invalid character"):
        lex("var \u00e9 = 1;")


def test_glued_tokens() -> None:
    # dyno lexes these as single tokens; `proc(` is split since `(` must match.
    assert texts("try! f(); proc init=(x) {} x reduce= y; proc(x)") == [
        *("try!", "f", "(", ")", ";"),
        *("proc", "init=", "(", "x", ")", "{", "}"),
        *("x", "reduce=", "y", ";"),
        *("proc", "(", "x", ")"),
    ]
    assert texts("try !x; init = 1; tryX!") == [
        *("try", "!", "x", ";", "init", "=", "1", ";", "tryX", "!"),
    ]


def test_query_and_attribute_identifiers() -> None:
    assert texts("proc f(x: ?t) where t == int?") == [
        *("proc", "f", "(", "x", ":", "?t", ")", "where", "t", "==", "int", "?"),
    ]
    assert texts('@chplcheck.ignore("x") @ x') == [
        *("@chplcheck", ".", "ignore", "(", '"x"', ")", "@", "x"),
    ]


# Numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1..n", ["1", "..", "n"]),
        ("0..<n", ["0", "..<", "n"]),
        ("1...2", ["1", "...", "2"]),
        ("1.foo", ["1", ".", "foo"]),
        ("1.e3", ["1.e3"]),
        ("1.exp", ["1", ".", "exp"]),
        ("1.5e", ["1.5", "e"]),
        ("1.0", ["1.0"]),
        (".5", [".5"]),
        ("1..5", ["1", "..", "5"]),
        ("1e-3", ["1e-3"]),
        ("1E+3", ["1E+3"]),
        ("1_000", ["1_000"]),
        ("1_", ["1_"]),
        ("0b1010", ["0b1010"]),
        ("0B1_0", ["0B1_0"]),
        ("0b12", ["0b1", "2"]),
        ("0o17", ["0o17"]),
        ("0O7", ["0O7"]),
        ("0x1F", ["0x1F"]),
        ("0x1p3", ["0x1p3"]),
        ("0x1e3", ["0x1e3"]),
        ("0x.8p-1", ["0x.8p-1"]),
        ("0x1.8p3", ["0x1.8p3"]),
        ("0x1.p3", ["0x1.p3"]),
        ("0x", ["0", "x"]),
        ("2.5i", ["2.5i"]),
        ("1i", ["1i"]),
        ("0xAp-2i", ["0xAp-2i"]),
        ("1.0E+3i", ["1.0E+3i"]),
    ],
)
def test_numbers(text: str, expected: list[str]) -> None:
    tokens = lex(text)[:-1]
    assert [t.text for t in tokens] == expected
    assert tokens[0].kind is K.NUMBER


def test_number_locations_match_dyno() -> None:
    assert_leaves_are_tokens(
        "var a = .5 + 1.e3 + 2.5i + 1i + 0x1p3 + 0x.8p1 + 1_000 + 0b1010"
        " + 0o17 + 1e-3;\nfor i in 1..10 do; var z = 1..<5;\nvar w = 1.0;\n"
    )


# Strings


@pytest.mark.parametrize(
    "text",
    [
        '"abc"',
        "'abc'",
        '""',
        '"a\\"b"',
        "'a\\'b'",
        '"a\\\\"',
        '"\\x41\\n\\t"',
        '"a\\\nb"',
        'b"bytes"',
        "b'bytes'",
        '"""a\n"b"\n\'\'c"""',
        "'''a\nb'''",
        'b"""x"""',
        '"""a\\"""',
        '""""""',
        '"// not a comment"',
        '"/* nor this"',
    ],
)
def test_strings(text: str) -> None:
    assert pairs(text + ";") == [(K.STRING, text), (K.PUNCT, ";")]


def test_triple_quote_ends_at_first_closing_triple() -> None:
    assert texts('"""a"""" "') == ['"""a"""', '" "']


def test_string_prefixes() -> None:
    # `c"..."` isn't a literal (dyno rejects it); it lexes as `c` and a string.
    assert pairs('c"z" bx"y"') == [
        (K.IDENT, "c"),
        (K.STRING, '"z"'),
        (K.IDENT, "bx"),
        (K.STRING, '"y"'),
    ]


def test_string_locations_match_dyno() -> None:
    assert_leaves_are_tokens(
        'var a = b"x\\"y" + \'q\' + """x\ny""";\n'
        "var b = '''x\ny''' + 'a\\'b' + \"x\\\ny\";\n"
    )


@pytest.mark.parametrize("text", ['"abc', "'abc", '"""abc""', "b'x"])
def test_unterminated_string(text: str) -> None:
    with pytest.raises(LexError, match="unterminated string"):
        lex(text)


# Comments


def test_line_comments() -> None:
    assert pairs("x // c1\n// c2\r\ny //") == [
        (K.IDENT, "x"),
        (K.LINE_COMMENT, "// c1"),
        (K.LINE_COMMENT, "// c2"),
        (K.IDENT, "y"),
        (K.LINE_COMMENT, "//"),
    ]
    assert lex("x // c1\n")[1].is_comment


@pytest.mark.parametrize(
    ("text", "comment"),
    [
        ("/* a */ x", "/* a */"),
        ("/**/ x", "/**/"),
        ("/***/ x", "/***/"),
        ("/* a /* b */ c */ x", "/* a /* b */ c */"),
        ("/* /* /* */ */ */ x", "/* /* /* */ */ */"),
        ("/*/ x */ x", "/*/ x */"),
        ("/* a\n b\n*/ x", "/* a\n b\n*/"),
        ("/* // */ x", "/* // */"),
        ("/* a //*/ */ */ x", "/* a //*/ */ */"),
    ],
)
def test_block_comments(text: str, comment: str) -> None:
    assert pairs(text) == [(K.BLOCK_COMMENT, comment), (K.IDENT, "x")]


def test_comments_match_dyno() -> None:
    assert_leaves_are_tokens("/* a /* b */ c */ x;\n/*/ y */ z;\nw/**/;\n")


@pytest.mark.parametrize("text", ["/* a", "/* a /* b */", "/*/"])
def test_unterminated_block_comment(text: str) -> None:
    with pytest.raises(LexError, match="unterminated block comment"):
        lex(text)


# Punctuation and brackets


def test_longest_match_punctuation() -> None:
    ops = sorted(p for p in PUNCTUATION if p not in "()[]{}")
    text = " ".join(ops)
    assert pairs(text) == [(K.PUNCT, op) for op in ops]
    assert texts("a<=>b<<=c**=d..<e...f=>g&&=h||=i>>=j") == [
        *("a", "<=>", "b", "<<=", "c", "**=", "d", "..<", "e", "...", "f", "=>"),
        *("g", "&&=", "h", "||=", "i", ">>=", "j"),
    ]
    assert texts("a<~>b") == ["a", "<", "~", ">", "b"]
    assert texts("x=-1") == ["x", "=", "-", "1"]


def test_bracket_matching() -> None:
    tokens = lex("f(a[i], {b, (c)})")
    pairs_found = {
        (tokens[i].text, tokens[t.match].text, i < t.match)
        for i, t in enumerate(tokens)
        if t.match is not None
    }
    assert pairs_found == {
        ("(", ")", True),
        (")", "(", False),
        ("[", "]", True),
        ("]", "[", False),
        ("{", "}", True),
        ("}", "{", False),
    }
    assert {i: t.match for i, t in enumerate(tokens) if t.match is not None} == {
        **{1: 14, 14: 1, 3: 5, 5: 3},
        **{7: 13, 13: 7, 10: 12, 12: 10},
    }
    brackets_in_strings = lex('f("(", \'[\', /* { */ ")")')
    assert brackets_in_strings[1].match == len(brackets_in_strings) - 2


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("f(]", r"1:3: unmatched '\]'"),
        ("f)", r"1:2: unmatched '\)'"),
        ("{\n(", r"2:1: unmatched '\('"),
        ("a[{]}", r"1:4: unmatched '\]'"),
    ],
)
def test_bracket_mismatch_is_an_error(text: str, message: str) -> None:
    with pytest.raises(LexError, match=message):
        lex(text)


# Line endings, tabs, and UTF-8


def test_crlf() -> None:
    text = "var x = 1; // c\r\n/* a\r\nb */\r\nvar s = '''p\r\nq''';\r\n"
    tokens = lex(text)
    comments = [t.text for t in tokens if t.is_comment]
    assert comments == ["// c", "/* a\r\nb */"]
    strings = [t for t in tokens if t.kind is K.STRING]
    assert strings[0].text == "'''p\r\nq'''"
    assert (strings[0].start, strings[0].end) == ((4, 9), (5, 5))
    assert [t.nl_before for t in tokens if t.nl_before] == [1, 1, 1]
    assert_leaves_are_tokens(text)


def test_tabs_are_one_byte_column() -> None:
    text = "var a\t=\t3;\n\tf(\tb);\n"
    tokens = lex(text)
    assert [(t.text, t.start) for t in tokens if t.text in ("3", "f", "b")] == [
        ("3", (1, 9)),
        ("f", (2, 2)),
        ("b", (2, 5)),
    ]
    assert_leaves_are_tokens(text)


def test_utf8_byte_columns() -> None:
    text = 'var s = "\u00e9\u4e2d"; y;\nf("\U0001f600", x); /* \u00e9 */ z;\n'
    tokens = lex(text)
    by_text = {t.text: t for t in tokens}
    assert (by_text['"\u00e9\u4e2d"'].start, by_text['"\u00e9\u4e2d"'].end) == (
        (1, 9),
        (1, 16),
    )
    assert by_text["y"].start == (1, 18)
    assert by_text["x"].start == (2, 11)
    assert by_text["z"].start == (2, 24)
    assert_leaves_are_tokens(text)


# OPAQUE extern blocks


def test_extern_block_is_opaque() -> None:
    text = 'extern {\n  int f(void) { return "}"; } /* ( */\n}\nvar x = (1);\n'
    end = text.index("}\nvar") + 1
    tokens = lex(text, [(0, end)])
    assert [(t.kind, t.text) for t in tokens[:2]] == [
        (K.OPAQUE, text[:end]),
        (K.IDENT, "var"),
    ]
    assert tokens[0].end == (3, 2)
    assert tokens[1].nl_before == 1
    with parse_text(text, "t.chpl") as r:
        (block,) = [
            n for n in chapel.preorder(r.asts[0]) if isinstance(n, chapel.ExternBlock)
        ]
        loc = block.location()
        assert (loc.start(), loc.end()) == (tokens[0].start, tokens[0].end)


def test_extern_block_without_opaque_range_fails() -> None:
    with pytest.raises(LexError, match="unmatched"):
        lex("extern {\n#define LB {\n}\n")


@pytest.mark.parametrize(
    ("ranges", "message"),
    [
        ([(1, 3)], "inside a token"),
        ([(4, 6)], "outside the text"),
    ],
)
def test_bad_opaque_ranges(ranges: list[tuple[int, int]], message: str) -> None:
    with pytest.raises(LexError, match=message):
        lex("abc", ranges)


# Debug output


def test_format_tokens() -> None:
    assert format_tokens(lex("f(x)\n  // c\n")) == (
        "0 IDENT 1:1-1:2 'f'\n"
        "1 PUNCT 1:2-1:3 match=3 '('\n"
        "2 IDENT 1:3-1:4 'x'\n"
        "3 PUNCT 1:4-1:5 match=1 ')'\n"
        "4 LINE_COMMENT 2:3-2:7 nl=1 '// c'\n"
        "5 EOF 3:1-3:1 nl=1 ''\n"
    )
