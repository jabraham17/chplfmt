proc (union).getActiveIndex() {
  return 1;
}

record R {
  type K, V;
}

proc f() param do
  // own-line comment after do
  return 1;

proc g() do // end-of-line comment after do
  return 1;

proc h() do /* block */ return 1;

proc k() {
  const a = 1,
        r1 = if a > 0
             then a
             else a + 1,
        r2 = if a > 1
             then a
             else a + 2;
}

const a = 1, r1 = if a > 0
  then a
     else 1, r2 = 3;
