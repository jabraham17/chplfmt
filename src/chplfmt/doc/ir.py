"""Immutable document IR (design section 7.6) and its constructors."""

from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar

from chplfmt.source import display_width


class Check(enum.Enum):
    """How `conditional_group` decides whether an alternative fits."""

    FIRST_LINE = "first_line"
    ALL_LINES = "all_lines"


FIRST_LINE = Check.FIRST_LINE
ALL_LINES = Check.ALL_LINES


class GroupId:
    """Identity of a group, for `if_break(..., group_id=...)`."""

    __slots__ = ("name",)

    def __init__(self, name: str = "g") -> None:
        self.name = name

    def __repr__(self) -> str:
        return f"GroupId({self.name!r})"


# Every node has `forced`: it always produces a line break (hardline or
# break_parent inside). Nodes are immutable, so this break propagation is
# computed bottom-up at construction instead of in a separate render pre-pass.


@dataclass(frozen=True, slots=True, eq=False)
class Text:
    s: str
    # Display width, or -1 if a tab makes it depend on the start column.
    width: int = field(init=False, repr=False)
    forced: ClassVar[bool] = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "width", -1 if "\t" in self.s else display_width(self.s)
        )


@dataclass(frozen=True, slots=True, eq=False)
class Concat:
    parts: tuple[Doc, ...]
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", any(p.forced for p in self.parts))


@dataclass(frozen=True, slots=True, eq=False)
class Group:
    contents: Doc
    id: GroupId | None
    should_break: bool
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", self.should_break or self.contents.forced)


@dataclass(frozen=True, slots=True, eq=False)
class Indent:
    contents: Doc
    n: int
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", self.contents.forced)


@dataclass(frozen=True, slots=True, eq=False)
class Align:
    contents: Doc
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", self.contents.forced)


@dataclass(frozen=True, slots=True, eq=False)
class Line:
    hard: bool = False
    soft: bool = False
    literal: bool = False
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", self.hard)


@dataclass(frozen=True, slots=True, eq=False)
class Fill:
    parts: tuple[Doc, ...]
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "forced", any(p.forced for p in self.parts))


@dataclass(frozen=True, slots=True, eq=False)
class IfBreak:
    broken: Doc
    flat: Doc
    group_id: GroupId | None
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # A forced break in `broken` only matters once the group is broken anyway.
        object.__setattr__(self, "forced", self.flat.forced)


@dataclass(frozen=True, slots=True, eq=False)
class LineSuffix:
    contents: Doc
    forced: ClassVar[bool] = False


@dataclass(frozen=True, slots=True, eq=False)
class TrailingComment:
    text: str
    forced: ClassVar[bool] = False


@dataclass(frozen=True, slots=True, eq=False)
class BreakParent:
    forced: ClassVar[bool] = True


@dataclass(frozen=True, slots=True, eq=False)
class ConditionalGroup:
    alts: tuple[Doc, ...]
    check: Check
    forced: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        # Forced only if whichever alternative gets chosen breaks.
        object.__setattr__(self, "forced", all(a.forced for a in self.alts))


@dataclass(frozen=True, slots=True, eq=False)
class Verbatim:
    s: str
    forced: ClassVar[bool] = False


type Doc = (
    Text
    | Concat
    | Group
    | Indent
    | Align
    | Line
    | Fill
    | IfBreak
    | LineSuffix
    | TrailingComment
    | BreakParent
    | ConditionalGroup
    | Verbatim
)
type DocLike = Doc | str


def _doc(d: DocLike) -> Doc:
    return text(d) if isinstance(d, str) else d


def text(s: str) -> Text:
    """Literal text without newlines."""
    if "\n" in s:
        raise ValueError(f"text() must not contain a newline: {s!r}")
    return Text(s)


EMPTY = Text("")


def concat(*docs: DocLike) -> Doc:
    """A sequence of docs."""
    if len(docs) == 1:
        return _doc(docs[0])
    return Concat(tuple(_doc(d) for d in docs))


