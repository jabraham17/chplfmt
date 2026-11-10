"""Locate and load chapel-py (section 7.1) and parse Chapel text through one shim."""

from __future__ import annotations

import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any

MIN_CHAPEL_VERSION = (2, 10)

_BOOTSTRAP_RE = re.compile(r"^export (CHPL_HOME|CHPL_THIRD_PARTY)='([^']*)'$")
_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")
_HINT = (
    "set CHPLFMT_CHAPEL_PY to the directory that contains 'chapel/', "
    "or set CHPL_HOME, or put 'chpl' on PATH"
)
_SUBPROCESS_TIMEOUT = 120


class ChapelEnvironmentError(ImportError):
    """chapel-py is missing, can't be loaded, or the Chapel version is too old."""

    def __init__(self, message: str, steps: Iterable[str] = (), hint: str = "") -> None:
        self.steps = list(steps)
        lines = [message, *(f"  tried: {s}" for s in self.steps)]
        if hint:
            lines.append(f"  hint: {hint}")
        super().__init__("\n".join(lines))


def parse_bootstrap_commands(output: str) -> dict[str, str]:
    """Extract CHPL_HOME / CHPL_THIRD_PARTY from `chpl --print-bootstrap-commands`."""
    found: dict[str, str] = {}
    for line in output.splitlines():
        m = _BOOTSTRAP_RE.match(line)
        if m:
            found[m.group(1)] = m.group(2)
    return found


def find_chpl_home(steps: list[str]) -> tuple[str, dict[str, str]] | None:
    """Return CHPL_HOME and the variables to pass to chpl_home_utils.py."""
    home = os.environ.get("CHPL_HOME")
    if home:
        steps.append(f"CHPL_HOME from the environment: {home}")
        return home, {"CHPL_HOME": home}
    steps.append("CHPL_HOME is not set in the environment")
    chpl = shutil.which("chpl")
    if chpl is None:
        steps.append("chpl --print-bootstrap-commands: 'chpl' not found on PATH")
        return None
    cmd = [chpl, "--print-bootstrap-commands"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        steps.append(f"{' '.join(cmd)}: {e}")
        return None
    found = parse_bootstrap_commands(proc.stdout)
    if proc.returncode != 0 or not found.get("CHPL_HOME"):
        steps.append(
            f"{' '.join(cmd)}: no CHPL_HOME in its output (exit {proc.returncode})"
        )
        return None
    steps.append(f"CHPL_HOME from {' '.join(cmd)}: {found['CHPL_HOME']}")
    return found["CHPL_HOME"], found


def chapel_py_dir(
    chpl_home: str, env_vars: dict[str, str], steps: list[str]
) -> str | None:
    """Ask `chpl_home_utils.py --chpldeps-chapel-py` where chapel-py lives."""
    script = os.path.join(chpl_home, "util", "chplenv", "chpl_home_utils.py")
    if not os.path.isfile(script):
        steps.append(f"{script}: not found")
        return None
    cmd = [sys.executable, script, "--chpldeps-chapel-py"]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **env_vars},
            timeout=_SUBPROCESS_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as e:
        steps.append(f"{' '.join(cmd)}: {e}")
        return None
    directory = proc.stdout.strip()
    if proc.returncode != 0 or not directory:
        steps.append(f"{' '.join(cmd)}: no directory reported (exit {proc.returncode})")
        return None
    steps.append(f"chapel-py directory from {script}: {directory}")
    return directory


def _set_env_defaults(env_vars: dict[str, str]) -> None:
    for name, value in env_vars.items():
        os.environ.setdefault(name, value)


def _import_chapel(
    import_module: Callable[[str], ModuleType], steps: list[str]
) -> ModuleType:
    try:
        return import_module("chapel")
    except ImportError as e:
        steps.append(f"import chapel: {e}")

    override = os.environ.get("CHPLFMT_CHAPEL_PY")
    directory: str | None = None
    if override:
        steps.append(f"CHPLFMT_CHAPEL_PY={override}")
        directory = override
    elif found := find_chpl_home(steps):
        _set_env_defaults(found[1])
        directory = chapel_py_dir(found[0], found[1], steps)
    if directory is None:
        raise ChapelEnvironmentError(
            "could not find the Chapel Python bindings (chapel-py)", steps, _HINT
        )
    init = os.path.join(directory, "chapel", "__init__.py")
    if not os.path.isfile(init):
        steps.append(f"{init}: not found")
        raise ChapelEnvironmentError(
            "could not find the Chapel Python bindings (chapel-py)", steps, _HINT
        )
    # Append, so older packages bundled next to chapel-py don't shadow ours.
    if directory not in sys.path:
        sys.path.append(directory)
    try:
        return import_module("chapel")
    except ImportError as e:
        steps.append(f"import chapel from {directory}: {e}")
        raise ChapelEnvironmentError(
            "could not load the Chapel Python bindings (chapel-py)", steps, _HINT
        ) from e


