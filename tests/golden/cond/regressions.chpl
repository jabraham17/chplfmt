proc f() {
  // A comment after `else` forces braces but keeps `} else {`.
  if this.hasPosNegUnitStride() then
    return _low;
  else
    // Adjust _low upward.
    return helpAlignLow(_low, _alignment, stride);
}

// comments after `then` and before an `else` branch
proc f(m, n) {
  return
    if true then //if cond then
      if isUintType(m.type)
      then temp
      else ( if temp >= 0 then temp else temp + n )
    else
      // n < 0
      ( if temp <= 0 then temp else temp + n );
}
