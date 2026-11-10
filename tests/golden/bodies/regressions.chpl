// try!/try on a statement-level assignment keeps its `;`.
proc f() throws { return 1; }
proc g() throws {
  var x: int;
  try!   x = f();
  try x += f(); // c
  try! f();
  var y = try! f();
}

// otherwise without `do`
select x {
  when 1 do f();
  otherwise compilerError("a");
}
select y {
  otherwise
    // c
    halt();
}
