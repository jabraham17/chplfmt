from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from chplfmt._chapel import chapel, parse_text
from chplfmt.lexer import TokenKind
from chplfmt.source import SourceText
from chplfmt.tokens import Span, TokenIndex, string_value


@contextmanager
def indexed(text: str) -> Iterator[TokenIndex]:
    with parse_text(text, "t.chpl") as res:
        assert res.errors == []
        idx = TokenIndex.build(SourceText.from_text(text), res.asts)
        assert idx.check_leaves() == []
        assert idx.check_ownership() == []
        yield idx


def find(idx: TokenIndex, kind: type, k: int = 0) -> Any:
    return [n for n in idx.nodes() if isinstance(n, kind)][k]


def texts(idx: TokenIndex, ids: list[int]) -> list[str]:
    return [idx.tokens[i].text for i in ids]


def joined(idx: TokenIndex, span: Span | None) -> str:
    assert span is not None
    return " ".join(t.text for t in idx.tokens[span[0] : span[1] + 1])


def own(idx: TokenIndex, node: Any) -> list[str]:
    return texts(idx, idx.own_tokens(node))


def structural(idx: TokenIndex, node: Any) -> list[str]:
    return texts(idx, idx.structural_brackets(node))


def delimiters(idx: TokenIndex, node: Any) -> list[str]:
    return texts(idx, idx.body_delimiters(node))


# Location lookup


def test_by_start_by_end_and_exact_span() -> None:
    with indexed("var x = 1;\n") as idx:
        assert idx.by_start[(1, 1)] == 0
        assert idx.by_end[(1, 4)] == 0
        assert idx.by_end[(1, 11)] == 4
        var = find(idx, chapel.Variable)
        assert idx.span(var.location()) == (0, 3)
        assert idx.span(((1, 5), (1, 10))) == (1, 3)


def test_span_bisects_off_boundary_positions() -> None:
    with indexed("var xy = 1;\n") as idx:
        # Positions inside tokens select the tokens wholly inside the range.
        assert idx.span(((1, 2), (1, 10))) == (1, 2)
        assert idx.span(((1, 1), (1, 12))) == (0, 4)


def test_span_of_missing_or_empty_location_is_none() -> None:
    with indexed("var x = 1;\n") as idx:
        assert idx.span(((-1, -1), (-1, -1))) is None
        assert idx.span(((1, 1), (1, 1))) is None
        mod = find(idx, chapel.Module)
        assert idx.node_span(mod) == (0, 4)  # implicit module: whole file


def test_next_and_prev_code_skip_comments() -> None:
    with indexed("var x /* a */ = // b\n 1;\n") as idx:
        eq = idx.by_start[(1, 15)]
        assert idx.tokens[eq].text == "="
        assert idx.tokens[idx.next_code(eq)].text == "1"
        assert idx.prev_code(eq) == 1
        assert idx.prev_code(0) is None
        assert idx.tokens[idx.next_code(len(idx.tokens) - 2)].kind is TokenKind.EOF


# Leaf invariant


def test_leaves_are_single_matching_tokens() -> None:
    src = 'var a = 0x1F + 2.5e3 + 3i; var s = "x\\ty" + b\'z\' + """q\n"""; var t = true;\n'
    with indexed(src) as idx:
        for node in idx.nodes():
            if isinstance(node, (chapel.Identifier, chapel.Literal)):
                sp = idx.node_span(node)
                assert sp is not None and sp[0] == sp[1]


@pytest.mark.parametrize(
    ("text", "names"),
    [
        ("var a: owned C?;", ["owned"]),
        ("var a: unmanaged C;", ["unmanaged"]),
        ("proc f(x: borrowed C, y: shared C) {}", ["borrowed", "shared"]),
        ("var d: domain(2);", ["domain"]),
        ("var s: sync int; var t: atomic int;", ["sync", "atomic"]),
        ("var i: index(D);", ["index"]),
        ("var s: sparse subdomain(D);", ["sparse", "subdomain"]),
        ("record R {} R implements hashable;", []),
        ("record R {} implements writeSerializable(R);", ["writeSerializable"]),
    ],
)
def test_wide_identifiers(text: str, names: list[str]) -> None:
    # Dyno gives these called Identifiers the location of the whole call.
    with indexed(text + "\n") as idx:
        wide: list[Any] = [n for n in idx.nodes() if idx.is_wide_identifier(n)]
        assert [n.name() for n in wide] == names
        for n in wide:
            call = idx.parent(n)
            assert isinstance(call, chapel.FnCall)
            assert idx.span(n.location()) == idx.node_span(call)
            assert joined(idx, idx.node_span(n)) == n.name()


