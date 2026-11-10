import time

import pytest

from chplfmt.api import format_text

pytestmark = pytest.mark.perf

_UNIT = """\
// Helper {i}: computes a value.
record R{i} {{
  var x: int;
  var y: real = {i}.0;  // trailing comment
  proc area() {{ return x * y; }}
}}

/* Block comment for p{i}. */
proc p{i}(a: int, b: real, ref c: [] int, const d: string = "s{i}"): int {{
  var total = 0;
  for i in 1..a {{
    if i % 2 == 0 {{
      total += i * {i};
    }} else {{
      total -= foo(i, b, c[i], d.size, someLongName{i}(a, b));
    }}
  }}
  while total > 100 do total /= 2;
  forall j in c.domain with (+ reduce total) {{
    total += c[j];
  }}
  select a {{
    when 1 do writeln("one");
    otherwise writeln("other", a, b, total);
  }}
  return total;
}}

"""


def synthetic(lines: int) -> str:
    unit_lines = _UNIT.count("\n")
    body = "".join(_UNIT.format(i=i) for i in range(lines // unit_lines + 1))
    return "module Perf {\n" + body + "}\n"


def test_format_5000_lines_fast() -> None:
    text = synthetic(5000)
    assert text.count("\n") >= 5000
    start = time.perf_counter()
    format_text(text, path="Perf.chpl")
    elapsed = time.perf_counter() - start
    print(f"\nformat_text on {text.count(chr(10))} lines: {elapsed:.2f}s")
    assert elapsed < 4
