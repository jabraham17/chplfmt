// Array types: the domain's brackets belong to the BracketLoop.
var A: [1..n, 1..m] int;
proc f(arr) {
  var B: [arr.domain.dim(0).lowBound..#(rows*factor), arr.domain.dim(1).lowBound..#(cols*factor)] arr.eltType;
  return B;
}
