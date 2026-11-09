"""chplfmt: an opinionated source formatter for Chapel."""

import logging

__version__ = "0.1.0"

# Warnings are also surfaced on the print report; don't print them twice.
logging.getLogger("chplfmt").addHandler(logging.NullHandler())
