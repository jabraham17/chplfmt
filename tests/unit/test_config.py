import argparse
import dataclasses
from pathlib import Path

import pytest
import yaml

from chplfmt.config import (
    ConfigError,
    FormatOptions,
    RunOptions,
    describe_options,
    load_all,
    load_options,
    to_yaml,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults(tmp_path: Path) -> None:
    assert load_options(str(tmp_path)) == FormatOptions()
    assert load_all(str(tmp_path))[1] == RunOptions()


def test_default_values_match_design() -> None:
    o = FormatOptions()
    assert (o.line_length, o.indent_width, o.continuation_indent, o.tab_size) == (
        80,
        2,
        2,
        2,
    )
    assert o.brace_style == "attach"
    assert o.else_placement == "cuddle"
    assert o.max_blank_lines == 1
    assert o.bracket_spacing is False
    assert o.comment_spacing and o.trailing_comma
    assert o.remove_redundant_parens and o.remove_empty_statements
    assert o.single_statement_body == "prefer-single-line"


@pytest.mark.parametrize("name", ["chplfmt.cfg", ".chplfmt.cfg"])
def test_yaml_default_files(tmp_path: Path, name: str) -> None:
    write(
        tmp_path / name,
        "line-length: 100\nbrace-style: break\ntrailing-comma: false\n"
        "single-statement-body: prefer-braces\nskip:\n  - third_party/**\n  - gen\n",
    )
    fmt, run = load_all(str(tmp_path))
    assert fmt.line_length == 100
    assert fmt.brace_style == "break"
    assert fmt.trailing_comma is False
    assert fmt.single_statement_body == "prefer-braces"
    assert run.skip == ("third_party/**", "gen")


def test_mason_toml(tmp_path: Path) -> None:
    write(
        tmp_path / "Mason.toml",
        '[brick]\nname = "x"\nversion = "0.1.0"\n\n'
        "[tool.chplfmt]\nline-length = 100\n"
        'single-statement-body = "prefer-braces"\nskip = ["a/**", "b"]\n',
    )
    fmt, run = load_all(str(tmp_path))
    assert fmt.line_length == 100
    assert fmt.single_statement_body == "prefer-braces"
    assert run.skip == ("a/**", "b")


def test_mason_toml_without_section(tmp_path: Path) -> None:
    write(tmp_path / "Mason.toml", '[brick]\nname = "x"\n')
    assert load_options(str(tmp_path)) == FormatOptions()


def test_only_cwd_is_searched(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "line-length: 100\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    assert load_options(str(sub)).line_length == 80


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("chplfmt.cfg", "comment-spacing: false\nremove-redundant-parens: no\n"),
        (
            "Mason.toml",
            "[tool.chplfmt]\ncomment-spacing = false\n"
            "remove-redundant-parens = false\n",
        ),
    ],
)
def test_boolean_false_in_config(tmp_path: Path, name: str, text: str) -> None:
    write(tmp_path / name, text)
    fmt = load_options(str(tmp_path))
    assert fmt.comment_spacing is False
    assert fmt.remove_redundant_parens is False


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("chplfmt.cfg", "bracket-spacing: true\n"),
        ("Mason.toml", "[tool.chplfmt]\nbracket-spacing = true\n"),
    ],
)
def test_boolean_true_in_config(tmp_path: Path, name: str, text: str) -> None:
    write(tmp_path / name, text)
    assert load_options(str(tmp_path)).bracket_spacing is True


def test_bool_flags(tmp_path: Path) -> None:
    fmt = load_options(str(tmp_path), ["--bracket-spacing", "--no-trailing-comma"])
    assert fmt.bracket_spacing is True
    assert fmt.trailing_comma is False


def test_precedence(tmp_path: Path) -> None:
    write(
        tmp_path / "chplfmt.cfg",
        "line-length: 100\nindent-width: 3\ntab-size: 5\ntrailing-comma: false\n",
    )
    explicit = write(
        tmp_path / "explicit.yaml",
        "line-length: 120\nindent-width: 4\n"
        "trailing-comma: true\ncomment-spacing: false\n",
    )
    cwd = str(tmp_path)
    # defaults < default files
    assert load_options(cwd).tab_size == 5
    # default files < -c
    fmt = load_options(cwd, ["-c", str(explicit)])
    assert (fmt.line_length, fmt.indent_width, fmt.tab_size) == (120, 4, 5)
    assert fmt.trailing_comma is True
    # -c < command line
    fmt = load_options(
        cwd,
        [
            "--config",
            str(explicit),
            "--line-length",
            "140",
            "--comment-spacing",
            "--no-trailing-comma",
        ],
    )
    assert (fmt.line_length, fmt.indent_width) == (140, 4)
    assert fmt.comment_spacing is True
    assert fmt.trailing_comma is False
    assert fmt.max_blank_lines == 1


