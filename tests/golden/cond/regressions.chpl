proc f() {
  // A comment after `else` forces braces but keeps `} else {`.
  if this.hasPosNegUnitStride() then
    return _low;
  else
    // Adjust _low upward.
    return helpAlignLow(_low, _alignment, stride);
}
