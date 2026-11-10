record R {
  var v: int;
  proc f() { }
  proc ref setV(x: int) { v = x; }
  proc const ref getV() const ref : int { return v; }
  proc paramRet() param { return 1; }
  proc typeRet() type { return int; }
  proc parenless { return v; }
  proc parenlessType type do return int;
  override proc hash(): uint { return 0; }
  iter these() { yield v; }
  iter these(param tag: iterKind) where tag == iterKind.standalone { yield v; }
}
proc R.g() { }
proc (R).h() { }
proc type R.make(): R { return new R(); }
inline proc fast(x: int): int do return x;
proc mayThrow() throws { }
export proc exported(x: int): int { return x; }
extern proc cfunc(x: c_int): c_int;
extern "real_name" proc renamed(): void;
operator +(a: R, b: R): R { return a; }
operator R.==(a: R, b: R): bool { return true; }
operator :(x: int, type t: R) { return new R(); }
iter count(n: int): int { for i in 1..n do yield i; }
proc double(x: int) do return 2 * x;
proc shiftLeft(x: vectorType(eltType, numElts), param shift: int): x.type do return implType(eltType, numElts).shiftLeftImm(x, shift);
proc tooLongBodyEvenAlone(x: int) do return someVeryLongFunctionName(argumentNumberOne, argumentNumberTwo, x);
proc doBlock() do { }
proc   spaced  (  x  :  int  )  :  int  {  return x;  }
const lam = proc(x: int) { return x; };
