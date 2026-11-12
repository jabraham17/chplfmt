from collections.abc import Callable
from typing import cast

import pytest

from chplfmt import _native as native

pytestmark = pytest.mark.native


def test_native_doc_metadata_and_dump() -> None:
    native_id = native.GroupId("quote's")
    cases = [
        (native.text("中"), False, 2),
        (native.text("a\tb"), False, -1),
        (native.concat(), False, 0),
        (native.concat("a", native.softline, "b"), False, 2),
        (native.group(native.hardline), True, -1),
        (native.group("a", id=native_id, should_break=True), True, -1),
        (native.indent(native.hardline, 2), True, -1),
        (native.align(native.softline), False, 0),
        (native.line, False, 1),
        (native.softline, False, 0),
        (native.hardline, True, -1),
        (native.literalline, True, -1),
        (native.fill(["a", native.line, "b"], lazy=True), False, 3),
        (native.if_break(native.hardline, "flat"), False, 4),
        (native.if_break("b", "f", group_id=native_id), False, -1),
        (native.line_suffix(native.hardline), False, 0),
        (native.trailing_comment("// hi"), False, 0),
        (native.break_parent, True, -1),
        (native.conditional_group([native.hardline, "a"], native.ALL_LINES), False, -1),
        (native.conditional_group([native.hardline], native.FIRST_LINE), True, -1),
        (native.verbatim("x\ny", bol=True), False, -1),
        (native.column_text(lambda col: f"at {col}"), True, -1),
        (native.suffix_break, False, 0),
        (native.on_render(lambda: None), False, 0),
    ]
    for doc, forced, width in cases:
        assert doc.forced is forced, native.dump(doc)
        assert doc.flat_width == width, native.dump(doc)
        if width >= 0:
            assert native.flat_width(doc, 2) == width
        flattened = native.flatten(doc)
        assert (flattened is None) is forced, native.dump(doc)
        if flattened is not None:
            flattened_again = native.flatten(flattened)
            assert flattened_again is not None
            assert native.dump(flattened) == native.dump(flattened_again)


def test_native_doc_shape_and_identity() -> None:
    assert native.concat(native.line) is native.line
    assert native.concat("hi").kind is native.DocKind.TEXT
    doc = native.concat(native.line, native.fill(["a", "b"]))
    assert isinstance(doc.parts, tuple)
    assert doc.parts[0] is native.line
    assert doc.parts[1].unpack()[0][0].unpack() == ("a",)
    assert doc != doc.parts[0]
    ident = native.GroupId()
    assert ident != native.GroupId()
    assert ident.name == "g"
    assert repr(native.GroupId("it's")) == 'GroupId("it\'s")'
    assert native.Check.FIRST_LINE is native.FIRST_LINE
    assert native.EMPTY.kind is native.DocKind.TEXT


def test_native_doc_builder_errors_and_callbacks() -> None:
    with pytest.raises(ValueError, match=r"text\(\) must not contain a newline"):
        native.text("a\nb")
    with pytest.raises(ValueError, match="trailing comment must not contain a newline"):
        native.trailing_comment("//\n")
    with pytest.raises(ValueError, match="conditional_group needs at least one"):
        native.conditional_group([])
    with pytest.raises(TypeError):
        assert native.line.parts == ()
    with pytest.raises(TypeError):
        native.column_text(cast(Callable[[int], str], 1))

    def fail(_col: int) -> str:
        raise LookupError("callback failure")

    callback = native.column_text(fail)
    assert callback.unpack() == (fail,)
    with pytest.raises(LookupError, match="callback failure"):
        native.dump(callback)

    def fn() -> None:
        pass

    assert native.on_render(fn).unpack() == (fn,)


def test_nested_native_doc_unpack_preserves_callbacks() -> None:
    def make(col: int) -> str:
        return f"at {col}"

    def notify() -> None:
        pass

    doc = native.concat(
        native.group(native.column_text(make)), native.on_render(notify)
    )
    group_doc, render_doc = doc.unpack()[0]
    assert group_doc.unpack()[0].unpack() == (make,)
    assert render_doc.unpack() == (notify,)


def test_native_deep_drop() -> None:
    doc = native.text("x")
    for _ in range(20_000):
        doc = native.indent(doc, 2)
    del doc