def test_wide_identifier_ownership() -> None:
    with indexed("var a: owned C?;\n") as idx:
        call = find(idx, chapel.FnCall)
        owned, q = idx.children(call)
        assert own(idx, call) == []
        assert own(idx, owned) == ["owned"]
        assert isinstance(q, chapel.OpCall)
        assert own(idx, q) == ["?"]
        assert own(idx, find(idx, chapel.Identifier, 1)) == ["C"]


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ('"a\\n\\x41\\\\"', ('"', b"a\nA\\")),
        ("'it\\'s'", ("'", b"it's")),
        ('b"\\xff"', ('"', b"\xff")),
        ('"""a\\n"""', ('"""', b"a\\n")),
        ("'''x'''", ("'''", b"x")),
    ],
)
def test_string_value(token: str, expected: tuple[str, bytes]) -> None:
    assert string_value(token) == expected


# Ownership


def test_function_ownership() -> None:
    src = (
        'pragma "no init"\n@deprecated(since="1.0", notes="x")\n'
        "proc g(x: int, ref y: real = 2.0): int where x > 0 { return x; }\n"
    )
    with indexed(src) as idx:
        fn = find(idx, chapel.Function)
        assert own(idx, fn) == ["proc", "g", "(", ",", ")", ":", "where"]
        assert structural(idx, fn) == ["("]
        group = find(idx, chapel.AttributeGroup)
        assert own(idx, group) == ["pragma", '"no init"']
        attr = find(idx, chapel.Attribute)
        assert own(idx, attr) == [
            "@deprecated",
            "(",
            "since",
            "=",
            ",",
            "notes",
            "=",
            ")",
        ]
        assert structural(idx, attr) == ["("]
        assert own(idx, find(idx, chapel.Formal, 1)) == ["ref", "y", ":", "="]
        body = find(idx, chapel.Block)
        assert own(idx, body) == ["{", "}"]
        assert own(idx, find(idx, chapel.Return)) == ["return", ";"]
        assert joined(idx, idx.node_span(fn)).startswith('pragma "no init" @dep')


def test_conditional_ownership() -> None:
    with indexed("if a then f(1); else { g(2); }\n") as idx:
        cond = find(idx, chapel.Conditional)
        assert own(idx, cond) == ["if", "then", ";", "else"]
        then_block, else_block = (
            k for k in idx.children(cond) if isinstance(k, chapel.Block)
        )
        assert own(idx, then_block) == []
        assert own(idx, else_block) == ["{", ";", "}"]


def test_loop_ownership() -> None:
    src = (
        "for i in 1..10 do writeln(i);\n"
        "forall i in D with (+ reduce s) { s += A[i]; }\n"
        "for (i, j) in zip(A, B) { }\n"
    )
    with indexed(src) as idx:
        assert own(idx, find(idx, chapel.For)) == ["for", "in", "do", ";"]
        assert own(idx, find(idx, chapel.Range)) == [".."]
        assert own(idx, find(idx, chapel.Forall)) == ["forall", "in"]
        with_ = find(idx, chapel.WithClause)
        assert own(idx, with_) == ["with", "(", ")"]
        assert structural(idx, with_) == ["("]
        assert own(idx, find(idx, chapel.ReduceIntent)) == ["reduce", "s"]
        index = find(idx, chapel.FnCall, 1)
        assert structural(idx, index) == ["["]
        assert own(idx, find(idx, chapel.TupleDecl)) == ["(", ",", ")"]
        zip_ = find(idx, chapel.Zip)
        assert own(idx, zip_) == ["zip", "(", ",", ")"]
        assert structural(idx, zip_) == ["("]


def test_aggregate_and_enum_ownership() -> None:
    src = (
        "record R : writeSerializable { var x: int; }\n"
        "class D : C, I { }\n"
        "enum E { a, b = 2, }\n"
    )
    with indexed(src) as idx:
        rec = find(idx, chapel.Record)
        assert own(idx, rec) == ["record", "R", ":", "{", ";", "}"]
        assert structural(idx, rec) == ["{"]
        cls = find(idx, chapel.Class)
        assert own(idx, cls) == ["class", "D", ":", ",", "{", "}"]
        enum = find(idx, chapel.Enum)
        assert own(idx, enum) == ["enum", "E", "{", ",", ",", "}"]
        assert own(idx, find(idx, chapel.EnumElement, 1)) == ["b", "="]


