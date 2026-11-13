"""Comment attachment.

`attach(index, off)` assigns every comment outside verbatim regions to exactly
one node, as a *leading*, *trailing*, or *dangling* comment:

1. The enclosing node is the smallest node whose token span strictly contains
   the comment (a statement's span includes its `;`).
2. Candidates are its children plus *anchors*, own tokens of the enclosing
   node: `{`, `then`, `else`, and the last token of the header.
3. `preceding`/`following` are the nearest candidates before/after it.
4. Special cases, then the generic rule (see `_attach_one`). Attaching to an
   anchor makes the comment dangling on the enclosing node *after* that
   anchor; following anchors are never targets (except `else`).

Blank lines are recorded as newline counts around each comment; the printer
collapses them (`max-blank-lines`).
"""

from __future__ import annotations

import enum
from bisect import bisect_left
from dataclasses import dataclass, field

from chplfmt._chapel import chapel
from chplfmt.lexer import TokenKind
from chplfmt.offregions import OffRegions, find_off_regions, is_statement_list
from chplfmt.tokens import Node, TokenIndex


class Placement(enum.StrEnum):
    OWN_LINE = "own-line"  # only whitespace before it on its line
    END_OF_LINE = "end-of-line"  # code before it, a newline after it
    INLINE = "inline"


@dataclass(frozen=True)
class Comment:
    token: int
    placement: Placement
    nl_before: int  # newlines between the previous token and the comment
    nl_after: int  # newlines between the comment and the next token (0 at EOF)
    is_line: bool  # a `//` comment


@dataclass(frozen=True)
class Anchor:
    """A token of the enclosing node that a dangling comment follows.

    `kind` is `"{"`, `"("`, `"["` (an open bracket: the comment is inside
    it, after any other dangling comments there), `"then"`, `"else"`, or
    `"header"` (the last token of the declaration/statement header).
    """

    kind: str
    token: int


@dataclass(frozen=True)
class Dangling:
    comment: Comment
    anchor: Anchor | None  # None: anywhere inside the node (no candidates)


@dataclass
class NodeComments:
    leading: list[Comment] = field(default_factory=list[Comment])
    trailing: list[Comment] = field(default_factory=list[Comment])
    dangling: list[Dangling] = field(default_factory=list[Dangling])


type Key = Node | None  # None: the file (when it has no implicit module)
type _Cand = tuple[int, int, Node | Anchor]

_EMPTY = NodeComments()
_ANCHORS = {TokenKind.PUNCT: ("{", "(", "["), TokenKind.IDENT: ("then", "else")}


@dataclass
class Attachment:
    comments: list[int]  # every attachable comment token, in order
    by_node: dict[Key, NodeComments]
    # Comment token -> (node, "leading" | "trailing" | "dangling").
    where: dict[int, tuple[Key, str]]
    file_node: Key  # the implicit module, if any (key of top-level comments)

    def of(self, node: Key) -> NodeComments:
        return self.by_node.get(node, _EMPTY)

    def leading(self, node: Key) -> list[Comment]:
        return self.of(node).leading

    def trailing(self, node: Key) -> list[Comment]:
        return self.of(node).trailing

    def dangling(self, node: Key) -> list[Dangling]:
        return self.of(node).dangling


def placement(index: TokenIndex, i: int) -> Placement:
    tokens = index.tokens
    if i == 0 or tokens[i].nl_before:
        return Placement.OWN_LINE
    nxt = tokens[i + 1]
    if nxt.nl_before or nxt.kind is TokenKind.EOF:
        return Placement.END_OF_LINE
    return Placement.INLINE


