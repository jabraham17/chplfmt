var a = f( x ,b = 2 );
var a2 = f (x, y) ;
var b = A [i,j];
var b2 = A[ 1..n , 2 ];
var e1 = f();
var e2 = A[];
var e3 = f( );
var cc = c(x=1, y=f(a = 2));
var u = a . b.c;
var ty = x.type;
var mc = a.b(c)[1..n];
var ip = (1, 2)(0);
var t = __primitive( "+" ,1,2);
var t2 = __primitive("=", x, y);

// Keyword-like types and calls.
var c = owned C?;
var d: domain( 2 );
var d2: domain(2, stridable=true);
var e: sync int;
var at: atomic int;
var sh: shared C;
var bo: borrowed C?;
var z = index(D);
var zz: sparse subdomain(D);
var ow = owned (C);

// new
var f1 = new C(1, 2);
var f2 = new owned C(1);
var f3 = new unmanaged C?();
var f4 = new shared  Node(value=1, next=nil);
var f5 = new (owned C)();
var f6 = new R(x=1);
var f7 = new C ( );

// Ranges
var r1 = 1..n;
var r2 = 0..<n;
var r3 = ..;
var r4 = lo..;
var r5 = ..hi;
var r6 = ..<hi;
var r7 = A.domain.low..A.domain.high;

// Reductions
var s1 = + reduce A;
var s2 = max scan A;
var s3 = minloc reduce zip(A, A.domain);

// Let and type queries
var v = let x = 1, y = 2 in x;
proc f(x: ?t, y: [?D] ?eltType) { }
