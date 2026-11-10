import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from chplfmt import _chapel
from chplfmt._chapel import (
    ChapelEnvironmentError,
    chapel_py_dir,
    check_version,
    find_chpl_home,
    load_chapel,
    parse_bootstrap_commands,
    parse_version,
)

BOOTSTRAP = """\
export CHPL_HOME='/opt/chapel/libexec'
export CHPL_THIRD_PARTY='/opt/chapel/libexec/third-party'
export PATH="$PATH:/whatever"
export CHPL_HOME='/evil'; rm -rf /
"""


class FakeRun:
    def __init__(self, stdout: str = "", returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(
        self, cmd: list[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, "")


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    saved = dict(os.environ)
    for name in ("CHPL_HOME", "CHPL_THIRD_PARTY", "CHPLFMT_CHAPEL_PY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield monkeypatch
    # The loader sets variables directly; monkeypatch only restores what it saw.
    os.environ.clear()
    os.environ.update(saved)


def fake_chapel(version: str = "2.10.0 pre-release (abc)") -> ModuleType:
    module = ModuleType("chapel")

    class Context:
        def __init__(self) -> None:
            if not os.environ.get("CHPL_HOME"):
                raise RuntimeError("CHPL_HOME must be set")

        def get_compiler_version(self) -> str:
            return version

    module.Context = Context  # type: ignore[attr-defined]
    return module


def make_chapel_py(root: Path) -> Path:
    (root / "chapel").mkdir(parents=True)
    (root / "chapel" / "__init__.py").write_text("")
    return root


def make_chpl_home(root: Path) -> tuple[Path, Path]:
    script = root / "util" / "chplenv" / "chpl_home_utils.py"
    script.parent.mkdir(parents=True)
    script.write_text("")
    return root, script


def importer(directory: Path) -> Any:
    """Fake import_module: 'chapel' is importable once `directory` is on sys.path."""
    module = fake_chapel()

    def _import(name: str) -> ModuleType:
        assert name == "chapel"
        if str(directory) in sys.path:
            return module
        raise ImportError("No module named 'chapel'")

    _import.module = module  # type: ignore[attr-defined]
    return _import


def test_parse_bootstrap_commands() -> None:
    assert parse_bootstrap_commands(BOOTSTRAP) == {
        "CHPL_HOME": "/opt/chapel/libexec",
        "CHPL_THIRD_PARTY": "/opt/chapel/libexec/third-party",
    }


def test_parse_bootstrap_commands_rejects_trailing_shell() -> None:
    assert parse_bootstrap_commands("export CHPL_HOME='/x'; echo hi\n") == {}


def test_find_chpl_home_from_env(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHPL_HOME", "/my/chapel")
    run = FakeRun()
    clean_env.setattr(_chapel.subprocess, "run", run)
    steps: list[str] = []
    assert find_chpl_home(steps) == ("/my/chapel", {"CHPL_HOME": "/my/chapel"})
    assert run.calls == []


def test_find_chpl_home_from_bootstrap(clean_env: pytest.MonkeyPatch) -> None:
    run = FakeRun(BOOTSTRAP)
    clean_env.setattr(_chapel.subprocess, "run", run)
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/bin/chpl")
    steps: list[str] = []
    home, env = find_chpl_home(steps) or ("", {})
    assert home == "/opt/chapel/libexec"
    assert env["CHPL_THIRD_PARTY"] == "/opt/chapel/libexec/third-party"
    [(cmd, kwargs)] = run.calls
    assert cmd == ["/bin/chpl", "--print-bootstrap-commands"]
    assert not kwargs.get("shell")


def test_find_chpl_home_without_chpl(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setattr(_chapel.shutil, "which", lambda name: None)
    steps: list[str] = []
    assert find_chpl_home(steps) is None
    assert any("not found on PATH" in s for s in steps)


def test_find_chpl_home_bad_output(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setattr(_chapel.subprocess, "run", FakeRun("garbage\n", returncode=1))
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/bin/chpl")
    assert find_chpl_home([]) is None


def test_chapel_py_dir_runs_helper_with_argument_list(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home, script = make_chpl_home(tmp_path / "home")
    run = FakeRun("/some/chapel-py\n")
    clean_env.setattr(_chapel.subprocess, "run", run)
    env = {"CHPL_HOME": str(home), "CHPL_THIRD_PARTY": "/tp"}
    assert chapel_py_dir(str(home), env, []) == "/some/chapel-py"
    [(cmd, kwargs)] = run.calls
    assert cmd == [sys.executable, str(script), "--chpldeps-chapel-py"]
    assert not kwargs.get("shell")
    assert kwargs["env"]["CHPL_HOME"] == str(home)
    assert kwargs["env"]["CHPL_THIRD_PARTY"] == "/tp"


def test_chapel_py_dir_missing_script(tmp_path: Path) -> None:
    steps: list[str] = []
    assert chapel_py_dir(str(tmp_path), {}, steps) is None
    assert "chpl_home_utils.py" in steps[-1]


def test_load_uses_plain_import_first(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHPL_HOME", "/my/chapel")
    module = fake_chapel()
    run = FakeRun()
    clean_env.setattr(_chapel.subprocess, "run", run)
    assert load_chapel(lambda name: module) == (module, "2.10.0 pre-release (abc)")
    assert run.calls == []


def test_load_sets_chpl_home_for_context(clean_env: pytest.MonkeyPatch) -> None:
    # chapel.Context() needs CHPL_HOME even when 'import chapel' works.
    run = FakeRun(BOOTSTRAP)
    clean_env.setattr(_chapel.subprocess, "run", run)
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/bin/chpl")
    module = fake_chapel()
    assert load_chapel(lambda name: module)[0] is module
    assert os.environ["CHPL_HOME"] == "/opt/chapel/libexec"
    assert os.environ["CHPL_THIRD_PARTY"] == "/opt/chapel/libexec/third-party"
    assert len(run.calls) == 1


def _module_at(path: Path) -> ModuleType:
    path.parent.mkdir(parents=True)
    path.write_text("")
    module = fake_chapel()
    module.__file__ = str(path)
    return module


def test_load_derives_chpl_home_from_module_path(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home, _ = make_chpl_home(tmp_path / "home")
    module = _module_at(home / "third-party" / "chpl-venv" / "chapel" / "__init__.py")
    run = FakeRun(BOOTSTRAP)
    clean_env.setattr(_chapel.subprocess, "run", run)
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/bin/chpl")
    assert load_chapel(lambda name: module)[0] is module
    assert os.environ["CHPL_HOME"] == str(home)
    assert os.environ["CHPL_THIRD_PARTY"] == str(home / "third-party")
    assert run.calls == []


def test_load_module_path_without_helper_falls_back_to_chpl(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module = _module_at(tmp_path / "x" / "third-party" / "chapel" / "__init__.py")
    run = FakeRun(BOOTSTRAP)
    clean_env.setattr(_chapel.subprocess, "run", run)
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/bin/chpl")
    assert load_chapel(lambda name: module)[0] is module
    assert os.environ["CHPL_HOME"] == "/opt/chapel/libexec"
    assert len(run.calls) == 1


def test_load_env_chpl_home_beats_module_path(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home, _ = make_chpl_home(tmp_path / "home")
    module = _module_at(home / "third-party" / "chapel" / "__init__.py")
    clean_env.setenv("CHPL_HOME", "/my/chapel")
    assert load_chapel(lambda name: module)[0] is module
    assert os.environ["CHPL_HOME"] == "/my/chapel"


def test_load_context_failure(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setattr(_chapel.shutil, "which", lambda name: None)
    module = fake_chapel()
    with pytest.raises(ChapelEnvironmentError, match="CHPL_HOME must be set"):
        load_chapel(lambda name: module)


def test_load_rejects_old_chapel(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setenv("CHPL_HOME", "/my/chapel")
    module = fake_chapel("2.9.0")
    with pytest.raises(ChapelEnvironmentError, match=r"requires Chapel 2\.10"):
        load_chapel(lambda name: module)


def test_load_from_override_appends_to_sys_path(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    directory = make_chapel_py(tmp_path / "chapel-py")
    clean_env.setenv("CHPLFMT_CHAPEL_PY", str(directory))
    clean_env.setenv("CHPL_HOME", "/my/chapel")
    imp = importer(directory)
    before = list(sys.path)
    assert load_chapel(imp)[0] is imp.module
    assert sys.path == [*before, str(directory)]


def test_load_via_bootstrap_and_helper(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home, script = make_chpl_home(tmp_path / "home")
    directory = make_chapel_py(tmp_path / "deps")
    outputs = {
        "--print-bootstrap-commands": f"export CHPL_HOME='{home}'\n",
        "--chpldeps-chapel-py": f"{directory}\n",
    }
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert not kwargs.get("shell")
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, outputs[cmd[-1]], "")

    clean_env.setattr(_chapel.subprocess, "run", run)
    clean_env.setattr(_chapel.shutil, "which", lambda name: "/usr/bin/chpl")
    imp = importer(directory)
    assert load_chapel(imp)[0] is imp.module
    assert calls == [
        ["/usr/bin/chpl", "--print-bootstrap-commands"],
        [sys.executable, str(script), "--chpldeps-chapel-py"],
    ]
    assert sys.path[-1] == str(directory)
    assert os.environ["CHPL_HOME"] == str(home)


def test_load_failure_lists_steps(clean_env: pytest.MonkeyPatch) -> None:
    clean_env.setattr(_chapel.shutil, "which", lambda name: None)

    def fail(name: str) -> ModuleType:
        raise ImportError("No module named 'chapel'")

    with pytest.raises(ChapelEnvironmentError) as exc:
        load_chapel(fail)
    message = str(exc.value)
    assert "import chapel" in message
    assert "CHPL_HOME is not set" in message
    assert "chpl --print-bootstrap-commands" in message
    assert "CHPLFMT_CHAPEL_PY" in message
    assert isinstance(exc.value, ImportError)


def test_load_override_without_package(
    clean_env: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env.setenv("CHPLFMT_CHAPEL_PY", str(tmp_path))
    before = list(sys.path)
    with pytest.raises(ChapelEnvironmentError, match=r"__init__\.py: not found"):
        load_chapel(importer(tmp_path / "elsewhere"))
    assert sys.path == before


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2.10.0 pre-release (e23242670c1)", (2, 10, 0)),
        ("2.10.0", (2, 10, 0)),
        ("2.11", (2, 11, 0)),
        ("10.2.3 (abc)", (10, 2, 3)),
        ("nightly", None),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int] | None) -> None:
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    "text", ["2.10.0", "2.10.0 pre-release (abc)", "2.11.1", "3.0.0"]
)
def test_supported_versions(text: str) -> None:
    check_version(text)


@pytest.mark.parametrize("text", ["2.9.0", "1.33.0", "2.9.1 pre-release (abc)"])
def test_version_too_old(text: str) -> None:
    with pytest.raises(ChapelEnvironmentError, match=r"requires Chapel 2\.10 or newer"):
        check_version(text)


def test_unparseable_version() -> None:
    with pytest.raises(ChapelEnvironmentError, match="cannot parse"):
        check_version("unknown")


def _site_packages() -> str:
    import configargparse

    return os.path.dirname(configargparse.__file__)


SRC = str(Path(__file__).resolve().parents[2] / "src")


def _isolated_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in ("CHPL_HOME", "CHPLFMT_CHAPEL_PY", "PYTHONPATH"):
        env.pop(name, None)
    return env


@pytest.mark.skipif(shutil.which("chpl") is None, reason="chpl not on PATH")
def test_real_discovery_without_site_packages() -> None:
    # -S: no site-packages, so 'import chapel' fails and discovery must run.
    code = (
        f"import sys; sys.path.insert(0, {SRC!r}); "
        "import chplfmt._chapel as c; "
        "print(c.chapel.__file__); print(c.CHAPEL_VERSION); print(sys.path[-1])"
    )
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        env=_isolated_env(),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    chapel_file, version, last = proc.stdout.splitlines()
    assert chapel_file == os.path.join(last, "chapel", "__init__.py")
    assert parse_version(version) is not None


def test_cli_reports_missing_chapel_with_exit_2(tmp_path: Path) -> None:
    code = (
        f"import sys; sys.path.insert(0, {SRC!r}); sys.path.append({_site_packages()!r}); "
        "from chplfmt.cli import main; sys.exit(main(sys.argv[1:]))"
    )
    env = _isolated_env()
    env["CHPLFMT_CHAPEL_PY"] = str(tmp_path / "missing")
    target = tmp_path / "a.chpl"
    target.write_text("var x = 1;\n")
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code, str(target)],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 2
    assert proc.stderr.startswith("chplfmt: error: could not find the Chapel Python")
    assert "tried: CHPLFMT_CHAPEL_PY=" in proc.stderr
    # Options that don't need chapel-py still work.
    proc = subprocess.run(
        [sys.executable, "-S", "-c", code, "--list-options"],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "line-length" in proc.stdout
