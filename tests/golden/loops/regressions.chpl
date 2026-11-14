// Array types: the domain's brackets belong to the BracketLoop.
var A: [1..n, 1..m] int;
proc f(arr) {
  var B: [arr.domain.dim(0).lowBound..#(rows*factor), arr.domain.dim(1).lowBound..#(cols*factor)] arr.eltType;
  return B;
}

// Statement-level bracket loops whose body is only empty statements keep one:
// `[i in D] { }` would parse as an array type.
[i in 1..3] ;
[i in 1..3] { ; }

while false { while false { while false { while false { while false { while false {
  tmp[0..<aSlice.size] = [(key,val) in zip(a.localSlice[aSlice], aVal.localSlice[aSlice])] (key,val);
  // write the local part of b (minus any skipped values) into tmp
  tmp[aSlice.size..#bSlice.size] = [(key,val) in zip(b.localSlice[bSlice], bVal.localSlice[bSlice])] (key,val);

  // add any indices that we need to pull to this locale
  // this not a local slice, but it should (hopefully) take advantage of bulk transfer
  if pullLocal[0] {
    const pullFromASlice = (aDom.last+1)..#numPullLocal;
    tmp[(aSlice.size+bSlice.size)..#(numPullLocal)] = [(key,val) in zip(a[pullFromASlice], aVal[pullFromASlice])] (key,val);
  } else if pullLocal[1] {
    const pullFromBSlice = (bDom.last+1)..#numPullLocal;
    tmp[(aSlice.size+bSlice.size)..#(numPullLocal)] = [(key,val) in zip(b[pullFromBSlice], bVal[pullFromBSlice])] (key,val);
  }
}}}}}}
