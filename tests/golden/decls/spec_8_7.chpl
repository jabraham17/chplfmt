proc toHex(tup, param filled = false) where isTuple(tup) {
  // ...
}

proc compute(const ref A: [?D] real, ref B: [D] real, alpha: real,
             beta: real): real throws
where D.rank == 2 {
  // ...
}

proc aVeryLongProcedureNameForDemonstratingTheFallbackLayout(
  param benchmark: Benchmark, img: [] uint(32), ref res: [] uint(8)
) where benchmark == Benchmark.ScalarFloat {
  // ...
}

proc open(stream, format)
where (isOwnedClass(stream) || isSharedClass(stream) ||
       isUnmanagedClass(stream)) && isValidFormat(format) {
  // ...
}

proc numBits(type t) param: int
where t == vec32x8r || t == vec64x4r || t == vec8x32i || t == vec16x16i ||
      t == vec32x8i || t == vec64x4i do
  return 256;

record R {
  proc ref push(in element: eltType) lifetime this < element {
    // ...
  }

  proc init(type eltType, iterable, param parSafe = false)
  where canResolveMethod(iterable, "these") lifetime this < iterable {
    // ...
  }
}
