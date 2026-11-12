"""Native document IR and constructors."""

from chplfmt._native import (
    ALL_LINES as ALL_LINES,
)
from chplfmt._native import (
    EMPTY as EMPTY,
)
from chplfmt._native import (
    FIRST_LINE as FIRST_LINE,
)
from chplfmt._native import (
    Check as Check,
)
from chplfmt._native import (
    Doc,
)
from chplfmt._native import (
    DocKind as DocKind,
)
from chplfmt._native import (
    GroupId as GroupId,
)
from chplfmt._native import (
    align as align,
)
from chplfmt._native import (
    break_parent as break_parent,
)
from chplfmt._native import (
    column_text as column_text,
)
from chplfmt._native import (
    concat as concat,
)
from chplfmt._native import (
    conditional_group as conditional_group,
)
from chplfmt._native import (
    dump as dump,
)
from chplfmt._native import (
    fill as fill,
)
from chplfmt._native import (
    flatten as flatten,
)
from chplfmt._native import (
    group as group,
)
from chplfmt._native import (
    hardline as hardline,
)
from chplfmt._native import (
    if_break as if_break,
)
from chplfmt._native import (
    indent as indent,
)
from chplfmt._native import (
    line as line,
)
from chplfmt._native import (
    line_suffix as line_suffix,
)
from chplfmt._native import (
    literalline as literalline,
)
from chplfmt._native import (
    on_render as on_render,
)
from chplfmt._native import (
    softline as softline,
)
from chplfmt._native import (
    suffix_break as suffix_break,
)
from chplfmt._native import (
    text as text,
)
from chplfmt._native import (
    trailing_comment as trailing_comment,
)
from chplfmt._native import (
    verbatim as verbatim,
)

type DocLike = Doc | str