def test_command_line_overrides_false_from_config(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "comment-spacing: false\n")
    assert load_options(str(tmp_path), ["--comment-spacing"]).comment_spacing


def test_explicit_toml_config(tmp_path: Path) -> None:
    cfg = write(tmp_path / "fmt.toml", "[tool.chplfmt]\nmax-blank-lines = 0\n")
    assert load_options(str(tmp_path), ["-c", str(cfg)]).max_blank_lines == 0


def test_skip_from_cli_is_repeatable(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "skip:\n  - from_config\n")
    _, run = load_all(str(tmp_path), ["--skip", "a/**", "--skip", "b.chpl"])
    assert run.skip == ("a/**", "b.chpl")
    _, run = load_all(str(tmp_path))
    assert run.skip == ("from_config",)


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["--brace-style", "x"],
            "invalid value 'x' for 'brace-style' (choose from attach, break)",
        ),
        (
            ["--single-statement-body", "always"],
            "invalid value 'always' for 'single-statement-body' "
            "(choose from preserve, prefer-braces, prefer-single-line)",
        ),
        (
            ["--line-length", "-1"],
            "invalid value '-1' for 'line-length' (expected an integer >= 0)",
        ),
        (
            ["--indent-width", "0"],
            "invalid value '0' for 'indent-width' (expected an integer >= 1)",
        ),
        (
            ["--tab-size", "two"],
            "invalid value 'two' for 'tab-size' (expected an integer >= 1)",
        ),
    ],
)
def test_validation_messages(tmp_path: Path, argv: list[str], message: str) -> None:
    with pytest.raises(ConfigError) as exc:
        load_options(str(tmp_path), argv)
    assert str(exc.value) == message


def test_validation_from_config_file(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "else-placement: sometimes\n")
    with pytest.raises(ConfigError) as exc:
        load_options(str(tmp_path))
    assert str(exc.value) == (
        "invalid value 'sometimes' for 'else-placement' (choose from cuddle, newline)"
    )


def test_bad_boolean_in_config(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "bracket-spacing: maybe\n")
    with pytest.raises(ConfigError):
        load_options(str(tmp_path))


@pytest.mark.parametrize("key", ["no-such-option", "check", "in-place", "lsp"])
def test_unknown_config_key(tmp_path: Path, key: str) -> None:
    write(tmp_path / "chplfmt.cfg", f"{key}: true\n")
    with pytest.raises(ConfigError, match=f"unknown configuration key '{key}'"):
        load_options(str(tmp_path))


def test_missing_explicit_config(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_options(str(tmp_path), ["-c", str(tmp_path / "nope.cfg")])


def test_malformed_yaml(tmp_path: Path) -> None:
    write(tmp_path / "chplfmt.cfg", "line-length: [unclosed\n")
    with pytest.raises(ConfigError):
        load_options(str(tmp_path))


def test_prefix_for_embedding() -> None:
    parser = argparse.ArgumentParser()
    FormatOptions.add_arguments(parser, prefix="chplfmt-")
    RunOptions.add_arguments(parser, prefix="chplfmt-")
    args = parser.parse_args(
        [
            "--chplfmt-line-length",
            "90",
            "--no-chplfmt-trailing-comma",
            "--chplfmt-skip",
            "x",
        ]
    )
    fmt = FormatOptions.from_args(args, prefix="chplfmt-")
    assert fmt.line_length == 90
    assert fmt.trailing_comma is False
    assert RunOptions.from_args(args, prefix="chplfmt-").skip == ("x",)
    args = parser.parse_args(["--chplfmt-brace-style", "x"])
    with pytest.raises(ConfigError, match="'chplfmt-brace-style'"):
        FormatOptions.from_args(args, prefix="chplfmt-")


def test_every_field_has_metadata() -> None:
    for cls in (FormatOptions, RunOptions):
        for f in dataclasses.fields(cls):
            assert f.metadata["chplfmt"].help


def test_describe_options_lists_every_option() -> None:
    text = describe_options()
    for cls in (FormatOptions, RunOptions):
        for f in dataclasses.fields(cls):
            assert f"\n{f.name.replace('_', '-')}: " in "\n" + text
    assert "brace-style: one of attach, break (default: attach)" in text
    assert "line-length: int >= 0 (default: 80)" in text
    assert "bracket-spacing: bool (default: false)" in text


def test_to_yaml_round_trips(tmp_path: Path) -> None:
    fmt = FormatOptions(
        line_length=0, brace_style="break", bracket_spacing=True, comment_spacing=False
    )
    run = RunOptions(skip=("a/**",))
    text = to_yaml(fmt, run)
    data = yaml.safe_load(text)
    assert data["line-length"] == 0
    assert data["skip"] == ["a/**"]
    write(tmp_path / "chplfmt.cfg", text)
    assert load_all(str(tmp_path)) == (fmt, run)
