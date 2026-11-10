proc f(x: int) {
  return   x ;
}
proc g() {
  return;
}
proc h() {
  return firstOperandValue + secondOperandValue + thirdOperandValue + fourthValue;
}
proc k() {
  return (firstOperandValue + secondOperandValue) * (thirdOperandValue + fourth);
}
proc m(cond: bool) {
  return if cond then someLongFunctionName(argumentOne) else otherFunction(argTwo);
}
proc n() {
  return x; // trailing
}
proc o() {
  return /* before */ x;
}
proc q() {
  return someFunctionWithLongName(argumentNumberOne, argumentNumberTwo, argThree);
}
iter it() {
  yield   1;
  yield firstOperandValue + secondOperandValue + thirdOperandValue + fourthValue;
}
proc t() throws {
  throw   new Error();
}
proc u() throws {
  throw new IllegalArgumentError("a fairly long message that " + "keeps going on");
}
proc lt(ref x: R) ref lifetime return x {
  return x;
}