def group(doc: DocLike, id: GroupId | None = None, should_break: bool = False) -> Group:
    """Print flat if it fits, else break."""
    return Group(_doc(doc), id, should_break)


def indent(doc: DocLike, n: int) -> Indent:
    """Increase the indentation of broken lines inside by `n` columns."""
    return Indent(_doc(doc), n)


def align(doc: DocLike) -> Align:
    """Indent broken lines inside to the column where `align` starts."""
    return Align(_doc(doc))


line = Line()
softline = Line(soft=True)
hardline = Line(hard=True)
literalline = Line(hard=True, literal=True)
break_parent = BreakParent()


def fill(parts: Sequence[DocLike]) -> Fill:
    """Bin-pack alternating content and separators."""
    return Fill(tuple(_doc(p) for p in parts))


def if_break(
    broken: DocLike, flat: DocLike = "", group_id: GroupId | None = None
) -> IfBreak:
    """Choose by the break state of the enclosing group, or of `group_id`."""
    return IfBreak(_doc(broken), _doc(flat), group_id)


def line_suffix(doc: DocLike) -> LineSuffix:
    """Defer `doc` until just before the next newline."""
    return LineSuffix(_doc(doc))


def trailing_comment(comment: str) -> LineSuffix:
    """A trailing `//` comment, recorded separately in the line record."""
    if "\n" in comment:
        raise ValueError(f"trailing comment must not contain a newline: {comment!r}")
    return LineSuffix(TrailingComment(comment))


def conditional_group(
    alts: Sequence[DocLike], check: Check = Check.FIRST_LINE
) -> ConditionalGroup:
    """Take the first alternative that fits under `check`, else the last."""
    if not alts:
        raise ValueError("conditional_group needs at least one alternative")
    return ConditionalGroup(tuple(_doc(a) for a in alts), check)


def verbatim(s: str) -> Verbatim:
    """Text (possibly multi-line) emitted byte-for-byte."""
    return Verbatim(s)


def dump(doc: DocLike) -> str:
    """Readable indented tree of `doc`, for tests and debugging."""
    out: list[str] = []
    _dump(_doc(doc), 0, out)
    return "\n".join(out)


def _gid(g: GroupId | None) -> str:
    return "" if g is None else f" id={g.name}"


def _dump(d: Doc, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    match d:
        case Text(s):
            out.append(f"{pad}text {s!r}")
        case Verbatim(s):
            out.append(f"{pad}verbatim {s!r}")
        case TrailingComment(s):
            out.append(f"{pad}trailing_comment {s!r}")
        case BreakParent():
            out.append(f"{pad}break_parent")
        case Line(hard, soft, literal):
            name = (
                "literalline"
                if literal
                else "hardline"
                if hard
                else "softline"
                if soft
                else "line"
            )
            out.append(pad + name)
        case Concat(parts) | Fill(parts):
            out.append(pad + ("concat" if isinstance(d, Concat) else "fill"))
            for p in parts:
                _dump(p, depth + 1, out)
        case Group(contents, gid, should_break):
            out.append(f"{pad}group{_gid(gid)}{' break' if should_break else ''}")
            _dump(contents, depth + 1, out)
        case Indent(contents, n):
            out.append(f"{pad}indent {n}")
            _dump(contents, depth + 1, out)
        case Align(contents):
            out.append(f"{pad}align")
            _dump(contents, depth + 1, out)
        case LineSuffix(contents):
            out.append(f"{pad}line_suffix")
            _dump(contents, depth + 1, out)
        case IfBreak(broken, flat, gid):
            out.append(f"{pad}if_break{_gid(gid)}")
            out.append(f"{pad}  broken:")
            _dump(broken, depth + 2, out)
            out.append(f"{pad}  flat:")
            _dump(flat, depth + 2, out)
        case ConditionalGroup(alts, check):
            out.append(f"{pad}conditional_group {check.name}")
            for a in alts:
                _dump(a, depth + 1, out)
