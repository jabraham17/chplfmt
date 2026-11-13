"""Command-line interface."""

from __future__ import annotations

import argparse
import contextlib
import difflib
import fnmatch
import glob
import importlib
import logging
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass

from chplfmt import __version__
from chplfmt.config import (
    ArgParser,
    ConfigError,
    FormatOptions,
    RunOptions,
    describe_options,
    make_parser,
    parse,
    to_yaml,
)

log = logging.getLogger("chplfmt")

EXIT_OK = 0
EXIT_CHANGED = 1
EXIT_USAGE = 2
EXIT_PARSE = 3
EXIT_INTERNAL = 4
EXIT_INTERRUPTED = 130  # 128 + SIGINT
EXIT_BROKEN_PIPE = 141  # 128 + SIGPIPE

STDIN_PATH = "<stdin>"


@dataclass(frozen=True)
class _Input:
    path: str | None  # None for stdin
    display: str
    skip_path: str | None  # None: never skipped


def build_parser(cwd: str) -> ArgParser:
    parser = make_parser(cwd, description="An opinionated source formatter for Chapel.")
    parser.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="file or glob ('**' supported); '-' reads standard input",
    )
    parser.add_argument(
        "--file", action="append", default=[], metavar="FILE", help="add a file"
    )
    parser.add_argument(
        "-i", "--in-place", action="store_true", help="rewrite files in place"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if any file would change; list them on stderr",
    )
    parser.add_argument(
        "--diff", action="store_true", help="print a unified diff to stdout"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="with --check: more details"
    )
    parser.add_argument(
        "--lines", metavar="A:B", help="format only lines A..B (single input only)"
    )
    parser.add_argument(
        "--stdin-filename",
        metavar="PATH",
        help="name used for diagnostics and --skip matching with '-'",
    )
    parser.add_argument(
        "--list-options", action="store_true", help="describe every option"
    )
    parser.add_argument(
        "--print-config",
        action="store_true",
        help="print the effective configuration as YAML",
    )
    parser.add_argument(
        "--lsp", action="store_true", help="run the LSP server on stdio"
    )
    parser.add_argument(
        "--version", action="store_true", help="print chplfmt and Chapel versions"
    )
    # Development only.
    parser.add_argument("--debug-dump-failed", metavar="DIR", help=argparse.SUPPRESS)
    parser.add_argument(
        "--debug-skip-verify", action="store_true", help=argparse.SUPPRESS
    )
    return parser


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _usage_error(message: str) -> int:
    _err(f"chplfmt: error: {message}")
    return EXIT_USAGE


def parse_lines(spec: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+):(\d+)", spec.strip())
    if m is None or not 1 <= int(m.group(1)) <= int(m.group(2)):
        raise ConfigError(
            f"invalid value '{spec}' for 'lines' (expected A:B with 1 <= A <= B)"
        )
    return int(m.group(1)), int(m.group(2))


def collect_inputs(args: argparse.Namespace) -> list[_Input]:
    """Expand files and globs; raises ConfigError for usage errors."""
    raw: list[str] = [*args.files, *args.file]
    if not raw:
        raise ConfigError("no input files (use '-' to read standard input)")
    inputs: list[_Input] = []
    seen: set[str] = set()
    has_stdin = False
    for item in raw:
        if item == "-":
            if args.in_place:
                raise ConfigError("-i/--in-place cannot be used with '-' (stdin)")
            if has_stdin:
                raise ConfigError("'-' can be given only once")
            has_stdin = True
            name: str | None = args.stdin_filename
            inputs.append(_Input(None, name or STDIN_PATH, name))
            continue
        if os.path.isdir(item):
            suggestion = os.path.join(item.rstrip("/") or "/", "**", "*.chpl")
            raise ConfigError(
                f"'{item}' is a directory; pass files or a glob such as '{suggestion}'"
            )
        if glob.has_magic(item):
            matches = sorted(glob.glob(item, recursive=True))
            paths = [m for m in matches if not os.path.isdir(m)]
        else:
            paths = [item]
        for path in paths:
            if path not in seen:
                seen.add(path)
                inputs.append(_Input(path, path, path))
    return inputs


def is_skipped(path: str, patterns: Sequence[str], cwd: str) -> bool:
    """Exact path, directory prefix, or fnmatch (relative or absolute)."""
    abs_path = os.path.normpath(os.path.join(cwd, path))
    rel_path = os.path.relpath(abs_path, cwd)
    for pattern in patterns:
        abs_pattern = os.path.normpath(os.path.join(cwd, pattern))
        if abs_path == abs_pattern or abs_path.startswith(
            abs_pattern.rstrip(os.sep) + os.sep
        ):
            return True
        if fnmatch.fnmatch(abs_path, abs_pattern) or fnmatch.fnmatch(
            rel_path, os.path.normpath(pattern)
        ):
            return True
    return False


def unified_diff(old: str, new: str, path: str) -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=path,
        tofile=path,
        fromfiledate="(original)",
        tofiledate="(formatted)",
    )
    return "".join(
        line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
        for line in lines
    )


