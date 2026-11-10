var x: int = 1;
const ref y = x;
var a = 1, b = 2;
proc scale(ref A: [?D] real, alpha: real, beta: real, gamma: real,
           delta: real): real throws {
  A *= alpha;
  return beta;
}
