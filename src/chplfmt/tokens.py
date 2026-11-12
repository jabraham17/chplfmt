"""Join dyno AST nodes to the native token and ownership index."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import cache
from typing import cast

from chplfmt import _native
from chplfmt._chapel import chapel
from chplfmt.lexer import LexError, TokenKind
from chplfmt.source import SourceText

Span = tuple[int, int]
Node = chapel.AstNode

_LEAVES = (chapel.Identifier, chapel.Literal)
_BODY_OWNERS = (chapel.Function, chapel.When, chapel.Loop)
_FIRST_PAREN = (
    chapel.Tuple,
    chapel.TupleDecl,
    chapel.Zip,
    chapel.WithClause,
    chapel.PrimCall,
    chapel.Attribute,
    chapel.FunctionSignature,
)
_MAY_HAVE_CURLY = frozenset(
    {
        "Begin",
        "Block",
        "BracketLoop",
        "Class",
        "Cobegin",
        "Coforall",
        "Defer",
        "DoWhile",
        "Enum",
        "For",
        "Forall",
        "Foreach",
        "Function",
        "Interface",
        "Local",
        "Manage",
        "Module",
        "On",
        "Record",
        "Select",
        "Serial",
        "When",
        "While",
    }
)

_CATEGORIES: tuple[tuple[int, type | tuple[type, ...]], ...] = (
    (0, _LEAVES),
    (1, chapel.Block),
    (2, chapel.AttributeGroup),
    (3, chapel.ArrayRow),
    (4, chapel.Module),
    (5, chapel.Formal),
    (6, chapel.FunctionSignature),
    (7, chapel.Attribute),
    (8, chapel.New),
)


@cache
def _category(cls: type) -> int:
    return next((kind for kind, types in _CATEGORIES if issubclass(cls, types)), 9)


def _native_class(cls: type) -> tuple[int, bool, int, bool, int]:
    bracket = next(
        (
            rule
            for rule, types in enumerate(
                (
                    chapel.FnCall,
                    _FIRST_PAREN,
                    chapel.OpCall,
                    chapel.Catch,
                    (chapel.Array, chapel.BracketLoop),
                    chapel.Domain,
                    chapel.VisibilityClause,
                    chapel.Function,
                    chapel.Interface,
                ),
                1,
            )
            if issubclass(cls, cast(type | tuple[type, ...], types))
        ),
        0,
    )
    return (
        _category(cls),
        issubclass(cls, _BODY_OWNERS),
        bracket,
        issubclass(cls, (chapel.Conditional, chapel.IndexableLoop)),
        int(issubclass(cls, chapel.Identifier))
        | (int(issubclass(cls, chapel.EmptyStmt)) << 1)
        | (int(issubclass(cls, chapel.BracketLoop)) << 2)
        | (int(issubclass(cls, (chapel.NamedDecl, chapel.Loop))) << 3)
        | (
            int(
                issubclass(
                    cls,
                    (
                        chapel.Function,
                        chapel.When,
                        chapel.Catch,
                        chapel.Try,
                        chapel.Loop,
                    ),
                )
            )
            << 4
        )
        | (int(issubclass(cls, chapel.SimpleBlockLike)) << 5)
        | (int(cls.__name__ in _MAY_HAVE_CURLY) << 6),
    )


def opaque_ranges(source: SourceText, asts: Iterable[Node]) -> list[tuple[int, int]]:
    """Offsets of every `ExternBlock` (`extern { ... }`), for the lexer."""
    ranges: list[tuple[int, int]] = []
    stack = list(reversed(list(asts)))
    while stack:
        node = stack.pop()
        if isinstance(node, chapel.ExternBlock):
            loc = node.location()
            ranges.append((source.offset(loc.start()), source.offset(loc.end())))
        stack.extend(
            reversed([child for child in node if not isinstance(child, chapel.Comment)])
        )
    return ranges


def children(node: Node) -> list[Node]:
    """The node's children without `Comment` nodes (which have no location)."""
    return [child for child in node if not isinstance(child, chapel.Comment)]


