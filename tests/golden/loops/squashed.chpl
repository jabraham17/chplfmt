for i in 1..n {writeln(i);}
[i in D] {A[i] = 0;}
for i in 1..n do someLongFunctionName(argumentNumberOne, argumentNumberTwo, argumentThree, argumentFour);
forall i in D with(ref total,+ reduce sum) {
  // ...
}
forall (a,e) in zip(actualValues,expectedValues) with (max reduce maxAbsErr, max reduce maxRelErr) {
  // ...
}
forall (pixel,resultPixel) in zip(inputImagePixels,outputImagePixels) with (ref histogram, + reduce totalBrightness) {
  // ...
}
begin with(ref result) compute(result);
[i in 0..#n with(ref tup)] tup[i]=i;
for   param   i   in   1..3   do   f(i);
for (i,j) in {1..3,1..4} do f(i,j);
for 1..n do f();
for x in zip(a,b,c) { g(x); }
coforall loc in Locales do on loc { work(); }
foreach i in D with (ref acc) do acc += i;
while x<3 do x+=1;
while (x < 3) { x += 1; }
do { x += 1; } while x < 10;
do {
  x += 1;
} while (x < 10 && y);
label outer for i in 1..n {
  for j in 1..n { if j == i then continue outer; }
}
for i in D do ;
while true do
  f();
forall i in D with (ref aVeryLongVariableNameNumberOne, ref aVeryLongVariableNameNumberTwo, ref three) {
  f(i);
}
forall elementIndex in someDomainWithAVeryLongName.dim(0) by 2 align 1 with (ref aVeryLongVariableName) do f();
forall idx in someVeryLongFunctionName(argumentNumberOne, argumentNumberTwo, argumentThree) with (ref x) do g();
for i in someVeryLongIterandExpression + anotherVeryLongIterandExpression + yetAnother do
  f(i);
proc p() {
  forall i in 1..10 with (+ reduce s) { s += i; }
}
