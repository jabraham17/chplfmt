proc f(x: int): int {
  if x > 0 {
    log(x);
    return x;
  } else {
    log(-x);
    return -x;
  }
}

proc g() {
  if done then return;
}
if a then b(); else c();

if isValid(indix) && indix < limit && !visited[indix] &&
   indix != sentinelValue {
  visited[indix] = true;
  visit(indix);
}

if !(scale == 0 || scale == 1 || scale == 2 || scale == 4 || scale == 8 ||
     scale == 16 || scale == 32) then
  halt("bad scale");