def _write_in_place(path: str, text: str) -> None:
    target = os.path.realpath(path)
    fd, tmp = tempfile.mkstemp(
        dir=os.path.dirname(target), prefix=".chplfmt-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read(inp: _Input) -> bytes:
    if inp.path is None:
        return sys.stdin.buffer.read()
    with open(inp.path, "rb") as f:
        return f.read()


def _line_range(start: int, end: int) -> str:
    """1-based inclusive text for a 0-based, end-exclusive edit range."""
    first, last = start + 1, max(end, start + 1)
    return str(first) if first == last else f"{first}-{last}"


def _process(
    inp: _Input,
    args: argparse.Namespace,
    options: FormatOptions,
    lines: tuple[int, int] | None,
) -> int:
    from chplfmt import api

    try:
        data = _read(inp)
    except OSError as e:
        _err(f"{inp.display}: error: cannot read file: {e.strerror or e}")
        return EXIT_USAGE
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as e:
        _err(f"{inp.display}: error: not valid UTF-8 (byte offset {e.start})")
        return EXIT_USAGE

    try:
        debug = api.DebugOptions(args.debug_dump_failed, args.debug_skip_verify)
        result = api.format_text(
            text, path=inp.display, options=options, lines=lines, debug=debug
        )
    except api.ChplParseError as e:
        for diagnostic in e.diagnostics:
            _err(str(diagnostic))
        return EXIT_PARSE
    except api.FormatError as e:
        _err(str(e))
        return EXIT_INTERNAL
    except Exception as e:
        log.debug("crash while formatting %s", inp.display, exc_info=True)
        _err(f"{inp.display}: internal error: {type(e).__name__}: {e}")
        return EXIT_INTERNAL

    for w in result.report.warnings:
        _err(f"{inp.display}:{w.line}:{w.col}: warning: {w.message}")

    if args.in_place:
        if result.changed and inp.path is not None:
            try:
                _write_in_place(inp.path, result.text)
            except OSError as e:
                _err(f"{inp.display}: error: cannot write file: {e.strerror or e}")
                return EXIT_USAGE
        return EXIT_OK
    if not (args.check or args.diff):
        sys.stdout.write(result.text)
        return EXIT_OK
    if args.diff and result.changed:
        sys.stdout.write(unified_diff(text, result.text, inp.display))
    if args.check and result.changed:
        _err(f"would reformat {inp.display}")
        if args.verbose:
            ranges = [_line_range(e.start_line, e.end_line) for e in result.edits]
            _err(f"  changed lines: {', '.join(ranges)}")
            counts = result.report.rule_counts()
            if counts:
                rules = ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
                _err(f"  rule applications: {rules}")
        return EXIT_CHANGED
    return EXIT_OK


def _print_version() -> int:
    print(f"chplfmt {__version__}")
    try:
        from chplfmt import _chapel
    except ImportError as e:
        return _usage_error(str(e))
    print(f"Chapel {_chapel.CHAPEL_VERSION}")
    return EXIT_OK


def _run_lsp() -> int:
    try:
        importlib.import_module("chplfmt._chapel")
    except ImportError as e:
        return _usage_error(str(e))
    from chplfmt import lsp

    return lsp.main()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _main(argv)
    except BrokenPipeError:
        # The reader went away (`chplfmt f.chpl | head`): stop quietly, and keep
        # the interpreter's final flush from failing again.
        with contextlib.suppress(OSError, ValueError, AttributeError):
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        return EXIT_BROKEN_PIPE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED


def _main(argv: Sequence[str] | None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    cwd = os.getcwd()
    try:
        args = parse(build_parser(cwd), argv)
        options = FormatOptions.from_args(args)
        run = RunOptions.from_args(args)
        lines = parse_lines(args.lines) if args.lines is not None else None
    except ConfigError as e:
        if "--lsp" in argv:  # the server reports config errors per request
            return _run_lsp()
        return _usage_error(str(e))

    if args.list_options:
        sys.stdout.write(describe_options())
        return EXIT_OK
    if args.print_config:
        sys.stdout.write(to_yaml(options, run))
        return EXIT_OK
    if args.version:
        return _print_version()
    if args.lsp:
        return _run_lsp()

    try:
        if args.in_place and (args.check or args.diff):
            raise ConfigError("-i/--in-place cannot be combined with --check or --diff")
        inputs = collect_inputs(args)
        if lines is not None and len(inputs) != 1:
            raise ConfigError("--lines requires exactly one input file")
    except ConfigError as e:
        return _usage_error(str(e))

    try:
        importlib.import_module("chplfmt._chapel")
    except ImportError as e:
        return _usage_error(str(e))

    code = EXIT_OK
    for inp in inputs:
        if inp.skip_path is not None and is_skipped(inp.skip_path, run.skip, cwd):
            log.debug("skipping %s", inp.display)
            continue
        code = max(code, _process(inp, args, options, lines))
    sys.stdout.flush()
    return code
