"""Option registry and configargparse-based configuration (section 7.13)."""

from __future__ import annotations

import argparse
import dataclasses
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, NoReturn, Self, cast

import configargparse
import yaml

_META = "chplfmt"


class ConfigError(Exception):
    """Invalid configuration or command line (exit code 2)."""


@dataclass(frozen=True)
class OptionMeta:
    help: str
    choices: tuple[str, ...] = ()
    min: int | None = None


def _opt(
    default: Any, help: str, *, choices: Sequence[str] = (), min: int | None = None
) -> Any:
    meta = OptionMeta(help, tuple(choices), min)
    return field(default=default, metadata={_META: meta})


def option_key(f: dataclasses.Field[Any]) -> str:
    return f.name.replace("_", "-")


def option_meta(f: dataclasses.Field[Any]) -> OptionMeta:
    meta = f.metadata[_META]
    assert isinstance(meta, OptionMeta)
    return meta


def _dest(prefix: str, f: dataclasses.Field[Any]) -> str:
    return (prefix + f.name).replace("-", "_")


def _invalid(key: str, value: Any, meta: OptionMeta) -> ConfigError:
    if meta.choices:
        expected = "choose from " + ", ".join(meta.choices)
    elif meta.min is not None:
        expected = f"expected an integer >= {meta.min}"
    else:
        expected = "expected an integer"
    return ConfigError(f"invalid value '{value}' for '{key}' ({expected})")


def _convert(f: dataclasses.Field[Any], value: Any, key: str) -> Any:
    meta = option_meta(f)
    if isinstance(f.default, bool):
        return bool(value)
    if isinstance(f.default, tuple):
        return tuple(str(v) for v in value or ())
    if isinstance(f.default, int):
        if isinstance(value, int):
            number = value
        else:
            try:
                number = int(str(value).strip(), 10)
            except ValueError:
                raise _invalid(key, value, meta) from None
        if meta.min is not None and number < meta.min:
            raise _invalid(key, value, meta)
        return number
    if meta.choices and value not in meta.choices:
        raise _invalid(key, value, meta)
    return str(value)


class _OptionSet:
    """Generates CLI flags, config keys, and validation from dataclass fields."""

    @classmethod
    def add_arguments(
        cls, parser: argparse.ArgumentParser, prefix: str = ""
    ) -> list[str]:
        """Add one flag per field; returns the argparse dests."""
        dests: list[str] = []
        for f in _fields(cls):
            meta = option_meta(f)
            flag = f"--{prefix}{option_key(f)}"
            dest = _dest(prefix, f)
            dests.append(dest)
            if isinstance(f.default, bool):
                parser.add_argument(
                    flag,
                    dest=dest,
                    action=argparse.BooleanOptionalAction,
                    default=f.default,
                    help=meta.help,
                )
            elif isinstance(f.default, tuple):
                parser.add_argument(
                    flag,
                    dest=dest,
                    action="append",
                    default=None,
                    metavar="GLOB",
                    help=meta.help,
                )
            else:
                metavar = "{" + ",".join(meta.choices) + "}" if meta.choices else "N"
                parser.add_argument(
                    flag, dest=dest, default=f.default, metavar=metavar, help=meta.help
                )
        return dests

    @classmethod
    def from_args(
        cls, args: argparse.Namespace | dict[str, Any], prefix: str = ""
    ) -> Self:
        """Build and validate from parsed args; raises ConfigError."""
        values = vars(args) if isinstance(args, argparse.Namespace) else args
        kwargs: dict[str, Any] = {}
        for f in _fields(cls):
            key = prefix + option_key(f)
            kwargs[f.name] = _convert(f, values[_dest(prefix, f)], key)
        return cls(**kwargs)


def _fields(cls: type[_OptionSet]) -> tuple[dataclasses.Field[Any], ...]:
    return dataclasses.fields(cls)  # pyright: ignore[reportArgumentType]


