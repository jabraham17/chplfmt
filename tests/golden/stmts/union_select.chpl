union U { var x: int; var y: int; }
proc show(u: U) {
  union select u { when x { writeln(u.x); } when y { writeln(u.y); } otherwise { writeln(0); } }
  union select u { when x do writeln(u.x); otherwise do writeln(0); }
  union select u /* selector */ {
    // first arm
    when x /* field */ { writeln(u.x); }
    when y { // inside
      writeln(u.y);
    }
    otherwise /* fallback */ { writeln(0); }
  }
  union select u // selector line
  { when x // field line
    { writeln(u.x); } otherwise // fallback line
    { writeln(0); } }
}