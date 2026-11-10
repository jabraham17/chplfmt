proc intents(in a: int, out b: int, inout c: int, ref d: int, const e: int,
             const in f: int, const ref g: int, param h: int, type t) { }

proc defaults(x:int=1,y=2.0,param p:bool=true,type t=int) { }

proc queries(A:[?D] ?t, B: [D] t, ref C: [?D2] t) { }

proc varargs(xs...) { }
proc varargsN(xs: int...3) { }
proc varargsQ(args...?n) { }
proc varargsT(param ps...?k, type ts...) { }

proc alignedBinPack(firstArgument: int, secondArgument: real, thirdArgument: string, fourthArgument: bool) { }

proc returnsAfterBinPack(firstArgument: int, secondArgument: real, thirdArgument: string): int { return 0; }

proc thisIsAnExtremelyLongProcedureNameThatForcesTheBreakAfterParenFallback(alpha: int, beta: int) { }

proc fallbackWithReturnType_______________________________________(alpha: int, beta: int): real throws { return 0.0; }

extern proc fallbackNoBody_________________________________________________(alpha: int, beta: int): real;

proc lineComments(a: int, // the first
                  b: int, // the second
                  c: int) { }

proc blockComments(a: int /* first */, /* second */ b: int) { }

proc ownLineComment(
  // leading
  a: int,
  b: int) { }

proc noFormals() { }
proc noFormalsSpaced(  ) { }
