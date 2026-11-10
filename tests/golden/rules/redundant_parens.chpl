// Nested duplicate layers collapse to one.
var a1 = ((x + y)) * z;
var a2 = (((x + y))) * z;
var a3 = f(((x + y)), w);

// Atoms lose their parentheses.
var b1 = (x) + (1) * ("s") + (f(x)) - (A[i]) + (r.field) + (true);
var b2 = ((x)) + f((y), (2.5));
var b3 = -(1) + -(x) + !(flag);
var b4 = (x).foo + (f(x)).bar + (a.b).c;
var b5 = (f(a))(b);
var b6: (int) = 3;
proc p1(arg: (int), arg2 = (5)) { }
var b7 = (1..n) by (2);
var b8 = (lo)..(hi);

// Atoms whose parentheses stay.
var c1 = (f)(x);
var c2 = (a.b)(c);
var c3 = (A)[i];
var c4 = (1).type;
var c5 = (new C()).method();
var c6 = (new C(1)).field;
var c7 = (x: int).foo;
var c8 = (+ reduce A) / n;
var c9 = (1..n) by 2;
var c10 = (x + y) * z;
var c11 = (-x) ** 2;

// Whole statement-level expressions.
var d1 = (x + y);
var d2: int = (x * 2);
const (d3, d4) = (f(x));
d1 = (x + y);
d1 += (x * y);
d1 <<= (n - 1);
var d5 = (new C());
var d6 = (if c then x else y);
var d7 = (+ reduce A);
var d8 = (1..n);

proc p2() {
  return (x + y);
}

iter p3() {
  yield (x + 1);
}

proc p4() throws {
  throw (new Error());
}

if (x > 0) then
  writeln(x);

if (x > 0) {
  writeln(x);
} else if (x < 0) {
  writeln(-x);
}

while (x < 10) do
  x += 1;

do {
  x += 1;
} while (x < 10);

for i in (1..n) do
  writeln(i);

forall i in (D) with (ref s) do
  s += i;

[i in (D)] writeln(i);

select (x + 1) {
  when (1), (2) do
    writeln("small");
  when (3 + 4) do
    writeln("seven");
  otherwise do
    writeln("other");
}

on (Locales[1]) do
  writeln(here);

on (here.parent) do
  writeln(here);

// Open-ended expressions stay in parentheses before a keyword.
if (if a then b else c) then
  writeln(x);

for i in (for j in 1..n do j) do
  writeln(i);

// Not statement-level: the parentheses stay.
writeln((x + y));
f((x + y));
var e1 = g((x + y)) + 1;

// Tuples are never user parentheses.
var t1 = (x, y);
var t2 = (x,);
for (i, j) in zip((A), (B)) do
  writeln(i, j);

// Comments inside parentheses are kept.
var g1 = ( /* c */ x);
var g2 = (x /* d */);
var g3 = (x + // e
          y);

// chplfmt: off
var h1 = ((x));
// chplfmt: on

// `try`: parentheses around it, or right after it, are kept.
proc tries() throws {
  var r1 = try (chplString.strip()): t;
  var r2 = try! (a): t;
  var r3 = (try! f());
  while (try x(1)) { }
  while (try! r.readLine(s)) do f();
}

// Keyword-prefixed operands never glue to the keyword.
proc keywords() throws {
  var c = new (f())();
  for i in(1..n) do f(i);
  on(x) do f();
  select(x) { when(1) do f(); }
  while(x) do f();
  do { f(); } while(x);
  if(x) then f();
  x=(y);
  x = a-(-1);
  x = -(-a);
  throw(e);
  return(x);
}
iter yields() { yield(x); }