class _Attacher:
    def __init__(self, index: TokenIndex, off: OffRegions) -> None:
        self.index = index
        self.tokens = index.tokens
        self.off = off
        roots = index.roots
        self.file_node: Key = next(
            (
                r
                for r in roots
                if isinstance(r, chapel.Module) and r.kind() == "implicit"
            ),
            None,
        )
        self._cands: dict[Key, tuple[list[_Cand], list[int]]] = {}
        self.result = Attachment([], {}, {}, self.file_node)

    def comment(self, i: int) -> Comment:
        tokens = self.tokens
        nxt = tokens[i + 1]
        return Comment(
            i,
            placement(self.index, i),
            tokens[i].nl_before,
            0 if nxt.kind is TokenKind.EOF else nxt.nl_before,
            tokens[i].kind is TokenKind.LINE_COMMENT,
        )

    def add(
        self, node: Key, role: str, c: Comment, anchor: Anchor | None = None
    ) -> None:
        r = self.result
        assert c.token not in r.where, f"comment {c.token} attached twice"
        nc = r.by_node.get(node)
        if nc is None:
            nc = r.by_node[node] = NodeComments()
        if role == "leading":
            nc.leading.append(c)
        elif role == "trailing":
            nc.trailing.append(c)
        else:
            nc.dangling.append(Dangling(c, anchor))
        r.where[c.token] = (node, role)

    # Enclosing node and candidates

    def enclosing(self, i: int) -> Key:
        index = self.index
        node = index.owner(i)
        while node is not None and node is not self.file_node:
            sp = index.node_span(node)
            if sp is not None and sp[0] < i < sp[1]:
                break
            node = index.parent(node)
        if node is None:
            node = self.file_node
        if is_statement_list(node):
            # A comment before a statement's `;` is inside the statement.
            cands, starts = self.candidates(node)
            k = bisect_left(starts, i) - 1
            if k >= 0 and cands[k][1] >= i:
                stmt = cands[k][2]
                if not isinstance(stmt, Anchor):
                    return stmt
        return node

    def _kids(self, node: Key) -> list[Node]:
        if node is None:
            return list(self.index.roots)
        return self.index.children(node)

    def candidates(self, node: Key) -> tuple[list[_Cand], list[int]]:
        cached = self._cands.get(node)
        if cached is not None:
            return cached
        index = self.index
        stmt_list = is_statement_list(node)
        cands: list[_Cand] = []
        for k in self._kids(node):
            sp = index.stmt_span(k) if stmt_list else index.node_span(k)
            if sp is not None:
                cands.append((sp[0], sp[1], k))
        if node is not None and node is not self.file_node:
            cands += [(a.token, a.token, a) for a in self.anchors(node, cands)]
            cands.sort(key=lambda c: c[0])
        result = (cands, [c[0] for c in cands])
        self._cands[node] = result
        return result

    def anchors(self, node: Node, kids: list[_Cand]) -> list[Anchor]:
        index = self.index
        tokens = self.tokens
        own = set(index.own_tokens(node))
        found: list[Anchor] = []
        for i in sorted(own):
            tok = tokens[i]
            if tok.text in _ANCHORS.get(tok.kind, ()):
                found.append(Anchor(tok.text, i))
        header = index.header_span(node)
        if (
            header is not None
            and header[1] in own
            and all(a.token != header[1] for a in found)
        ):
            found.append(Anchor("header", header[1]))
        # `(`/`[` are anchors only for empty lists (see `_attach_one`).
        return found

    # Attachment

    def run(self) -> Attachment:
        tokens = self.tokens
        off = self.off
        attachable = [
            i
            for i, t in enumerate(tokens)
            if t.is_comment and not off.contains(t.start_offset)
        ]
        self.result.comments = attachable
        moved = self._moved_to_brace(attachable)
        for i in attachable:
            c = self.comment(i)
            target = moved.get(i)
            if target is not None:
                self.add(target[0], "dangling", c, target[1])
            else:
                self._attach_one(c)
        return self.result

    def _moved_to_brace(self, attachable: list[int]) -> dict[int, tuple[Node, Anchor]]:
        """An end-of-line comment between a header and `{` moves after the `{`.

        So do the comments after it up to the `{`, to keep their order.
        """
        index = self.index
        tokens = self.tokens
        moved: dict[int, tuple[Node, Anchor]] = {}
        for i in attachable:
            if i in moved or placement(index, i) is not Placement.END_OF_LINE:
                continue
            b = index.next_code(i)
            tok = tokens[b]
            if tok.kind is not TokenKind.PUNCT or tok.text != "{":
                continue
            owner = index.owner(b)
            if owner is None:
                continue
            enc = self.enclosing(i)
            ok = owner == enc or (
                isinstance(owner, chapel.Block)
                and index.parent(owner) == enc
                and (sp := index.node_span(owner)) is not None
                and sp[0] == b
                and not is_statement_list(enc)
            )
            if ok:
                for j in range(i, b):
                    if not self.off.contains(tokens[j].start_offset):
                        moved[j] = (owner, Anchor("{", b))
        return moved

    def _attach_one(self, c: Comment) -> None:
        i = c.token
        enc = self.enclosing(i)
        cands, starts = self.candidates(enc)
        k = bisect_left(starts, i)
        preceding = cands[k - 1][2] if k > 0 else None
        following = cands[k][2] if k < len(cands) else None
        if (
            isinstance(preceding, chapel.AttributeGroup)
            and self.index.prev_code(i) == cands[k - 1][1]
        ):
            # Between attributes and the declaration: stays after the attributes.
            self.add(preceding, "trailing", c)
            return
        if isinstance(preceding, Anchor) and preceding.kind in ("(", "["):
            close = self.tokens[preceding.token].match
            if close is not None and i < close:
                if following is None or starts[k] >= close:
                    self.add(enc, "dangling", c, preceding)
                    return
                preceding = None  # before the first item of the list
            else:
                preceding = cands[k - 2][2] if k > 1 else None
                if isinstance(preceding, Anchor) and preceding.kind in ("(", "["):
                    preceding = None
        if isinstance(following, Anchor) and following.kind in ("(", "["):
            # `proc f /*c*/ (a)`: the first item inside the brackets.
            close = self.tokens[following.token].match
            nxt = cands[k + 1] if k + 1 < len(cands) else None
            if nxt is not None and close is not None and nxt[1] < close:
                following = nxt[2]
        if isinstance(following, Anchor):
            if following.kind == "else":
                branch = next(
                    (x[2] for x in cands[k + 1 :] if not isinstance(x[2], Anchor)),
                    None,
                )
                if branch is not None:
                    self.add(branch, "leading", c)
                    return
            following = None
        if c.placement is Placement.END_OF_LINE:
            order = (("trailing", preceding), ("leading", following))
        else:
            order = (("leading", following), ("trailing", preceding))
        for role, target in order:
            if isinstance(target, Anchor):
                self.add(enc, "dangling", c, target)
                return
            if target is not None:
                self.add(target, role, c)
                return
        self.add(enc, "dangling", c)


def attach(index: TokenIndex, off: OffRegions | None = None) -> Attachment:
    """Attach every comment outside off regions (extern blocks have none)."""
    return _Attacher(index, find_off_regions(index) if off is None else off).run()
