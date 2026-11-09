import pytest

from chplfmt.source import (
    SourceDecodeError,
    SourceText,
    char_width,
    display_width,
)


def test_immutable() -> None:
    src = SourceText.from_text("a\n")
    with pytest.raises(AttributeError):
        src.text = "b"  # type: ignore[misc]


def test_invalid_utf8_is_an_error() -> None:
    with pytest.raises(SourceDecodeError) as info:
        SourceText.from_bytes(b"var x;\nvar \xff = 1;\n")
    assert (info.value.line, info.value.byte_col) == (2, 5)


def test_from_bytes_keeps_bytes() -> None:
    data = "var s = '\u00e9';\r\n".encode()
    src = SourceText.from_bytes(data)
    assert src.data == data
    assert src.text == data.decode()
    assert src.uses_crlf


def test_lines_lf_and_crlf() -> None:
    src = SourceText.from_text("ab\r\ncd\n\nef")
    assert src.line_count == 4
    assert src.line_starts == (0, 4, 7, 8)
    assert [src.line_text(n) for n in range(1, 5)] == ["ab", "cd", "", "ef"]
    assert src.line_end(1) == 2  # before "\r\n"
    assert src.line_end(4) == len(src.text)
    # A lone '\r' is not a line break (dyno only counts '\n').
    assert SourceText.from_text("a\rb\n").line_count == 2


def test_trailing_newline_makes_an_empty_last_line() -> None:
    src = SourceText.from_text("x\n")
    assert src.line_count == 2
    assert src.line_text(2) == ""
    assert src.pos(2) == (2, 1)


def test_pos_and_offset_ascii_and_tabs() -> None:
    src = SourceText.from_text("\tvar x;\nfoo\n")
    assert src.pos(0) == (1, 1)
    assert src.pos(1) == (1, 2)  # a tab is one byte column
    assert src.pos(8) == (2, 1)
    for off in range(len(src.text) + 1):
        assert src.offset(src.pos(off)) == off


def test_pos_and_offset_utf8() -> None:
    text = 'var s = "\u00e9\u4e2d"; var y;\n\U0001f600x\n'
    src = SourceText.from_text(text)
    assert src.pos(text.index("var y")) == (1, 18)
    assert src.pos(text.index("x")) == (2, 5)
    for off in range(len(text) + 1):
        assert src.offset(src.pos(off)) == off
    with pytest.raises(ValueError, match="inside a character"):
        src.offset((1, 11))


def test_offset_out_of_range() -> None:
    src = SourceText.from_text("ab\ncd")
    assert src.offset((1, 3)) == 2  # the '\n' itself
    assert src.offset((2, 3)) == 5  # EOF
    for bad in [(1, 4), (2, 4), (3, 1), (0, 1), (1, 0)]:
        with pytest.raises(ValueError):
            src.offset(bad)


def test_char_width() -> None:
    assert char_width("a") == 1
    assert char_width("\u00e9") == 1
    assert char_width("\u4e2d") == 2
    assert char_width("\uff21") == 2  # fullwidth A
    assert char_width("\U0001f600") == 2


def test_display_width_tab_stops() -> None:
    assert display_width("abc") == 3
    assert display_width("\t", 0, 4) == 4
    assert display_width("a\t", 0, 4) == 4
    assert display_width("\t", 3, 4) == 4
    assert display_width("\t", 4, 4) == 8
    assert display_width("a\tb", 0, 2) == 3
    assert display_width("\u4e2d\t", 0, 4) == 4
    assert display_width("ab\ncd") == 2


def test_display_column() -> None:
    src = SourceText.from_text("x\n\t\u4e2dy = 1\n")
    y = src.text.index("y")
    assert src.display_column(y) == 4  # tab to 2, wide char 2
    assert src.display_column(y, tab_size=8) == 10
    assert src.display_column(0) == 0
