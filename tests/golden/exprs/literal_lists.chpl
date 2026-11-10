var l = {1..n,1..m};
var l2 = {1..n};
var l3 = { 1..n, 1..m, };
var m = [1,2,3,];
var m2 = [ 1, 2, 3 ];
var m3 = [1];
var n2 = [1 => "a", 2 => "b"];
var n3 = ["one" => 1, "two" => 2, "three" => 3, "four" => 4, "five" => 5, "six" => 6];
var o = [1,2;3,4];
var o2 = [1, 2, 3;
          4, 5, 6;
            7, 8, 9];
var p = (a,b);
var q = (a,);
var q2 = ( a , );
var q3 = ((a, b), (c, d));

// Comments between elements.
var withComments = [1, // one
                    2, /* two */ 3,
                    // four
                    4];
var argComments = f(alpha, // first
                    beta);
var trailing = [alpha, beta,
                gamma // last
               ];
var longTuple = (firstTupleElementValue, secondTupleElementValue, thirdValue);
var longDomain = {0..<firstDimensionSize, 0..<secondDimensionSize, 0..<third};
var hugeArray = [100000, 200000, 300000, 400000, 500000, 600000, 700000, 800000,
                 900000];
var nestedArrays = [[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12], [13, 14, 15]];
