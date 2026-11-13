"""comment-spacing: `//x` -> `// x`.

The verifier's comment check recomputes the expected text with `apply`.
"""

from __future__ import annotations

import unicodedata

from chplfmt.rules.base import Rule


def _is_letter_or_digit(ch: str) -> bool:
    category = unicodedata.category(ch)
    return category[0] == "L" or category == "Nd"


def apply(text: str) -> str:
    """`//x` -> `// x` when `x` is a letter or digit; anything else is unchanged."""
    if text.startswith("//") and len(text) > 2 and _is_letter_or_digit(text[2]):
        return "// " + text[2:]
    return text


RULE = Rule("comment-spacing", lambda o: o.comment_spacing)
