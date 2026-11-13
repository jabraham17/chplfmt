"""Printer. Importing this package registers every construct printer."""

from chplfmt.printer import aggregates as aggregates
from chplfmt.printer import attrs as attrs
from chplfmt.printer import cond as cond
from chplfmt.printer import decls as decls
from chplfmt.printer import exprs as exprs
from chplfmt.printer import loops as loops
from chplfmt.printer import stmts as stmts
from chplfmt.printer.core import (
    REGISTRY,
    Printer,
    PrintFn,
    PrintReport,
    RuleApplication,
    printer,
)

__all__ = [
    "REGISTRY",
    "PrintFn",
    "PrintReport",
    "Printer",
    "RuleApplication",
    "printer",
]
