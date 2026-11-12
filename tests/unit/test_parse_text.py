import os
from pathlib import Path
from typing import Any

import pytest

import corpus
from chplfmt import _chapel
from chplfmt._chapel import Diagnostic, chapel, parse_text

BAD = "var x = ;\nproc f( {\n"
REAL_CONTEXT = chapel.Context


def shape(asts: list[Any]) -> list[tuple[str, tuple[int, int], tuple[int, int]]]:
    out: list[tuple[str, tuple[int, int], tuple[int, int]]] = []
    for root in asts:
        for node in chapel.preorder(root):
            loc = node.location()
            out.append((type(node).__name__, loc.start(), loc.end()))
    return out


class NativeContext:
    """A Context with the future `parse_text(path, text)` API, emulated with a file
    written at the logical path itself."""

    def __init__(self) -> None:
        self._ctx = REAL_CONTEXT()
        self.calls: list[tuple[str, str]] = []

    def parse_text(self, path: str, text: str) -> list[Any]:
        self.calls.append((path, text))
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        return self._ctx.parse(path)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)


def test_valid_text() -> None:
    with parse_text("var x = 1;\n", "some/dir/foo.chpl") as res:
        assert res.diagnostics == []
        assert res.errors == []
        [mod] = res.asts
        assert isinstance(mod, chapel.Module)
        assert mod.name() == "foo"


def test_parse_errors_reported_against_logical_path() -> None:
    with parse_text(BAD, "src/bad.chpl") as res:
        diags = res.diagnostics
    assert [(d.path, d.line, d.col, d.message, d.kind) for d in diags] == [
        ("src/bad.chpl", 1, 9, "near ';'", "syntax"),
        ("src/bad.chpl", 2, 9, "near '{'", "syntax"),
    ]
    assert all(d.is_error for d in diags)
    assert str(diags[0]) == "src/bad.chpl:1:9: error: near ';'"
    assert diags[0].end_line == 1 and diags[0].end_col == 10


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("ChapelBase.chpl", "var x = ;\n"),
        ("other.chpl", "operator &&=(ref lhs: bool, rhs: bool) { }\n"),
    ],
)
def test_corpus_unexpected_parse_errors_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, text: str
) -> None:
    monkeypatch.setattr(corpus, "chpl_home", lambda: tmp_path)
    path = tmp_path / "modules/internal" / name
    path.parent.mkdir(parents=True)
    path.write_text(text)
    with (
        pytest.raises(pytest.fail.Exception, match="dyno reports 1 error"),
        corpus.parsed(path),
    ):
        pass


def test_warnings_are_not_errors() -> None:
    text = "module A { }\nmodule B { }\nvar y = 1;\n"
    with parse_text(text, "w.chpl") as res:
        assert res.diagnostics
        assert res.errors == []
        assert {d.kind for d in res.diagnostics} == {"warning"}
        assert str(res.diagnostics[0]).startswith("w.chpl:3:1: warning: ")


def test_text_is_written_unchanged() -> None:
    text = '\tvar x = 1;\r\nvar s = "\u00e9"; var y = 2;\r\n'
    with parse_text(text, "t.chpl") as res:
        starts = [loc for kind, loc, _ in shape(res.asts) if kind == "Variable"]
    assert starts == [(1, 2), (2, 1), (2, 15)]


def test_temp_file_lives_until_block_ends() -> None:
    with parse_text("var x = 1;\n", "keep.chpl") as res:
        [tmp] = res.ctx.introspect_parsed_files()
        assert os.path.basename(tmp) == "keep.chpl"
        assert os.path.exists(tmp)
        assert res.ctx.get_file_text(tmp) == "var x = 1;\n"
    assert not os.path.exists(tmp)


def test_fresh_context_per_call() -> None:
    with (
        parse_text("var x = 1;\n", "a.chpl") as a,
        parse_text("var x;\n", "a.chpl") as b,
    ):
        assert a.ctx is not b.ctx


def test_undecodable_message_does_not_crash() -> None:
    with parse_text("var \u00e9 = 1;\n", "u.chpl") as res:
        assert res.errors
        assert all(isinstance(d.message, str) for d in res.diagnostics)


def test_unknown_location_maps_to_logical_path() -> None:
    class Loc:
        def path(self) -> str:
            return ""

        def start(self) -> tuple[int, int]:
            return (-1, -1)

        def end(self) -> tuple[int, int]:
            return (-1, -1)

    class Err:
        def location(self) -> Loc:
            return Loc()

        def message(self) -> str:
            return "error reading file"

        def kind(self) -> str:
            return "error"

    [d] = _chapel.map_diagnostics([Err()], "x.chpl", "/tmp/x.chpl")  # type: ignore[list-item]
    assert d == Diagnostic("x.chpl", 0, 0, "error reading file", "error", 0, 0)
    assert str(d) == "x.chpl: error: error reading file"


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("<stdin>", "stdin.chpl"),
        ("", "stdin.chpl"),
        ("dir/", "stdin.chpl"),
        ("a/b/MyMod.chpl", "MyMod.chpl"),
    ],
)
def test_parse_name(path: str, name: str) -> None:
    assert _chapel.parse_name(path) == name


def test_stdin_parses_under_safe_name() -> None:
    with parse_text("var x = 1;\nproc f( {\n", "<stdin>") as res:
        [tmp] = res.ctx.introspect_parsed_files()
        assert os.path.basename(tmp) == "stdin.chpl"
        assert [m.name() for m in res.asts if isinstance(m, chapel.Module)] == ["stdin"]
        assert {d.path for d in res.diagnostics} == {"<stdin>"}


def test_native_parse_text_gets_safe_name(tmp_path: Path) -> None:
    made: list[NativeContext] = []

    def factory() -> NativeContext:
        made.append(NativeContext())
        return made[-1]

    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(tmp_path)
        mp.setattr(_chapel.chapel, "Context", factory)
        with parse_text(BAD, "<stdin>") as res:
            paths = {d.path for d in res.diagnostics}
    assert [c.calls for c in made] == [[("stdin.chpl", BAD)]]
    assert paths == {"<stdin>"}


@pytest.mark.parametrize("text", ["var x = 1;\nproc f() { }\n", BAD, "\tvar y;\r\n"])
def test_native_parse_text_matches_temp_file(tmp_path: Path, text: str) -> None:
    logical = str(tmp_path / "same.chpl")
    made: list[NativeContext] = []

    def factory() -> NativeContext:
        made.append(NativeContext())
        return made[-1]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(_chapel.chapel, "Context", factory)
        with parse_text(text, logical) as res:
            native_diags = res.diagnostics
            native_shape = shape(res.asts)
    assert [c.calls for c in made] == [[(logical, text)]]

    os.remove(logical)
    with parse_text(text, logical) as res:
        temp_diags = res.diagnostics
        temp_shape = shape(res.asts)
    assert not os.path.exists(logical)
    assert temp_diags == native_diags
    assert temp_shape == native_shape
