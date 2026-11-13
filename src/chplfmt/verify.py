"""Verifier: the output must mean exactly what the input meant.

Checks, in order: `reparse`, `ast`, `tokens`, `comments`, `verbatim`. Each
rule (`chplfmt.rules`) describes what it may change; the verifier applies the
enabled ones to both sides before comparing.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from functools import cache
from typing import Any, cast

from chplfmt._chapel import ParseResult, chapel, parse_text
from chplfmt.comments import expected_comment_text
from chplfmt.config import FormatOptions
from chplfmt.errors import VerificationError
from chplfmt.lexer import LexError
from chplfmt.offregions import verbatim_spans
from chplfmt.rules import RULES
from chplfmt.source import Pos, SourceText
from chplfmt.tokens import Node, TokenIndex, children

CHECKS = ("reparse", "ast", "tokens", "comments", "verbatim")
UNKNOWN: Pos = (0, 0)

# Semantic attributes per AST class name (inherited along the MRO). Every
# public method of every AstNode subclass is listed in exactly one table;
# tests/unit/test_verify.py fails on classes or methods missing here.
_VALUES: dict[str, tuple[str, ...]] = {
    "AnonFormal": ("intent",),
    "Array": ("has_trailing_comma", "is_associative"),
    "Attribute": ("name",),
    "AttributeGroup": ("is_unstable", "is_deprecated"),
    "BoolLiteral": ("value",),
    "BracketLoop": ("is_maybe_array_type",),
    "Catch": ("has_parens_around_error",),
    "Conditional": (
        "then_block_style",
        "has_else_block",
        "else_block_style",
        "is_expression_level",
    ),
    "Decl": ("linkage", "visibility"),
    "Domain": ("used_curly_braces",),
    "Dot": ("field",),
    "FnCall": ("used_square_brackets",),
    "For": ("is_param",),
    "Formal": ("is_this",),
    "Function": (
        "is_anonymous",
        "is_inline",
        "is_method",
        "is_override",
        "is_parenless",
        "is_primary_method",
        "kind",
        "num_formals",
        "return_intent",
        "throws",
    ),
    "FunctionSignature": ("is_parenless", "kind", "return_intent", "throws"),
    "Identifier": ("name",),
    "Implements": ("interface_name", "is_expression_level"),
    "Import": ("visibility",),
    "Include": ("name", "is_prototype", "visibility"),
    "IndexableLoop": ("is_expression_level",),
    "Interface": ("is_formal_list_explicit",),
    "Label": ("name",),
    "Loop": ("block_style",),
    "Module": ("kind",),
    "NamedDecl": ("name",),
    "New": ("management",),
    "OpCall": ("is_binary_op", "is_unary_op", "op"),
    "PrimCall": ("prim",),
    "Range": ("op_kind",),
    "SimpleBlockLike": ("block_style",),
    "StringLikeLiteral": ("quote_style",),
    "Try": ("is_expression_level", "is_try_bang"),
    "TupleDecl": ("intent_or_kind",),
    "Use": ("visibility",),
    "VarLikeDecl": ("storage_kind", "intent"),
    "Variable": ("is_config", "is_field", "kind"),
    "VisibilityClause": ("limitation_kind",),
    "When": ("block_style", "is_otherwise"),
}
# Optional child accessors: only whether the child is present (its role).
_PRESENT: dict[str, tuple[str, ...]] = {
    "AnonFormal": ("type_expression",),
    "Begin": ("with_clause",),
    "Break": ("target",),
    "Catch": ("target",),
    "Cobegin": ("with_clause",),
    "Continue": ("target",),
    "Decl": ("linkage_name",),
    "EnumElement": ("init_expression",),
    "ForwardingDecl": ("expr",),
    "Function": ("body", "return_type", "this_formal", "where_clause"),
    "FunctionSignature": ("return_type", "this_formal"),
    "Implements": ("type_ident",),
    "IndexableLoop": ("index", "with_clause"),
    "Local": ("condition",),
    "Range": ("lower_bound", "upper_bound"),
    "Return": ("value",),
    "Serial": ("condition",),
    "Try": ("body",),
    "TupleDecl": ("init_expression", "type_expression"),
    "VarArgFormal": ("count",),
    "VarLikeDecl": ("init_expression", "type_expression"),
    "Yield": ("value",),
}
# Iterator accessors: how many children play that role.
_COUNTS: dict[str, tuple[str, ...]] = {
    "AggregateDecl": ("inherit_exprs",),
    "Cobegin": ("task_bodies",),
    "Function": ("lifetime_clauses",),
    "FunctionSignature": ("formals",),
    "Interface": ("formals",),
    "Manage": ("managers",),
    "Select": ("when_stmts",),
    "Try": ("handlers",),
    "TupleDecl": ("decls",),
    "VisibilityClause": ("limitations",),
    "When": ("case_exprs",),
}
# Compared another way (`_special_attrs`).
_SPECIAL: dict[str, tuple[str, ...]] = {
    "Attribute": ("actuals",),
    "FnCall": ("actuals",),
    "ImagLiteral": ("text",),
    "IntLiteral": ("text",),
    "RealLiteral": ("text",),
    "StringLikeLiteral": ("value",),
    "UintLiteral": ("text",),
}
# Children, locations, resolution, and derived values.
_IGNORED: dict[str, tuple[str, ...]] = {
    "AstNode": (
        "dump",
        "tag",
        "attribute_group",
        "location",
        "parent",
        "parent_symbol",
        "parent_module",
        "pragmas",
        "unique_id",
        "scope",
        "creates_scope",
        "type",
        "called_fn",
        "resolve",
        "scope_resolve",
        "resolve_via",
        "block_header",
        "curly_braces_location",
        "paren_location",
    ),
    "AggregateDecl": ("decls_or_comments",),
    "Array": ("exprs",),
    "As": ("symbol", "rename"),
    "AttributeGroup": ("get_attribute_named",),
    "Call": (
        "actuals",
        "num_actuals",
        "actual",
        "called_expression",
        "formal_actual_mapping",
    ),
    "Catch": ("body",),
    "Comment": ("text",),
    "Conditional": (
        "condition",
        "then_block",
        "then_stmts",
        "num_then_stmts",
        "then_stmt",
        "then_keyword_location",
        "else_block",
        "else_stmts",
        "num_else_stmts",
        "else_stmt",
        "else_keyword_location",
    ),
    "Delete": ("exprs",),
    "DoWhile": ("condition",),
    "Domain": ("exprs",),
    "Dot": ("field_location", "receiver", "to_node"),
    "EnumElement": ("assigned_value",),
    # `#line N "<temp path>"` + text; the verbatim check compares the text.
    "ExternBlock": ("code",),
    "Function": (
        "formals",
        "formal",
        "throws_location",
        "initial_signature",
        "template_signature",
    ),
    "Identifier": ("to_node", "refers_to_builtin"),
    "Implements": ("interface_expr",),
    "Import": ("visibility_clauses",),
    "Include": ("to_node", "name_location"),
    "IndexableLoop": ("iterand",),
    "Init": ("target",),
    "Interface": ("stmts",),
    "Label": ("loop",),
    "Loop": ("body", "header_location"),
    "Module": ("find_test_functions", "find_unittest_main"),
    "NamedDecl": ("name_location", "header_location"),
    "New": ("type_expression",),
    "On": ("destination",),
    "Reduce": ("iterand", "op"),
    "ReduceIntent": ("op",),
    "Require": ("exprs",),
    "Scan": ("iterand", "op"),
    "Select": ("exprs",),
    "SimpleBlockLike": ("stmts", "num_stmts", "stmt"),
    "Throw": ("error_expression",),
    "Use": ("visibility_clauses",),
    "VisibilityClause": ("symbol",),
    "When": ("body",),
    "While": ("condition",),
    "WithClause": ("exprs",),
}
ATTRIBUTE_TABLES = (_VALUES, _PRESENT, _COUNTS, _SPECIAL, _IGNORED)
# AstNode subclasses that add no methods (all attributes are inherited).
NO_OWN_ATTRS = frozenset(
    {
        *("ArrayRow", "Block", "BytesLiteral", "Class", "Coforall", "Defer"),
        *("EmptyStmt", "Enum", "ErroneousExpression", "Forall", "Foreach", "Let"),
        *("Literal", "Match", "MatchCase", "MultiDecl", "Record", "StringLiteral"),
        *("Sync", "TaskVar", "Tuple", "TypeDecl", "TypeQuery", "Union", "Zip"),
    }
)


@dataclass(frozen=True)
class _Ignore:
    attrs: frozenset[str]
    empty_stmts: bool


# AST equivalence


_VALUE, _PRESENT_KIND, _COUNT = 0, 1, 2
_Step = tuple[str, int, Callable[[Node], Any]]


@cache
def _plan(cls: type) -> tuple[tuple[str, str], ...]:
    plan: list[tuple[str, str]] = []
    for base in reversed(cls.__mro__):
        name = base.__name__
        plan += [("value", m) for m in _VALUES.get(name, ())]
        plan += [("present", m) for m in _PRESENT.get(name, ())]
        plan += [("count", m) for m in _COUNTS.get(name, ())]
    return tuple(plan)


_KIND_CODES = {"value": _VALUE, "present": _PRESENT_KIND, "count": _COUNT}


@cache
def _steps(cls: type, ignored: frozenset[str]) -> tuple[tuple[_Step, ...], bool, bool]:
    """`_plan` with unbound methods, plus whether `cls` is a Literal / has actuals."""
    steps = tuple(
        (m, _KIND_CODES[kind], cast(Callable[[Node], Any], getattr(cls, m)))
        for kind, m in _plan(cls)
        if m not in ignored
    )
    return (
        steps,
        issubclass(cls, chapel.Literal),
        issubclass(cls, (chapel.FnCall, chapel.Attribute)),
    )


def _actual_names(node: chapel.FnCall | chapel.Attribute) -> tuple[str | None, ...]:
    actuals = cast(
        Iterable[object],
        node.actuals(),  # pyright: ignore[reportUnknownMemberType]
    )
    names: list[str | None] = []
    for a in actuals:
        if isinstance(a, tuple):
            names.append(cast(str, a[0]))  # pyright: ignore[reportUnknownArgumentType]
        else:
            names.append(None)
    return tuple(names)


def semantic_attrs(
    node: Node, index: TokenIndex, ignored: frozenset[str] = frozenset()
) -> tuple[tuple[str, object], ...]:
    """The attributes of `node` that formatting must not change."""
    steps, is_literal, has_actuals = _steps(type(node), ignored)
    attrs: list[tuple[str, object]] = []
    for method, kind, fn in steps:
        value = fn(node)
        if kind == _PRESENT_KIND:
            value = value is not None
        elif kind == _COUNT:
            value = sum(1 for _ in value)
        attrs.append((method, value))
    if is_literal:
        sp = index.node_span(node)
        attrs.append(("token", None if sp is None else index.tokens[sp[0]].text))
    if has_actuals:
        attrs.append(("actual_names", _actual_names(cast(chapel.FnCall, node))))
    return tuple(attrs)


def _kids(node: Node, ignore: _Ignore, index: TokenIndex | None = None) -> list[Node]:
    kids = children(node) if index is None else index.ast_children(node)
    if ignore.empty_stmts:
        return [c for c in kids if not isinstance(c, chapel.EmptyStmt)]
    return kids


Fingerprint = tuple[str, tuple[tuple[str, object], ...], tuple[Any, ...]]


def fingerprint(
    node: Node, index: TokenIndex, ignored: frozenset[str] = frozenset()
) -> Fingerprint:
    """`(kind, semantic_attrs, child fingerprints)` without comments (recursive)."""
    ignore = _Ignore(ignored, False)
    return (
        node.tag(),
        semantic_attrs(node, index, ignored),
        tuple(fingerprint(c, index, ignored) for c in _kids(node, ignore, index)),
    )


def _attrs_equal(
    x: Node, y: Node, ia: TokenIndex, ib: TokenIndex, ignored: frozenset[str]
) -> bool:
    """`semantic_attrs(x) == semantic_attrs(y)` for nodes of the same class."""
    steps, is_literal, has_actuals = _steps(type(x), ignored)
    for _, kind, fn in steps:
        u, v = fn(x), fn(y)
        if kind == _PRESENT_KIND:
            if (u is None) != (v is None):
                return False
        elif kind == _COUNT:
            if sum(1 for _ in u) != sum(1 for _ in v):
                return False
        elif u != v:
            return False
    if is_literal:
        sx, sy = ia.node_span(x), ib.node_span(y)
        tx = None if sx is None else ia.tokens[sx[0]].text
        if tx != (None if sy is None else ib.tokens[sy[0]].text):
            return False
    return not has_actuals or _actual_names(cast(chapel.FnCall, x)) == _actual_names(
        cast(chapel.FnCall, y)
    )


def _compare_ast(
    a: Sequence[Node],
    b: Sequence[Node],
    ia: TokenIndex,
    ib: TokenIndex,
    ignore: _Ignore,
) -> tuple[Node | None, Node | None] | None:
    """The first pair of nodes that differ, in preorder."""
    stack: list[tuple[Sequence[Node], Sequence[Node], Node | None, Node | None]] = [
        (a, b, None, None)
    ]
    kids_a, kids_b = ia.ast_children, ib.ast_children
    empty = chapel.EmptyStmt
    drop_empty = ignore.empty_stmts
    ignored = ignore.attrs
    while stack:
        xs, ys, px, py = stack.pop()
        for k in range(max(len(xs), len(ys))):
            # chapel-py has one class per AST tag.
            if k >= len(xs) or k >= len(ys) or type(xs[k]) is not type(ys[k]):
                return (xs[k] if k < len(xs) else px), (ys[k] if k < len(ys) else py)
        pending: list[
            tuple[Sequence[Node], Sequence[Node], Node | None, Node | None]
        ] = []
        for x, y in zip(xs, ys, strict=True):
            if not _attrs_equal(x, y, ia, ib, ignored):
                return x, y
            kx, ky = kids_a(x), kids_b(y)
            if kx or ky:
                if drop_empty:
                    kx = [c for c in kx if not isinstance(c, empty)]
                    ky = [c for c in ky if not isinstance(c, empty)]
                pending.append((kx, ky, x, y))
        stack.extend(reversed(pending))
    return None


def _node_pos(index: TokenIndex, node: Node | None) -> Pos:
    if node is None:
        return UNKNOWN
    sp = index.node_span(node)
    if sp is not None:
        return index.tokens[sp[0]].start
    start = node.location().start()
    return start if start[0] >= 1 else UNKNOWN


# Token, comment, and verbatim equivalence


def _in_spans(offset: int, spans: Sequence[tuple[int, int]], starts: list[int]) -> bool:
    k = bisect_right(starts, offset) - 1
    return k >= 0 and offset < spans[k][1]


class _Side:
    def __init__(self, index: TokenIndex, removed: set[int]) -> None:
        self.index = index
        self.source = index.source
        self.spans = verbatim_spans(index)
        starts = [s for s, _ in self.spans]
        tokens = index.tokens
        self.code = [
            i
            for i, t in enumerate(tokens[:-1])
            if not t.is_comment and i not in removed
        ]
        self.comments = [
            i
            for i, t in enumerate(tokens)
            if t.is_comment and not _in_spans(t.start_offset, self.spans, starts)
        ]

    def pos(self, seq: list[int], k: int) -> Pos:
        tokens = self.index.tokens
        return tokens[seq[k]].start if k < len(seq) else tokens[-1].start


def _first_difference(xs: Sequence[str], ys: Sequence[str]) -> int | None:
    for k in range(max(len(xs), len(ys))):
        if k >= len(xs) or k >= len(ys) or xs[k] != ys[k]:
            return k
    return None


def _offset_pos(source: SourceText, offset: int) -> Pos:
    return source.pos(min(offset, len(source.text)))


class _Verifier:
    def __init__(
        self, path: str, options: FormatOptions, a: TokenIndex, b: TokenIndex
    ) -> None:
        self.path = path
        self.options = options
        self.ia = a
        self.ib = b
        rules = [r for r in RULES if r.enabled(options)]
        self.ignore = _Ignore(
            frozenset[str]().union(*(n.ignored_attrs for n in rules)),
            any(n.drops_empty_stmts for n in rules),
        )
        self.a = _Side(a, set[int]().union(*(n.removable_tokens(a) for n in rules)))
        self.b = _Side(b, set[int]().union(*(n.removable_tokens(b) for n in rules)))
        self.formatted_lines: tuple[int, int] | None = None

    def fail(self, check: str, input_pos: Pos, output_pos: Pos) -> VerificationError:
        return VerificationError(self.path, check, input_pos, output_pos)

    def check_ast(self) -> None:
        diff = _compare_ast(self.ia.roots, self.ib.roots, self.ia, self.ib, self.ignore)
        if diff is not None:
            raise self.fail(
                "ast", _node_pos(self.ia, diff[0]), _node_pos(self.ib, diff[1])
            )

    def check_tokens(self) -> None:
        ta, tb = self.ia.tokens, self.ib.tokens
        k = _first_difference(
            [ta[i].text for i in self.a.code], [tb[i].text for i in self.b.code]
        )
        if k is not None:
            raise self.fail(
                "tokens", self.a.pos(self.a.code, k), self.b.pos(self.b.code, k)
            )

    def check_comments(self) -> None:
        ta, tb = self.ia.tokens, self.ib.tokens
        tab = self.options.tab_size
        ca, cb = self.a.comments, self.b.comments
        lines = self.formatted_lines
        for k in range(max(len(ca), len(cb))):
            if k < len(ca) and k < len(cb):
                x, y = ta[ca[k]], tb[cb[k]]
                if lines is not None and not lines[0] <= x.start[0] <= lines[1]:
                    if x.text == y.text:
                        continue
                    raise self.fail("comments", self.a.pos(ca, k), self.b.pos(cb, k))
                expected = expected_comment_text(
                    x.text,
                    input_col=self.a.source.display_column(x.start_offset, tab),
                    output_col=self.b.source.display_column(y.start_offset, tab),
                    tab_size=tab,
                    comment_spacing=self.options.comment_spacing,
                )
                if expected == y.text:
                    continue
            raise self.fail("comments", self.a.pos(ca, k), self.b.pos(cb, k))

    def check_verbatim(self) -> None:
        sa, sb = self.a.source, self.b.source
        xs = [sa.text[s:e] for s, e in self.a.spans]
        ys = [sb.text[s:e] for s, e in self.b.spans]
        k = _first_difference(xs, ys)
        if k is None:
            return
        if k < len(xs) and k < len(ys):
            x, y = xs[k], ys[k]
            n = next(
                (i for i, (p, q) in enumerate(zip(x, y, strict=False)) if p != q),
                min(len(x), len(y)),
            )
            raise self.fail(
                "verbatim",
                _offset_pos(sa, self.a.spans[k][0] + n),
                _offset_pos(sb, self.b.spans[k][0] + n),
            )
        raise self.fail(
            "verbatim",
            _offset_pos(sa, self.a.spans[k][0]) if k < len(xs) else UNKNOWN,
            _offset_pos(sb, self.b.spans[k][0]) if k < len(ys) else UNKNOWN,
        )


def verify(
    input_text: str,
    output_text: str,
    path: str,
    options: FormatOptions,
    *,
    input_parse: ParseResult | None = None,
    input_index: TokenIndex | None = None,
    formatted_lines: tuple[int, int] | None = None,
) -> None:
    """Raise `VerificationError` unless `output_text` is a faithful formatting.

    `input_parse` and `input_index` (of `input_text`) are reused when given.
    With `formatted_lines` (range formatting), comments of input lines outside
    that range must be unchanged.
    """
    with ExitStack() as stack:
        out = stack.enter_context(parse_text(output_text, path))
        if out.errors:
            d = out.errors[0]
            raise VerificationError(path, "reparse", UNKNOWN, (d.line, d.col))
        try:
            ib = TokenIndex.build(SourceText.from_text(output_text), out.asts)
        except LexError as e:
            raise VerificationError(path, "reparse", UNKNOWN, e.pos) from e
        if input_index is None:
            inp = input_parse or stack.enter_context(parse_text(input_text, path))
            input_index = TokenIndex.build(SourceText.from_text(input_text), inp.asts)
        v = _Verifier(path, options, input_index, ib)
        v.formatted_lines = formatted_lines
        v.check_ast()
        v.check_tokens()
        v.check_comments()
        v.check_verbatim()
