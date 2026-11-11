from collections.abc import Callable
from typing import cast

import pytest

from chplfmt import _native as native
from chplfmt.doc import ir as reference
from chplfmt.doc.render import (
    _composite_width,
    _leaf_width,
)


def test_native_doc_metadata_and_dump() -> None:
    native_id = native.GroupId("quote's")
    reference_id = reference.GroupId("quote's")
    pairs = [
        (native.text("中"), reference.text("中")),
        (native.text("a\tb"), reference.text("a\tb")),
        (native.concat(), reference.concat()),
        (
            native.concat("a", native.softline, "b"),
            reference.concat("a", reference.softline, "b"),
        ),
        (native.group(native.hardline), reference.group(reference.hardline)),
        (
            native.group("a", id=native_id, should_break=True),
            reference.group("a", id=reference_id, should_break=True),
        ),
        (native.indent(native.hardline, 2), reference.indent(reference.hardline, 2)),
        (native.align(native.softline), reference.align(reference.softline)),
        (native.line, reference.line),
        (native.softline, reference.softline),
        (native.hardline, reference.hardline),
        (native.literalline, reference.literalline),
        (
            native.fill(["a", native.line, "b"], lazy=True),
            reference.fill(["a", reference.line, "b"], lazy=True),
        ),
        (
            native.if_break(native.hardline, "flat"),
            reference.if_break(reference.hardline, "flat"),
        ),
        (
            native.if_break("b", "f", group_id=native_id),
            reference.if_break("b", "f", group_id=reference_id),
        ),
        (
            native.line_suffix(native.hardline),
            reference.line_suffix(reference.hardline),
        ),
        (native.trailing_comment("// hi"), reference.trailing_comment("// hi")),
        (native.break_parent, reference.break_parent),
        (
            native.conditional_group([native.hardline, "a"], native.ALL_LINES),
            reference.conditional_group([reference.hardline, "a"], reference.ALL_LINES),
        ),
        (
            native.conditional_group([native.hardline], native.FIRST_LINE),
            reference.conditional_group([reference.hardline], reference.FIRST_LINE),
        ),
        (native.verbatim("x\ny", bol=True), reference.verbatim("x\ny", bol=True)),
        (
            native.column_text(lambda col: f"at {col}"),
            reference.column_text(lambda col: f"at {col}"),
        ),
        (native.suffix_break, reference.suffix_break),
        (native.on_render(lambda: None), reference.on_render(lambda: None)),
    ]
    for doc, expected in pairs:
        assert doc.forced == expected.forced
        if isinstance(
            expected,
            (
                reference.Concat,
                reference.Fill,
                reference.Group,
                reference.ConditionalGroup,
                reference.Indent,
                reference.Align,
                reference.IfBreak,
            ),
        ):
            expected_width = _composite_width(expected, {})
        else:
            expected_width = _leaf_width(expected, {})
        assert doc.flat_width == expected_width
        assert native.dump(doc) == reference.dump(expected)
        flattened = native.flatten(doc)
        reference_flat = reference.flatten(expected)
        assert (flattened is None) == (reference_flat is None)
        if flattened is not None and reference_flat is not None:
            assert native.dump(flattened) == reference.dump(
                reference_flat
            ), native.dump(doc)


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
    assert repr(native.GroupId("it's")) == repr(reference.GroupId("it's"))
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


def test_native_deep_drop() -> None:
    doc = native.text("x")
    for _ in range(20_000):
        doc = native.indent(doc, 2)
    del doc