@dataclass(frozen=True)
class FormatOptions(_OptionSet):
    line_length: int = _opt(80, "Maximum line length; 0 means unlimited.", min=0)
    indent_width: int = _opt(2, "Indentation of nested blocks.", min=1)
    continuation_indent: int = _opt(
        2, "Indentation of wrapped lines that have no alignment anchor.", min=1
    )
    tab_size: int = _opt(
        2, "Tab-stop width for expanding tabs in comments and measuring text.", min=1
    )
    brace_style: str = _opt(
        "attach",
        "Opening brace on the header line (attach) or on its own line (break).",
        choices=("attach", "break"),
    )
    else_placement: str = _opt(
        "cuddle",
        "'} else {' (cuddle) or 'else' on its own line (newline); also for catch.",
        choices=("cuddle", "newline"),
    )
    max_blank_lines: int = _opt(
        1, "Collapse runs of blank lines to at most this many.", min=0
    )
    bracket_spacing: bool = _opt(
        False, "Spaces inside domain, array, and tuple literal brackets."
    )
    comment_spacing: bool = _opt(
        True, "Insert a space after '//' when a letter or digit follows."
    )
    trailing_comma: bool = _opt(
        True, "Trailing comma exactly when the closing bracket is on its own line."
    )
    single_statement_body: str = _opt(
        "prefer-single-line",
        "Layout of bodies that consist of a single statement.",
        choices=("preserve", "prefer-braces", "prefer-single-line"),
    )
    remove_redundant_parens: bool = _opt(True, "Remove redundant parentheses.")
    remove_empty_statements: bool = _opt(True, "Remove empty statements (stray ';').")


@dataclass(frozen=True)
class RunOptions(_OptionSet):
    skip: tuple[str, ...] = _opt(
        (), "Skip matching paths (repeatable): exact path, directory prefix, or glob."
    )


class ArgParser(configargparse.ArgParser):
    """configargparse parser that raises ConfigError instead of exiting.

    Only dests in `config_dests` can be set from config files.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.config_dests: set[str] = set()

    def error(self, message: str) -> NoReturn:
        raise ConfigError(message)

    def get_possible_config_keys(self, action: argparse.Action) -> list[str]:
        if action.dest not in self.config_dests:
            return []
        return super().get_possible_config_keys(action)

    def get_command_line_key_for_unknown_config_file_setting(
        self, key: str
    ) -> NoReturn:
        raise ConfigError(f"unknown configuration key '{key}'")


def default_config_files(cwd: str) -> list[str]:
    names = ("chplfmt.cfg", ".chplfmt.cfg", "Mason.toml")
    return [os.path.join(cwd, name) for name in names]


def make_parser(cwd: str, prog: str = "chplfmt", **kwargs: Any) -> ArgParser:
    """A parser with chplcheck-style config-file handling and every option."""
    parser = ArgParser(
        prog,
        default_config_files=default_config_files(cwd),
        config_file_parser_class=configargparse.CompositeConfigParser(
            [
                configargparse.YAMLConfigFileParser,
                configargparse.TomlConfigParser(["tool.chplfmt"]),
            ]
        ),
        args_for_setting_config_path=["--config", "-c"],
        config_arg_help_message="config file path",
        **kwargs,
    )
    parser.config_dests.update(FormatOptions.add_arguments(parser))
    parser.config_dests.update(RunOptions.add_arguments(parser))
    return parser


def parse(parser: ArgParser, argv: Sequence[str]) -> argparse.Namespace:
    """parse_args that reports every problem as ConfigError."""
    try:
        return parser.parse_args(list(argv))
    except configargparse.ConfigFileParserException as e:
        raise ConfigError(str(e)) from e


def load_all(cwd: str, argv: Sequence[str] = ()) -> tuple[FormatOptions, RunOptions]:
    args = parse(make_parser(cwd), argv)
    return FormatOptions.from_args(args), RunOptions.from_args(args)


def load_options(cwd: str, argv: Sequence[str] = ()) -> FormatOptions:
    """Effective FormatOptions from config files in `cwd` and flags in `argv`."""
    return load_all(cwd, argv)[0]


def to_yaml(fmt: FormatOptions, run: RunOptions) -> str:
    """The effective configuration as YAML, using config-file keys."""
    data: dict[str, Any] = {}
    for opts in (fmt, run):
        for f in _fields(type(opts)):
            value = getattr(opts, f.name)
            if isinstance(value, tuple):
                value = list(cast(tuple[str, ...], value))
            data[option_key(f)] = value
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def describe_options() -> str:
    """Text for --list-options."""
    lines: list[str] = []
    for cls in (FormatOptions, RunOptions):
        for f in _fields(cls):
            meta = option_meta(f)
            if isinstance(f.default, bool):
                kind, default = "bool", str(f.default).lower()
            elif isinstance(f.default, tuple):
                kind, default = "list of globs", "[]"
            elif meta.choices:
                kind, default = "one of " + ", ".join(meta.choices), str(f.default)
            else:
                kind = "int" if meta.min is None else f"int >= {meta.min}"
                default = str(f.default)
            lines.append(f"{option_key(f)}: {kind} (default: {default})")
            lines.append(f"    {meta.help}")
    return "\n".join(lines) + "\n"