def test_select_and_try_ownership() -> None:
    src = (
        "select x { when 1, 2 do f(); when 3 { g(); } otherwise h(); }\n"
        "try { f(); } catch e: Error { g(); } catch { }\n"
    )
    with indexed(src) as idx:
        sel = find(idx, chapel.Select)
        assert own(idx, sel) == ["select", "{", "}"]
        when1, when2, other = (find(idx, chapel.When, k) for k in range(3))
        assert own(idx, when1) == ["when", ",", "do", ";"]
        assert own(idx, when2) == ["when"]
        assert own(idx, other) == ["otherwise", ";"]
        assert own(idx, find(idx, chapel.Try)) == ["try"]
        catch = find(idx, chapel.Catch)
        assert own(idx, catch) == ["catch"]
        assert own(idx, find(idx, chapel.Variable)) == ["e", ":"]


def test_expression_ownership() -> None:
    src = (
        "var t = (a, b); var u = (a,); var w = x: int;\n"
        "var o = new owned C(1, 2);\n"
        "var r = + reduce A;\n"
    )
    with indexed(src) as idx:
        t, u = find(idx, chapel.Tuple), find(idx, chapel.Tuple, 1)
        assert own(idx, t) == ["(", ",", ")"]
        assert own(idx, u) == ["(", ",", ")"]
        assert structural(idx, t) == ["("]
        assert own(idx, find(idx, chapel.OpCall)) == [":"]
        call = find(idx, chapel.FnCall)
        assert own(idx, call) == ["(", ",", ")"]
        assert structural(idx, call) == ["("]
        new = find(idx, chapel.New)
        assert own(idx, new) == ["new", "owned"]
        assert own(idx, find(idx, chapel.Reduce)) == ["reduce"]


def test_use_extern_and_import_ownership() -> None:
    src = "use M only a;\nextern { int x; }\nimport N.{b, c};\n"
    with indexed(src) as idx:
        assert own(idx, find(idx, chapel.Use)) == ["use", ";"]
        assert own(idx, find(idx, chapel.VisibilityClause)) == ["only"]
        ext = find(idx, chapel.ExternBlock)
        [i] = idx.own_tokens(ext)
        assert idx.tokens[i].kind is TokenKind.OPAQUE
        vis = find(idx, chapel.VisibilityClause, 1)
        assert own(idx, vis) == [".", "{", ",", "}"]
        assert structural(idx, vis) == ["{"]
        assert delimiters(idx, vis) == []


def test_comments_are_owned_by_the_enclosing_node() -> None:
    with indexed("// a\nproc f(x /* b */) { /* c */ }\n") as idx:
        owners = {
            t.text: idx.owner(i) for i, t in enumerate(idx.tokens) if t.is_comment
        }
        assert isinstance(owners["// a"], chapel.Module)
        assert isinstance(owners["/* b */"], chapel.Function)
        assert isinstance(owners["/* c */"], chapel.Block)


def test_comment_outside_explicit_module_has_no_owner() -> None:
    with indexed("/* h */\nmodule M { }\n") as idx:
        assert idx.owner(0) is None
        assert isinstance(idx.owner(1), chapel.Module)


def test_owner_and_children() -> None:
    with indexed("f(1);\n") as idx:
        call = find(idx, chapel.FnCall)
        assert [idx.owner(i) == call for i in range(4)] == [False, True, False, True]
        assert [type(k).__name__ for k in idx.children(call)] == [
            "Identifier",
            "IntLiteral",
        ]
        assert idx.parent(call) == find(idx, chapel.Module)


