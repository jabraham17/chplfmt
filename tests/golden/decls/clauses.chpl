record R {
  proc separateLines(type eltType, iterable) where canResolveMethod(iterable, "theseAreLong") lifetime this < iterable, this < eltType {
  }
  proc ref lifetimes(x, y) lifetime this < x, this < y { }
  proc returnLifetime(x) lifetime return x { }
  proc anotherVeryLongProcedureNameForDemonstratingTheFallbackLayoutOk(param a: int) where a == 1 lifetime this < a { }
  proc anotherVeryLongProcedureNameForDemonstratingTheFallbackLayoutOk(param b: int) where b == someLongParamValueForTesting lifetime this < b, this < somethingElse { }
}
