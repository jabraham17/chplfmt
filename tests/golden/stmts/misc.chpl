include module S;
include private module P;
require   "foo.h","-lfoo";
require "someVeryLongHeaderName.h", "anotherVeryLongHeaderName.h", "-lsomelibrary";
R   implements I;
implements I( R );
extern { int x; }
extern {
  int   y;
  // comment
}

proc d() {
  delete   a,b;
  delete firstObjectToDelete, secondObjectToDelete, thirdObjectToDelete, fourthObject;
  delete a, /* c */ b;
}

record R {
  proc init() {
    init   this;
  }
}

proc lab() {
  label outer for i in 1..n {
    for j in 1..n {
      if j == i then continue outer;
      if j > i then break outer;
      break;
    }
    continue;
  }
}
