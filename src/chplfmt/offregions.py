"""`chplfmt: off` regions and other verbatim spans."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from chplfmt._chapel import chapel
from chplfmt.lexer import TokenKind
from chplfmt.tokens import Node, TokenIndex

DIRECTIVE_RE = re.compile(r"^//\s*chplfmt:\s*(off|on)\s*$")


@dataclass(frozen=True)
class OffRegion:
    """Code-point offsets `[start, end)`: start of the `off` line to end of the `on` line."""

    start: int
    end: int
    off_token: int
    on_token: int | None  # None: the region runs to the end of its statement list


@dataclass(frozen=True)
class OffRegions:
    regions: list[OffRegion] = field(default_factory=list[OffRegion])
    # Directive comments that bound no region (not at statement level, or an
    # `on` without `off`), for warnings.
    misplaced: list[int] = field(default_factory=list[int])

    def contains(self, offset: int) -> bool:
        return any(r.start <= offset < r.end for r in self.regions)


def directive(index: TokenIndex, i: int) -> str | None:
    """`"off"`/`"on"` if token `i` is a directive comment alone on its line."""
    tokens = index.tokens
    tok = tokens[i]
    if tok.kind is not TokenKind.LINE_COMMENT or (i > 0 and tok.nl_before == 0):
        return None
    nxt = tokens[i + 1]
    if nxt.kind is not TokenKind.EOF and nxt.nl_before == 0:
        return None
    m = DIRECTIVE_RE.match(tok.text)
    return m.group(1) if m else None


def is_statement_list(node: Node | None) -> bool:
    """Whether a comment owned by `node` sits between statements of a list."""
    return node is None or isinstance(
        node,
        (
            chapel.Module,
            chapel.SimpleBlockLike,
            chapel.AggregateDecl,
            chapel.Interface,
            chapel.Cobegin,
        ),
    )


def _list_end(index: TokenIndex, node: Node | None) -> tuple[int, int]:
    """The last token inside the list (possibly a comment) and its closer."""
    eof = len(index.tokens) - 1
    sp = None if node is None else index.node_span(node)
    if sp is None or (isinstance(node, chapel.Module) and node.kind() == "implicit"):
        return eof - 1, eof
    last = sp[1]
    tok = index.tokens[last]
    if tok.text == "}" and tok.kind is TokenKind.PUNCT and index.owner(last) == node:
        return last - 1, last
    return last, index.next_code(last)


def find_off_regions(index: TokenIndex) -> OffRegions:
    """Regions from `// chplfmt: off` to the matching `on` in the same list."""
    source = index.source
    tokens = index.tokens
    regions: list[OffRegion] = []
    misplaced: list[int] = []
    region_end = -1
    for i in range(len(tokens) - 1):
        kind = directive(index, i)
        if kind is None or tokens[i].start_offset < region_end:
            continue
        owner = index.owner(i)
        if kind == "on" or not is_statement_list(owner):
            misplaced.append(i)
            continue
        on_token: int | None = None
        for j in range(i + 1, len(tokens) - 1):
            if index.owner(j) == owner and directive(index, j) == "on":
                on_token = j
                break
        if on_token is not None:
            end = source.line_end(tokens[on_token].start[0])
        else:
            last, closer = _list_end(index, owner)
            end = tokens[last].end_offset
            if tokens[closer].start[0] > tokens[last].end[0]:
                end = source.line_end(tokens[last].end[0])
        start = source.line_start(tokens[i].start[0])
        regions.append(OffRegion(start, end, i, on_token))
        region_end = end
    return OffRegions(regions, misplaced)


def verbatim_spans(
    index: TokenIndex, off: OffRegions | None = None
) -> list[tuple[int, int]]:
    """Offsets of off regions and extern blocks outside them, in order."""
    off = find_off_regions(index) if off is None else off
    spans = [(r.start, r.end) for r in off.regions]
    spans += [
        (t.start_offset, t.end_offset)
        for t in index.tokens
        if t.kind is TokenKind.OPAQUE and not off.contains(t.start_offset)
    ]
    return sorted(spans)
