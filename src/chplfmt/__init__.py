"""chplfmt: an opinionated source formatter for Chapel."""

import logging
from importlib.metadata import version

__version__ = version("chplfmt")

# Warnings are also surfaced on the print report; don't print them twice.
logging.getLogger("chplfmt").addHandler(logging.NullHandler())
