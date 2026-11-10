var   x :int=1 ;
const   ref y=x;
var a=1,b  =  2;
proc scale( ref A:[?D] real,alpha:real,beta:real,gamma:real,delta:real ):real throws{
  A *= alpha;
  return beta;
}

proc toHex(tup,
           param filled=false)
  where isTuple(tup)
{
  // ...
}

proc compute(const ref A: [?D] real,
  ref B: [D] real,
  alpha: real,
  beta: real): real throws where D.rank == 2 {
  // ...
}

proc aVeryLongProcedureNameForDemonstratingTheFallbackLayout(param benchmark: Benchmark, img: [] uint(32), ref res: [] uint(8)) where benchmark == Benchmark.ScalarFloat {
  // ...
}

record R {
  proc ref push(in element: eltType)
      lifetime this < element
  {
    // ...
  }

  proc init(type eltType, iterable, param parSafe = false) where canResolveMethod(iterable, "these") lifetime this < iterable {
    // ...
  }
}
