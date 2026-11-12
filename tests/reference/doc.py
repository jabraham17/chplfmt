from chplfmt import _native as native
from reference import ir


def to_native(root: ir.DocLike) -> native.Doc:
    if isinstance(root, str):
        return native.text(root)
    converted: dict[ir.Doc, native.Doc] = {}
    ids: dict[ir.GroupId, native.GroupId] = {}
    stack = [(root, False)]
    while stack:
        doc, ready = stack.pop()
        if doc in converted:
            continue
        if not ready:
            stack.append((doc, True))
            match doc:
                case ir.Concat(parts) | ir.Fill(parts) | ir.ConditionalGroup(parts):
                    children = parts
                case ir.LineSuffix(ir.TrailingComment()):
                    children = ()
                case (
                    ir.Group(contents)
                    | ir.Indent(contents)
                    | ir.Align(contents)
                    | ir.LineSuffix(contents)
                ):
                    children = (contents,)
                case ir.IfBreak(broken, flat):
                    children = (broken, flat)
                case _:
                    children = ()
            stack.extend((child, False) for child in children if child not in converted)
            continue

        def part(child: ir.Doc) -> native.Doc:
            return converted[child]

        def group_id(value: ir.GroupId | None) -> native.GroupId | None:
            if value is None:
                return None
            if value not in ids:
                ids[value] = native.GroupId(value.name)
            return ids[value]

        match doc:
            case ir.Text(s):
                result = native.text(s)
            case ir.Concat(parts):
                result = native.concat(*(part(child) for child in parts))
            case ir.Group(contents, ident, should_break):
                result = native.group(part(contents), group_id(ident), should_break)
            case ir.Indent(contents, n):
                result = native.indent(part(contents), n)
            case ir.Align(contents):
                result = native.align(part(contents))
            case ir.Line(hard, soft, literal):
                result = (
                    native.literalline
                    if literal
                    else (
                        native.hardline
                        if hard
                        else native.softline if soft else native.line
                    )
                )
            case ir.Fill(parts, lazy):
                result = native.fill([part(child) for child in parts], lazy=lazy)
            case ir.IfBreak(broken, flat, ident):
                result = native.if_break(part(broken), part(flat), group_id(ident))
            case ir.LineSuffix(ir.TrailingComment(comment)):
                result = native.trailing_comment(comment)
            case ir.LineSuffix(contents):
                result = native.line_suffix(part(contents))
            case ir.BreakParent():
                result = native.break_parent
            case ir.ConditionalGroup(alts, check):
                result = native.conditional_group(
                    [part(child) for child in alts],
                    native.ALL_LINES if check is ir.ALL_LINES else native.FIRST_LINE,
                )
            case ir.Verbatim(s, bol):
                result = native.verbatim(s, bol)
            case ir.ColumnText(make):
                result = native.column_text(make)
            case ir.SuffixBreak():
                result = native.suffix_break
            case ir.OnRender(fn):
                result = native.on_render(fn)
            case _:
                raise TypeError(f"unsupported doc: {type(doc).__name__}")
        converted[doc] = result
    return converted[root]


def to_reference(root: native.Doc) -> ir.Doc:
    converted: dict[native.Doc, ir.Doc] = {}
    ids: dict[native.GroupId, ir.GroupId] = {}
    stack = [(root, False)]
    while stack:
        doc, ready = stack.pop()
        if doc in converted:
            continue
        kind = doc.kind
        args = doc.unpack()
        if not ready:
            stack.append((doc, True))
            if kind in (
                native.DocKind.CONCAT,
                native.DocKind.FILL,
                native.DocKind.CONDITIONAL_GROUP,
            ):
                children = args[0]
            elif kind in (
                native.DocKind.GROUP,
                native.DocKind.INDENT,
                native.DocKind.ALIGN,
                native.DocKind.LINE_SUFFIX,
            ):
                children = args[:1]
            elif kind is native.DocKind.IF_BREAK:
                children = args[:2]
            else:
                children = ()
            stack.extend((child, False) for child in children if child not in converted)
            continue

        def part(child: native.Doc) -> ir.Doc:
            return converted[child]

        def group_id(value: native.GroupId | None) -> ir.GroupId | None:
            if value is None:
                return None
            if value not in ids:
                ids[value] = ir.GroupId(value.name)
            return ids[value]

        if kind is native.DocKind.TEXT:
            result = ir.text(args[0])
        elif kind is native.DocKind.CONCAT:
            result = ir.concat(*(part(child) for child in args[0]))
        elif kind is native.DocKind.GROUP:
            result = ir.group(part(args[0]), group_id(args[1]), args[2])
        elif kind is native.DocKind.INDENT:
            result = ir.indent(part(args[0]), args[1])
        elif kind is native.DocKind.ALIGN:
            result = ir.align(part(args[0]))
        elif kind is native.DocKind.LINE:
            result = ir.Line(*args)
        elif kind is native.DocKind.FILL:
            result = ir.fill([part(child) for child in args[0]], lazy=args[1])
        elif kind is native.DocKind.IF_BREAK:
            result = ir.if_break(part(args[0]), part(args[1]), group_id(args[2]))
        elif kind is native.DocKind.LINE_SUFFIX:
            result = ir.line_suffix(part(args[0]))
        elif kind is native.DocKind.TRAILING_COMMENT:
            result = ir.TrailingComment(args[0])
        elif kind is native.DocKind.BREAK_PARENT:
            result = ir.break_parent
        elif kind is native.DocKind.CONDITIONAL_GROUP:
            result = ir.conditional_group(
                [part(child) for child in args[0]],
                ir.ALL_LINES if args[1] is native.ALL_LINES else ir.FIRST_LINE,
            )
        elif kind is native.DocKind.VERBATIM:
            result = ir.verbatim(*args)
        elif kind is native.DocKind.COLUMN_TEXT:
            result = ir.column_text(args[0])
        elif kind is native.DocKind.SUFFIX_BREAK:
            result = ir.suffix_break
        elif kind is native.DocKind.ON_RENDER:
            result = ir.on_render(args[0])
        else:
            raise TypeError(f"unsupported doc: {kind}")
        converted[doc] = result
    return converted[root]
