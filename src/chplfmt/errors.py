"""Exceptions of the library API (section 7.11), shared by `api` and `verify`."""

from __future__ import annotations

from chplfmt._chapel import Diagnostic


class FormatError(Exception):
    pass


class InternalError(FormatError):
    """A printer bug caught before verification (e.g. a lost comment)."""


class ChplParseError(FormatError):
    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("\n".join(str(d) for d in diagnostics))


class VerificationError(FormatError):
    """Line and column are 1-based; `0:0` means unknown."""

    def __init__(
        self,
        path: str,
        check: str,
        input_pos: tuple[int, int],
        output_pos: tuple[int, int],
    ) -> None:
        self.path = path
        self.check = check
        self.input_pos = input_pos
        self.output_pos = output_pos
        super().__init__(
            f"{path}: internal error: formatter output failed verification "
            f"({check}) at input {input_pos[0]}:{input_pos[1]} / "
            f"output {output_pos[0]}:{output_pos[1]}"
        )
