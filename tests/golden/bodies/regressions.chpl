// try!/try on a statement-level assignment keeps its `;`.
proc f() throws { return 1; }
proc g() throws {
  var x: int;
  try!   x = f();
  try x += f(); // c
  try! f();
  var y = try! f();
}
