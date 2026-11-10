proc f(x: int) {
  if x > 0 then writeln(x);
  if x > 0 {
    writeln(x);
  }
  if x > 0 { writeln(x); }
  if x > 0 then
    writeln(x);
  if x > 0 then writeln(x); else writeln(-x);
  if x > 0 {
    writeln(x);
  } else {
    writeln(-x);
  }
  for i in 1..x do writeln(i);
  for i in 1..x {
    writeln(i);
  }
  forall i in 1..x with (ref y) do y += i;
  while x > 0 do x -= 1;
  while x > 0 {
    x -= 1;
  }
  on here do writeln(x);
  for i in 1..x {
    if i == 2 then continue;
  }
  if x > 0 {
    // comment
    writeln(x);
  }
  for i in 1..x {
    writeln("a very long string literal that will not fit on one line", i, x);
  }
}
proc g() do return 1;
proc h() { return 2; }
