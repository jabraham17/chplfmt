for i in 1..n do writeln(i);
[i in D] A[i] = 0;

for i in 1..n {
  someLongFunctionName(argumentNumberOne, argumentNumberTwo, argumentThree,
                       argumentFour);
}

forall i in D with (ref total, + reduce sum) {
  // ...
}

forall (a, e) in zip(actualValues, expectedValues) with (max reduce maxAbsErr,
                                                         max reduce maxRelErr) {
  // ...
}

forall (pixel, resultPixel) in zip(inputImagePixels, outputImagePixels)
with (ref histogram, + reduce totalBrightness) {
  // ...
}

begin with (ref result) compute(result);
[i in 0..#n with (ref tup)] tup[i] = i;