@pytest.mark.parametrize(
    "text",
    [
        "var x = 1;\n",
        "/* h */\nmodule M { }\n",
        "// first\n// second\nmodule M { }\n",
        'pragma "no init"\n@deprecated(since="1.0")\nproc g(x: int): int { return x; }\n',
        "var a: owned C?; var b = new C(1);\n",
        "if a then f(1); else { g(2); }\n",
        "use M only a;\nextern { int x; }\n",
    ],
)
def test_native_index_phase_3a_parity(text: str) -> None:
    with indexed(text) as idx:
        native = TokenIndex.build_native(idx.source, idx.roots)
        assert native.tokens is native.tokens
        assert native.tokens == idx.tokens
        assert native.problems == idx.problems
        assert native.nodes() == list(idx.nodes())
        assert native.check_leaves() == idx.check_leaves()
        assert native.check_ownership() == idx.check_ownership()
        for node in idx.nodes():
            assert native.span(node.location()) == idx.span(node.location())
            assert native.node_span(node) == idx.node_span(node)
            assert native.header_span(node) == idx.header_span(node)
            assert native.body_span(node) == idx.body_span(node)
            assert native.stmt_span(node) == idx.stmt_span(node)
            assert native.parent(node) == idx.parent(node)
            assert native.children(node) == idx.children(node)
            assert native.ast_children(node) == idx.ast_children(node)
            assert native.own_tokens(node) == idx.own_tokens(node)
            assert native.structural_brackets(node) == idx.structural_brackets(node)
            assert native.user_parens(node) == idx.user_parens(node)
            assert native.parens_around(node) == idx.parens_around(node)
            assert native.unexplained_brackets(node) == idx.unexplained_brackets(node)
            assert native.body_delimiters(node) == idx.body_delimiters(node)
            assert native.is_wide_identifier(node) == idx.is_wide_identifier(node)
        for token, value in enumerate(idx.tokens):
            assert native.owner(token) == idx.owner(token)
            if token < len(idx.tokens) - 1:
                assert native.next_code(token) == idx.next_code(token)
            assert native.prev_code(token) == idx.prev_code(token)
            assert native.find_start(value.start) == idx.by_start[value.start]
            if value.kind is not TokenKind.EOF:
                assert native.find_end(value.end) == idx.by_end[value.end]
        assert native.span(((1, 2), (1, 10))) == idx.span(((1, 2), (1, 10)))
        assert native.find_start((0, 0)) is None
        assert native.find_end((0, 0)) is None


# User parentheses


@pytest.mark.parametrize(
    ("text", "kind", "layers"),
    [
        ("var x = ((a));", chapel.Identifier, 2),
        ("var x = (((a)));", chapel.Identifier, 3),
        ("var x = (a + b) * c;", chapel.OpCall, 1),
        ("f((x));", chapel.Identifier, 1),
        ("f(((x)));", chapel.Identifier, 2),
        ("proc f() { return (x); }", chapel.Identifier, 1),
        ("if (c) then f();", chapel.Identifier, 1),
        ("var x = ((a, b));", chapel.Tuple, 1),
        ("var o: owned (C);", chapel.Identifier, 1),
        ("var e = [i in D] (i * 2);", chapel.OpCall, 1),
        ("var c = (x: int) + 1;", chapel.OpCall, 1),
    ],
)
def test_user_parens(text: str, kind: type, layers: int) -> None:
    with indexed(text + "\n") as idx:
        wrapped = [
            n for n in idx.nodes() if isinstance(n, kind) and idx.parens_around(n)
        ]
        [node] = wrapped
        found = idx.parens_around(node)
        assert len(found) == layers
        sp = idx.node_span(node)
        assert sp is not None
        for k, (i, j) in enumerate(found):
            assert (i, j) == (sp[0] - k - 1, sp[1] + k + 1)
            assert idx.tokens[i].match == j


@pytest.mark.parametrize(
    "text", ["var t = (a, b);", "var t = (a,);", "f(x);", "(a)(1);", "var a = [1];"]
)
def test_not_user_parens(text: str) -> None:
    with indexed(text + "\n") as idx:
        bracketed = (chapel.Tuple, chapel.FnCall, chapel.Array)
        calls = [n for n in idx.nodes() if isinstance(n, bracketed)]
        assert calls
        for node in calls:
            assert idx.structural_brackets(node)
            opens = {i for i, _, _ in idx.user_parens(node)}
            assert not opens & set(idx.structural_brackets(node))


def test_callee_in_parens() -> None:
    with indexed("(a)(1);\n") as idx:
        call = find(idx, chapel.FnCall)
        assert [idx.tokens[i].start for i in idx.structural_brackets(call)] == [(1, 4)]
        assert [(i, j) for i, j, _ in idx.user_parens(call)] == [(0, 2)]


# Body delimiters


