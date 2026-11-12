"""chplfmt: an opinionated source formatter for Chapel."""

import logging
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("chplfmt")
except PackageNotFoundError:
    __version__ = "unknown"

# Warnings are also surfaced on the print report; don't print them twice.
logging.getLogger("chplfmt").addHandler(logging.NullHandler())
