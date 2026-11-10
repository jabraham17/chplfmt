import os
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from chplfmt import __version__, api
from chplfmt.cli import is_skipped, main, unified_diff

GOOD = "var x = 1;\n"
BAD = "var x = ;\n"


@pytest.fixture(autouse=True)
def in_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(path: str, text: str = GOOD) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture
def uppercase(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the identity formatter with one that changes 'var' to 'const'."""
    real = api.format_text

    def fake(text: str, **kwargs: Any) -> api.FormatResult:
        real(text, **kwargs)
        out = text.replace("var ", "const ")
        return api.FormatResult(out, out != text, api.compute_edits(text, out))

    monkeypatch.setattr(api, "format_text", fake)


def test_stdin_to_stdout(set_stdin: Callable[[bytes], None], capsys: Any) -> None:
    set_stdin(b"var x = 1;\r\nproc f() { }\n")
    assert main(["-"]) == 0
    assert capsys.readouterr().out == "var x = 1;\nproc f() { }\n"


def test_stdin_parse_error(set_stdin: Callable[[bytes], None], capsys: Any) -> None:
    set_stdin(BAD.encode())
    assert main(["-"]) == 3
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "<stdin>:1:9: error: near ';'\n"


def test_stdin_filename(set_stdin: Callable[[bytes], None], capsys: Any) -> None:
    set_stdin(BAD.encode())
    assert main(["-", "--stdin-filename", "src/foo.chpl"]) == 3
    assert capsys.readouterr().err == "src/foo.chpl:1:9: error: near ';'\n"


def test_stdin_filename_is_used_for_skip(
    set_stdin: Callable[[bytes], None], capsys: Any
) -> None:
    set_stdin(BAD.encode())
    assert main(["-", "--stdin-filename", "gen/foo.chpl", "--skip", "gen"]) == 0
    assert capsys.readouterr() == ("", "")


def test_multiple_files_are_concatenated(capsys: Any) -> None:
    write("b.chpl", "var b = 2;\n")
    write("a.chpl", "var a = 1;\n")
    assert main(["b.chpl", "a.chpl", "--file", "b.chpl"]) == 0
    assert capsys.readouterr().out == "var b = 2;\nvar a = 1;\n"


def test_recursive_glob(capsys: Any) -> None:
    write("src/b.chpl", "var b;\n")
    write("src/sub/a.chpl", "var a;\n")
    write("src/notes.txt", "x")
    assert main(["src/**/*.chpl"]) == 0
    assert capsys.readouterr().out == "var b;\nvar a;\n"


def test_directory_is_usage_error(capsys: Any) -> None:
    os.mkdir("src")
    write("a.chpl")
    assert main(["a.chpl", "src"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "'src' is a directory" in captured.err
    assert "src/**/*.chpl" in captured.err


def test_in_place_with_stdin_is_usage_error(capsys: Any) -> None:
    assert main(["-i", "-"]) == 2
    assert "-i/--in-place cannot be used with '-'" in capsys.readouterr().err


def test_no_inputs(capsys: Any) -> None:
    assert main([]) == 2
    assert "no input files" in capsys.readouterr().err


def test_check_unchanged(capsys: Any) -> None:
    write("a.chpl")
    assert main(["--check", "a.chpl"]) == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.usefixtures("uppercase")
def test_check_changed(capsys: Any) -> None:
    write("a.chpl", "var a = 1;\n")
    write("b.chpl", "const b = 1;\n")
    assert main(["--check", "a.chpl", "b.chpl"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "would reformat a.chpl\n"
    assert Path("a.chpl").read_text() == "var a = 1;\n"


@pytest.mark.usefixtures("uppercase")
def test_check_verbose(capsys: Any) -> None:
    write("a.chpl", "var a = 1;\nproc f() { }\nvar b;\nvar c;\n")
    assert main(["--check", "-v", "a.chpl"]) == 1
    err = capsys.readouterr().err
    assert err == "would reformat a.chpl\n  changed lines: 1, 3-4\n"


def test_check_verbose_rule_counts(capsys: Any) -> None:
    write(
        "a.chpl",
        "//x\nvar a = (1);;\nvar t = (1, 2,);\nif a then { f(); }\n"
        "x = ((a + 1)) * 2;\n",
    )
    assert main(["--check", "-v", "a.chpl"]) == 1
    assert capsys.readouterr().err == (
        "would reformat a.chpl\n"
        "  changed lines: 1-5\n"
        "  rule applications: comment-spacing: 1, remove-empty-statements: 1, "
        "remove-redundant-parens: 2, single-statement-body: 1, trailing-comma: 1\n"
    )


@pytest.mark.usefixtures("uppercase")
def test_diff(capsys: Any) -> None:
    write("a.chpl", "var a = 1;\n")
    assert main(["--diff", "a.chpl"]) == 0
    out = capsys.readouterr().out
    assert out == (
        "--- a.chpl\t(original)\n+++ a.chpl\t(formatted)\n"
        "@@ -1 +1 @@\n-var a = 1;\n+const a = 1;\n"
    )


@pytest.mark.usefixtures("uppercase")
def test_check_and_diff(capsys: Any) -> None:
    write("a.chpl", "var a = 1;\n")
    assert main(["--check", "--diff", "a.chpl"]) == 1
    captured = capsys.readouterr()
    assert "+const a = 1;" in captured.out
    assert captured.err == "would reformat a.chpl\n"


@pytest.mark.usefixtures("uppercase")
def test_in_place(capsys: Any) -> None:
    p = write("a.chpl", "var a = 1;\n")
    p.chmod(0o640)
    write("b.chpl", "const b;\n")
    assert main(["-i", "a.chpl", "b.chpl"]) == 0
    assert capsys.readouterr() == ("", "")
    assert p.read_text() == "const a = 1;\n"
    assert stat.S_IMODE(p.stat().st_mode) == 0o640
    assert sorted(os.listdir()) == ["a.chpl", "b.chpl"]


@pytest.mark.usefixtures("uppercase")
def test_in_place_leaves_parse_errors_untouched(capsys: Any) -> None:
    write("bad.chpl", "var x = ;\n")
    assert main(["-i", "bad.chpl"]) == 3
    assert Path("bad.chpl").read_text() == "var x = ;\n"


def test_in_place_with_check_is_usage_error(capsys: Any) -> None:
    write("a.chpl")
    assert main(["-i", "--check", "a.chpl"]) == 2


def test_skip(capsys: Any) -> None:
    write("a.chpl", "var a;\n")
    write("third_party/x/b.chpl", BAD)
    write("gen/c.chpl", BAD)
    write("d_gen.chpl", BAD)
    write("generated.chpl", "var g;\n")
    argv = [
        "**/*.chpl",
        "--skip",
        "third_party/**",
        "--skip",
        "gen",
        "--skip",
        "*_gen.chpl",
    ]
    assert main(argv) == 0
    assert capsys.readouterr().out == "var a;\nvar g;\n"


def test_skip_from_config(capsys: Any) -> None:
    write("chplfmt.cfg", "skip:\n  - vendor\n")
    write("a.chpl", "var a;\n")
    write("vendor/b.chpl", BAD)
    assert main(["a.chpl", "vendor/b.chpl"]) == 0
    assert capsys.readouterr().out == "var a;\n"


def test_is_skipped(tmp_path: Path) -> None:
    cwd = str(tmp_path)
    assert is_skipped("a/b.chpl", ["a/b.chpl"], cwd)
    assert is_skipped("./a/b.chpl", ["a/b.chpl"], cwd)
    assert is_skipped(str(tmp_path / "a" / "b.chpl"), ["a"], cwd)
    assert is_skipped("a/b.chpl", [str(tmp_path / "a")], cwd)
    assert is_skipped("a/b/c.chpl", ["a/*"], cwd)
    assert not is_skipped("ab/c.chpl", ["a"], cwd)
    assert not is_skipped("b.chpl", ["a/**"], cwd)


def test_exit_code_is_highest(capsys: Any, uppercase: None) -> None:
    write("a.chpl", "var a;\n")
    write("bad.chpl", BAD)
    assert main(["--check", "a.chpl", "bad.chpl", "missing.chpl"]) == 3
    err = capsys.readouterr().err
    assert "would reformat a.chpl" in err
    assert "bad.chpl:1:9: error: near ';'" in err
    assert "missing.chpl: error: cannot read file" in err


def test_unreadable_and_non_utf8(capsys: Any) -> None:
    Path("latin1.chpl").write_bytes(b"// caf\xe9\nvar x;\n")
    write("ok.chpl", "var ok;\n")
    assert main(["missing.chpl", "latin1.chpl", "ok.chpl"]) == 2
    captured = capsys.readouterr()
    assert captured.out == "var ok;\n"
    assert "latin1.chpl: error: not valid UTF-8" in captured.err


def test_crash_is_internal_error(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    def boom(text: str, **kwargs: Any) -> api.FormatResult:
        raise RuntimeError("boom")

    monkeypatch.setattr(api, "format_text", boom)
    write("a.chpl")
    write("bad.chpl", BAD)
    assert main(["a.chpl"]) == 4
    assert "a.chpl: internal error: RuntimeError: boom" in capsys.readouterr().err


def test_verification_error_exit_4(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    def fail(text: str, **kwargs: Any) -> api.FormatResult:
        raise api.VerificationError("a.chpl", "tokens", (1, 2), (3, 4))

    monkeypatch.setattr(api, "format_text", fail)
    write("a.chpl")
    assert main(["a.chpl"]) == 4
    assert capsys.readouterr().err == (
        "a.chpl: internal error: formatter output failed verification (tokens) "
        "at input 1:2 / output 3:4\n"
    )


def test_lines(capsys: Any) -> None:
    write("a.chpl", "var a;\nvar b;\n")
    write("b.chpl")
    assert main(["--lines", "1:2", "a.chpl"]) == 0
    assert main(["--lines", "1:2", "a.chpl", "b.chpl"]) == 2
    assert main(["--lines", "3:1", "a.chpl"]) == 2
    assert main(["--lines", "x", "a.chpl"]) == 2
    err = capsys.readouterr().err
    assert "--lines requires exactly one input file" in err
    assert "invalid value '3:1' for 'lines'" in err


def test_invalid_option_value(capsys: Any) -> None:
    assert main(["--brace-style", "x", "a.chpl"]) == 2
    assert capsys.readouterr().err == (
        "chplfmt: error: invalid value 'x' for 'brace-style' (choose from attach, break)\n"
    )


def test_invalid_config_file(capsys: Any) -> None:
    write(".chplfmt.cfg", "line-length: wide\n")
    write("a.chpl")
    assert main(["a.chpl"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid value 'wide' for 'line-length'" in captured.err


def test_list_options(capsys: Any) -> None:
    assert main(["--list-options"]) == 0
    out = capsys.readouterr().out
    assert "line-length: int >= 0 (default: 80)" in out
    assert (
        "single-statement-body: one of preserve, prefer-braces, prefer-single-line"
        in out
    )
    assert "skip: list of globs (default: [])" in out


def test_print_config(capsys: Any) -> None:
    write("Mason.toml", '[brick]\nname = "x"\n[tool.chplfmt]\nline-length = 100\n')
    assert main(["--print-config", "--no-comment-spacing", "--skip", "gen/**"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("line-length: 100\n")
    assert "comment-spacing: false\n" in out
    assert "skip:\n- gen/**\n" in out


def test_version(capsys: Any) -> None:
    assert main(["--version"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == f"chplfmt {__version__}"
    assert out[1].startswith("Chapel 2.")


def test_unified_diff_without_final_newline() -> None:
    assert unified_diff("a\nb", "a\nc", "f.chpl").endswith(
        "-b\n\\ No newline at end of file\n+c\n\\ No newline at end of file\n"
    )


def test_python_m(tmp_path: Path) -> None:
    write("a.chpl", "var a;\n")
    proc = subprocess.run(
        [sys.executable, "-m", "chplfmt", "--check", "a.chpl"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


def test_broken_pipe_exits_quietly(tmp_path: Path) -> None:
    write("big.chpl", "".join(f"var x{i} = {i};\n" for i in range(12000)))
    proc = subprocess.Popen(
        [sys.executable, "-m", "chplfmt", "big.chpl"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
    )
    assert proc.stdout is not None and proc.stderr is not None
    assert proc.stdout.readline() == b"var x0 = 0;\n"
    proc.stdout.close()
    err = proc.stderr.read()
    assert (proc.wait(timeout=60), err) == (141, b"")


def test_broken_pipe_in_process(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    write("a.chpl")

    class Closed:
        def write(self, _: str) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            raise BrokenPipeError

    monkeypatch.setattr(sys, "stdout", Closed())
    assert main(["a.chpl"]) == 141
    assert capsys.readouterr().err == ""


def test_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    write("a.chpl")

    def interrupt(*_: Any, **__: Any) -> api.FormatResult:
        raise KeyboardInterrupt

    monkeypatch.setattr(api, "format_text", interrupt)
    assert main(["a.chpl"]) == 130
    assert capsys.readouterr() == ("", "")


# End to end with the real formatter

MESSY = "\n  var a = 1;  \r\n\r\n\r\n\r\n//b\r\nvar c;"
TIDY = "var a = 1;\n\n// b\nvar c;\n"


def test_e2e_stdout(capsys: Any) -> None:
    write("a.chpl", MESSY)
    assert main(["a.chpl"]) == 0
    assert capsys.readouterr() == (TIDY, "")
    assert Path("a.chpl").read_bytes() == MESSY.encode()


def test_e2e_in_place(capsys: Any) -> None:
    p = write("a.chpl", MESSY)
    assert main(["-i", "a.chpl"]) == 0
    assert capsys.readouterr() == ("", "")
    assert p.read_bytes() == TIDY.encode()
    assert main(["--check", "a.chpl"]) == 0


def test_e2e_check(capsys: Any) -> None:
    write("a.chpl", MESSY)
    assert main(["--check", "-v", "a.chpl"]) == 1
    assert capsys.readouterr() == (
        "",
        "would reformat a.chpl\n"
        "  changed lines: 1, 2-7\n"
        "  rule applications: comment-spacing: 1\n",
    )


def test_e2e_diff(capsys: Any) -> None:
    write("a.chpl", "var a;  \n\n\n\nvar b;\n")
    assert main(["--diff", "a.chpl"]) == 0
    assert capsys.readouterr().out == (
        "--- a.chpl\t(original)\n+++ a.chpl\t(formatted)\n"
        "@@ -1,5 +1,3 @@\n-var a;  \n-\n-\n+var a;\n \n var b;\n"
    )
