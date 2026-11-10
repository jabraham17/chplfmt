// Section 8.5
const total = firstValue * scaleFactor + secondValue * otherScale +
              thirdValue * lastScale;

// Section 8.9
const y = if cond then a else b;
const z = if someLongConditionExpression(withArguments)
             then firstAlternative
             else secondAlternative;

// Spacing for each operator kind
proc spacing() {
  var s = a + b;
  var t = x == y;
  var u = a ** b;
  x = y;
  x += 1;
  a <=> b;
  var assoc = [1 => "one", 2 => "two"];
  var r = 1..n by 2;
  var c = 0..#n;
  var w = 1..<n;
  var o = a..b align 1;
  const D = {1..n} dmapped new blockDist({1..n});
  var sum = + reduce A;
  var m = max reduce (A + B);
  var sc = + scan A;
  var b2 = a & b | c ^ d;
  var sh = a << 2 >> 1;
  var mo = a % b / c;
  var cmp = a <= b && c >= d || e != f;
}

// Unary and postfix operators, casts
proc unary(x: int?, ref y: owned C?) {
  var a = -x;
  var b = !flag;
  var c = ~bits;
  var d = y!;
  var e = -(-x);
  var f = x:int;
  var g = (x + 1):real;
  var h = x:int(8) + 1;
  var i = -a ** 2;
  return f!.value;
}

// Associativity and precedence
proc prec() {
  var p = a ** b ** c;
  var q = (a ** b) ** c;
  var r = a + b * c;
  var s = (a + b) * c;
  var t = a - (b - c);
  var u = a - b - c;
  var v = (a && b) || c;
}

// Comments inside chains
proc comments() {
  var total = first + // after first
              second + third;
  var other = first /* inline */ + second;
}

// Long chains with anchors
proc chains() {
  const ok = isValid(idx) && idx < limit && !visited[idx] &&
             idx != sentinelValue && someOtherCondition(idx);
  var flag: bool;
  flag = isValid(idx) && idx < limit && !visited[idx] && idx != sentinelValue &&
         someOtherCondition(idx);
  flag &&= isValid(idx) && idx < limit && !visited[idx] &&
           idx != sentinelValue && someOtherCondition(idx);
  return isValid(idx) && idx < limit && !visited[idx] &&
         idx != sentinelValue && someOtherCondition(idx);
}

proc parens() {
  const ok = !(scale == 0 || scale == 1 || scale == 2 || scale == 4 ||
               scale == 8 || scale == 16 || scale == 32);
  const mixed = (alphaValue + betaValue + gammaValue + deltaValue +
                 epsilonValue) * scaleFactorValue;
  return (alphaValue + betaValue + gammaValue + deltaValue + epsilonValue +
          zetaValue);
}

// Expression-level if
proc exprIf() {
  const e = if a then b else if c then d else e;
  const f = if someLongConditionExpression(withArguments)
               then firstAlternative
               else if anotherLongConditionExpression(withArguments)
               then secondAlternative
               else thirdAlternative;
  return if someLongConditionExpression(withArguments)
            then firstAlternative
            else secondAlternative;
}

// Expression-level if ending in a bracket type
var wi: if t == complex then nothing else [dim] t;
