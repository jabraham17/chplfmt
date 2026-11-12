# chplfmt

`chplfmt` is a code formatter for the Chapel programming language. It helps maintain consistent code style and improves readability by automatically formatting Chapel source files according to predefined rules.

It uses the Chapel parser (through the `chapel` Python bindings) for program
structure and its own lexer for comments and spacing. Every result is
re-parsed and checked against the input before anything is written; if that
check fails, the file is left unchanged.

## Requirements

- Chapel 2.10 or newer, with the Chapel Python bindings (chapel-py). They are
  found automatically through `$CHPL_HOME`, or through `chpl` on `PATH`. Set
  `CHPLFMT_CHAPEL_PY` to the directory that contains `chapel/` to override.
- Python 3.12 or newer.
- A Rust toolchain for source installs (including editable installs). Install
  [rustup](https://rustup.rs/); the workspace selects Rust 1.85.1 from
  `native/rust-toolchain.toml`.

## Installation

```sh
pip install git+<repo-url>
```

Source installs compile the native extension with maturin. Prebuilt
`cp312-abi3` wheels, when available, work on CPython 3.12 and newer without
installing Rust; formatting still needs the Chapel Python bindings.

## Usage

```sh
chplfmt file.chpl                  # print the formatted file to stdout
chplfmt -i 'src/**/*.chpl'         # rewrite files in place
chplfmt --check 'src/**/*.chpl'    # exit 1 and list files that would change
chplfmt --diff file.chpl           # print a unified diff
chplfmt --lines 10:20 file.chpl    # format only lines 10 to 20
cat file.chpl | chplfmt - --stdin-filename file.chpl
chplfmt -i 'src/**/*.chpl' --skip 'src/third_party/**'
```

Inputs are files and globs (`**` is supported); pass a glob such as
`src/**/*.chpl` instead of a directory. `--check --verbose` also prints the
changed line ranges and how often each rewrite rule applied.

| Exit code | Meaning |
|---|---|
| 0 | Success (`--check`: nothing to change) |
| 1 | `--check`: at least one file would change |
| 2 | Usage, configuration, environment, or Chapel version error |
| 3 | At least one input failed to parse |
| 4 | Internal error (the output failed verification); the file is untouched |

## Configuration

Options are read from the first of `chplfmt.cfg`, `.chplfmt.cfg` (YAML), or
`Mason.toml` (`[tool.chplfmt]`) in the current directory, or from the file
given with `-c/--config`. Command-line flags override config files. Every
option is also a flag, e.g. `--line-length 100` or `--no-trailing-comma`.

```yaml
# .chplfmt.cfg
line-length: 100
brace-style: break
trailing-comma: false
skip:
  - third_party/**
```

```toml
# Mason.toml
[tool.chplfmt]
line-length = 100
single-statement-body = "prefer-braces"
```

| Option | Values (default) | Effect |
|---|---|---|
| `line-length` | int ≥ 0 (80) | Maximum line length; 0 means unlimited |
| `indent-width` | int ≥ 1 (2) | Indentation of nested blocks |
| `continuation-indent` | int ≥ 1 (2) | Indentation of wrapped lines that have no alignment anchor |
| `tab-size` | int ≥ 1 (2) | Tab-stop width for expanding tabs in comments and measuring text |
| `brace-style` | `attach`, `break` (`attach`) | Opening brace on the header line or on its own line |
| `else-placement` | `cuddle`, `newline` (`cuddle`) | `} else {` or `else` on its own line; also for `catch` |
| `max-blank-lines` | int ≥ 0 (1) | Collapse runs of blank lines to at most this many |
| `bracket-spacing` | bool (false) | Spaces inside domain, array, and tuple literal brackets |
| `comment-spacing` | bool (true) | Insert a space after `//` when a letter or digit follows |
| `trailing-comma` | bool (true) | Trailing comma exactly when the closing bracket is on its own line |
| `single-statement-body` | `preserve`, `prefer-braces`, `prefer-single-line` (`prefer-single-line`) | Layout of bodies that consist of a single statement |
| `remove-redundant-parens` | bool (true) | Remove redundant parentheses |
| `remove-empty-statements` | bool (true) | Remove empty statements (stray `;`) |
| `skip` | list of globs (empty) | Skip matching paths: exact path, directory prefix, or glob |

`chplfmt --list-options` prints this list and `chplfmt --print-config` prints
the effective configuration.

### Turning formatting off

```chapel
// chplfmt: off
const table = [1, 0, 0,
               0, 1, 0,
               0, 0, 1];
// chplfmt: on
```

Statements between the two directives are kept byte-for-byte. The directives
must be on their own lines, between statements.

## Editor integration

`chplfmt --lsp` runs a language server on stdio that provides document and
range formatting. It reads the configuration from its working directory (the
workspace root) and is meant to run next to chpl-language-server.

## Development

Install rustup first, then run these commands from the repository root:

```sh
rustup toolchain install 1.85.1 --profile minimal --component clippy rustfmt
export CARGO_BUILD_JOBS=4
uv venv --python 3.12 .venv
uv pip install --python .venv -e '.[dev]'
.venv/bin/ruff check . && .venv/bin/black --check . && .venv/bin/pyright
.venv/bin/python native/tools/gen_width_table.py --check
cargo fmt --manifest-path native/Cargo.toml --all --check
cargo clippy --manifest-path native/Cargo.toml --workspace --all-targets -- -D warnings
cargo test --manifest-path native/Cargo.toml --workspace --all-targets
.venv/bin/python -m pytest -q -n 4 -m native \
  tests/unit/test_config.py tests/unit/test_doc_render.py \
  tests/unit/test_lexer.py tests/unit/test_native_doc.py \
  tests/unit/test_source.py
.venv/bin/python -m pytest -n 4 -m "not corpus"   # fast tests
.venv/bin/python -m pytest -n 4                   # include corpus properties
```

The `native` marker selects tests that do not need chapel-py. The full test
suite and the formatter still require Chapel and its Python bindings.

- Golden tests live in `tests/golden/<area>/` and option tests in
  `tests/options/<option>/<value>/`; `pytest --update-goldens` rewrites the
  expected `.good` files.
- Corpus property tests (marker `corpus`) run over `$CHPL_HOME/modules` (and
  `$CHPL_HOME/test` when present). Per-profile properties use a sample of files
  unless `CHPLFMT_FULL_CORPUS=1`.
- The design is described in `design.md`.