@pytest.mark.parametrize(
    ("text", "kind", "expected"),
    [
        ("proc f() { }", chapel.Block, ["{", "}"]),
        ("proc f() do return 1;", chapel.Function, ["do"]),
        ("if c then f(); else g();", chapel.Conditional, ["then"]),
        ("if c { f(); } else { g(); }", chapel.Conditional, []),
        ("for i in 1..3 do f();", chapel.For, ["do"]),
        ("while c do f();", chapel.While, ["do"]),
        ("forall i in D with (ref x) { }", chapel.Block, ["{", "}"]),
        ("on here do f();", chapel.On, ["do"]),
        ("select x { when 1 do f(); }", chapel.When, ["do"]),
        ("select x { when 1 do f(); }", chapel.Select, ["{", "}"]),
        ("cobegin { f(); g(); }", chapel.Cobegin, ["{", "}"]),
        ("record R { }", chapel.Record, ["{", "}"]),
        ("var y = if c then 1 else 2;", chapel.Conditional, []),
        ("var y = for i in 1..3 do i;", chapel.For, []),
        ("var d = {1..2};", chapel.Domain, []),
    ],
)
def test_body_delimiters(text: str, kind: type, expected: list[str]) -> None:
    with indexed(text + "\n") as idx:
        assert delimiters(idx, find(idx, kind)) == expected


def test_else_block_braces_are_body_delimiters() -> None:
    with indexed("if c then f(); else { g(); }\n") as idx:
        blocks = [n for n in idx.nodes() if isinstance(n, chapel.Block)]
        assert [delimiters(idx, b) for b in blocks] == [[], ["{", "}"]]


# Span helpers


def test_function_spans() -> None:
    src = "proc f(x: int): int where x > 0 { return x; }\n"
    with indexed(src) as idx:
        fn = find(idx, chapel.Function)
        assert joined(idx, idx.node_span(fn)) == (
            "proc f ( x : int ) : int where x > 0 { return x ; }"
        )
        assert joined(idx, idx.header_span(fn)) == "proc f ( x : int ) : int"
        assert joined(idx, idx.body_span(fn)) == "{ return x ; }"
        assert idx.stmt_span(fn) == idx.node_span(fn)


def test_do_body_span() -> None:
    with indexed("for i in 1..3 do f(i);\n") as idx:
        loop = find(idx, chapel.For)
        assert joined(idx, idx.header_span(loop)) == "for i in 1 .. 3"
        assert joined(idx, idx.body_span(loop)) == "f ( i )"
        assert joined(idx, idx.stmt_span(loop)) == "for i in 1 .. 3 do f ( i ) ;"


def test_bracket_loop_header_includes_brackets() -> None:
    with indexed("[i in D] f(i);\n") as idx:
        loop = find(idx, chapel.BracketLoop)
        assert joined(idx, idx.header_span(loop)) == "[ i in D ]"


def test_aggregate_body_span() -> None:
    with indexed("class C : P { var x: int; }\n") as idx:
        cls = find(idx, chapel.Class)
        assert joined(idx, idx.header_span(cls)) == "class C : P"
        assert joined(idx, idx.body_span(cls)) == "{ var x : int ; }"


@pytest.mark.parametrize(
    ("text", "kind", "node", "stmt"),
    [
        ("var x = 1;", chapel.Variable, "var x = 1", "var x = 1 ;"),
        ("f(1);", chapel.FnCall, "f ( 1 )", "f ( 1 ) ;"),
        (
            "var (a, b) = t;",
            chapel.TupleDecl,
            "var ( a , b ) = t",
            "var ( a , b ) = t ;",
        ),
        ("proc f() { return 1; }", chapel.Return, "return 1 ;", "return 1 ;"),
        ("x = 1;", chapel.OpCall, "x = 1 ;", "x = 1 ;"),
        ("use M;", chapel.Use, "use M ;", "use M ;"),
        ("var x = 1 /* c */ ;", chapel.Variable, "var x = 1", "var x = 1 /* c */ ;"),
        ("proc f() { };", chapel.Function, "proc f ( ) { }", "proc f ( ) { }"),
    ],
)
def test_stmt_span(text: str, kind: type, node: str, stmt: str) -> None:
    with indexed(text + "\n") as idx:
        n = find(idx, kind)
        assert joined(idx, idx.node_span(n)) == node
        assert joined(idx, idx.stmt_span(n)) == stmt