class TokenIndex(_native.NativeIndex):
    """Tokens of one file joined to its AST."""

    @classmethod
    def build(cls, source: SourceText, asts: Sequence[Node]) -> TokenIndex:
        try:
            return cls(source, asts, _native_class, chapel.Comment, chapel.ExternBlock)
        except _native.NativeLexError as error:
            message = error.reason
            if error.char is not None:
                message += f" {error.char!r}"
            raise LexError(source, error.offset, message) from None

    @classmethod
    def build_native(
        cls, source: SourceText, asts: Sequence[Node]
    ) -> _native.NativeIndex:
        return _native.build_index(
            source, asts, _native_class, chapel.Comment, chapel.ExternBlock
        )

    def check_leaves(self) -> list[str]:
        """Every Identifier and literal is exactly one token with matching text."""
        problems: list[str] = []
        for node in self.nodes():
            if not isinstance(node, _LEAVES):
                continue
            loc = node.location()
            where = f"{node.tag()} at {loc.start()}"
            index = self.find_start(loc.start())
            if index is None:
                problems.append(f"{where}: no token starts there")
                continue
            tok = self.tokens[index]
            end = self.find_end(loc.end())
            if end is not None and self.tokens[end].end != loc.end():
                end = None
            if end != index and (end is None or not self.is_wide_identifier(node)):
                problems.append(
                    f"{where}: ends at {loc.end()}, token {tok.text!r} doesn't"
                )
            expected = _leaf_text(node)
            if isinstance(node, chapel.StringLikeLiteral):
                if tok.kind is not TokenKind.STRING or not _string_matches(
                    node, tok.text
                ):
                    problems.append(f"{where}: token {tok.text!r} doesn't match")
            elif expected is not None and tok.text != expected:
                problems.append(f"{where}: token {tok.text!r} != {expected!r}")
        return problems

    def check_ownership(self) -> list[str]:
        """Every code token is owned; brackets are owned in pairs and explained."""
        problems = list(self.problems)
        for index, tok in enumerate(self.tokens):
            if (
                self.owner(index) is None
                and not tok.is_comment
                and tok.kind is not TokenKind.EOF
            ):
                problems.append(f"token {tok.text!r} at {tok.start} has no owner")
            if tok.match is not None and self.owner(index) != self.owner(tok.match):
                problems.append(
                    f"bracket {tok.text!r} at {tok.start} split across owners"
                )
        for node in self.nodes():
            for index in self.unexplained_brackets(node):
                tok = self.tokens[index]
                problems.append(
                    f"{node.tag()}: unexplained {tok.text!r} at {tok.start}"
                )
        return problems


def _leaf_text(node: Node) -> str | None:
    if isinstance(node, chapel.Identifier):
        return node.name()
    if isinstance(node, chapel.BoolLiteral):
        return "true" if node.value() else "false"
    if isinstance(
        node,
        (chapel.IntLiteral, chapel.UintLiteral, chapel.RealLiteral, chapel.ImagLiteral),
    ):
        return node.text()
    return None


_ESCAPES = {
    "'": "'",
    '"': '"',
    "?": "?",
    "\\": "\\",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\n": "\n",
}


def string_value(token_text: str) -> tuple[str, bytes]:
    """Decode a STRING token as dyno does: its quote style and value bytes."""
    body = token_text[1:] if token_text[0] == "b" else token_text
    quote = body[:3] if body[:3] in ('"""', "'''") else body[0]
    inner = body[len(quote) : -len(quote)]
    if len(quote) == 3:
        return quote, inner.encode("utf-8")
    out = bytearray()
    index = 0
    while index < len(inner):
        ch = inner[index]
        if ch != "\\":
            out += ch.encode("utf-8")
            index += 1
            continue
        esc = inner[index + 1]
        index += 2
        if esc == "x":
            digits = ""
            while (
                len(digits) < 2
                and index < len(inner)
                and inner[index] in "0123456789abcdefABCDEF"
            ):
                digits += inner[index]
                index += 1
            out.append(int(digits, 16))
        else:
            out += _ESCAPES[esc].encode("utf-8")
    return quote, bytes(out)


def _string_matches(node: chapel.StringLikeLiteral, text: str) -> bool:
    is_bytes = text[0] == "b"
    if is_bytes != isinstance(node, chapel.BytesLiteral):
        return False
    try:
        quote, value = string_value(text)
    except (KeyError, ValueError, IndexError):
        return False
    if quote != node.quote_style():
        return False
    try:
        return node.value().encode("utf-8") == value
    except UnicodeDecodeError:
        return True