def _home_of_module(
    module: ModuleType, steps: list[str]
) -> tuple[str, dict[str, str]] | None:
    """CHPL_HOME of a chapel-py inside `$CHPL_HOME/third-party/` (avoids running chpl)."""
    path = getattr(module, "__file__", None)
    if not isinstance(path, str):
        return None
    head, sep, _ = os.path.abspath(path).rpartition(os.sep + "third-party" + os.sep)
    script = os.path.join(head, "util", "chplenv", "chpl_home_utils.py")
    if not sep or not os.path.isfile(script):
        return None
    steps.append(f"CHPL_HOME from the chapel-py location: {head}")
    return head, {"CHPL_HOME": head, "CHPL_THIRD_PARTY": head + sep.rstrip(os.sep)}


def load_chapel(
    import_module: Callable[[str], ModuleType] = importlib.import_module,
) -> tuple[ModuleType, str]:
    """Import chapel-py (searching for it if needed); return it and the Chapel version."""
    steps: list[str] = []
    module = _import_chapel(import_module, steps)
    # chapel.Context() raises "CHPL_HOME must be set" without it.
    if not os.environ.get("CHPL_HOME") and (
        found := _home_of_module(module, steps) or find_chpl_home(steps)
    ):
        _set_env_defaults(found[1])
    try:
        version = str(module.Context().get_compiler_version())
    except RuntimeError as e:
        steps.append(f"chapel.Context(): {e}")
        raise ChapelEnvironmentError(
            "could not start the Chapel Python bindings (chapel-py)", steps, _HINT
        ) from e
    check_version(version)
    return module, version


def parse_version(version: str) -> tuple[int, int, int] | None:
    """Parse `get_compiler_version()` output such as '2.10.0 pre-release (abc)'."""
    m = _VERSION_RE.match(version)
    if m is None:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)


def check_version(version: str) -> None:
    parsed = parse_version(version)
    if parsed is None:
        raise ChapelEnvironmentError(f"cannot parse the Chapel version {version!r}")
    if parsed[:2] < MIN_CHAPEL_VERSION:
        need = ".".join(map(str, MIN_CHAPEL_VERSION))
        raise ChapelEnvironmentError(
            f"Chapel {version} is not supported; chplfmt requires Chapel {need} or newer"
        )


if TYPE_CHECKING:
    import chapel  # pyright: ignore[reportMissingTypeStubs]

    CHAPEL_VERSION: str
else:
    chapel, CHAPEL_VERSION = load_chapel()


@dataclass(frozen=True)
class Diagnostic:
    path: str
    line: int  # 1-based; 0 when unknown
    col: int  # 1-based UTF-8 byte column; 0 when unknown
    message: str
    kind: str  # dyno's kind: "error", "syntax", "warning", or "note"
    end_line: int = 0
    end_col: int = 0  # exclusive

    @property
    def is_error(self) -> bool:
        return self.kind not in ("warning", "note")

    @property
    def severity(self) -> str:
        return self.kind if self.kind in ("warning", "note") else "error"

    def __str__(self) -> str:
        where = f"{self.path}:{self.line}:{self.col}" if self.line > 0 else self.path
        return f"{where}: {self.severity}: {self.message}"


@dataclass(frozen=True)
class ParseResult:
    ctx: chapel.Context
    asts: list[chapel.AstNode]
    diagnostics: list[Diagnostic] = field(default_factory=list[Diagnostic])

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.is_error]


def _same_path(a: str, b: str) -> bool:
    return a == b or os.path.realpath(a) == os.path.realpath(b)


def _error_message(err: chapel.Error) -> str:
    try:
        return err.message()
    except UnicodeDecodeError:
        # dyno can cut a multi-byte character in half when quoting it.
        return "invalid character"


def map_diagnostics(
    errors: Iterable[chapel.Error], path: str, tmp: str | None = None
) -> list[Diagnostic]:
    """Convert dyno errors, reporting `tmp` (and unknown paths) as `path`."""
    result: list[Diagnostic] = []
    for err in errors:
        loc = err.location()
        loc_path = loc.path()
        if not loc_path or (tmp is not None and _same_path(loc_path, tmp)):
            loc_path = path
        (line, col), (end_line, end_col) = loc.start(), loc.end()
        if line < 1:
            line = col = end_line = end_col = 0
        result.append(
            Diagnostic(
                path=loc_path,
                line=line,
                col=col,
                message=_error_message(err),
                kind=err.kind(),
                end_line=end_line,
                end_col=end_col,
            )
        )
    return result


@contextmanager
def parse_text(text: str, path: str) -> Generator[ParseResult]:
    """Parse `text` as if it were the file at `path`."""
    ctx = chapel.Context()
    native: Callable[[str, str], list[chapel.AstNode]] | None = getattr(
        ctx, "parse_text", None
    )
    if native is not None:
        with ctx.track_errors() as errs:
            asts = native(path, text)
        yield ParseResult(ctx, asts, map_diagnostics(_errors(errs), path))
        return
    with tempfile.TemporaryDirectory(prefix="chplfmt-") as d:
        tmp = os.path.join(d, os.path.basename(path) or "input.chpl")
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        with ctx.track_errors() as errs:
            asts = ctx.parse(tmp)
        yield ParseResult(ctx, asts, map_diagnostics(_errors(errs), path, tmp))


def _errors(errs: Any) -> list[chapel.Error]:
    return list(errs)
