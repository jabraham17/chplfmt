use   IO,Time ;
use Map   only map;
use M2 except a,b;
import Foo.{ a,b };
import Foo.{a as b, c};
use M3   as N;
public  use A;
private import B.c as d;
use M4 only a as b,c;
import X.Y, Z;
use super.M, this.N;
use A only;
use A as _;
use A, /* c */ B;
use A /* after A */, B; // trailing
public use /* lead */ C;
use D only x, // why x
           y;
use LongModuleNameOne, LongModuleNameTwo, LongModuleNameThree, LongModuleNameFour, LongModuleNameFive;
use SomeModule only firstSymbol, secondSymbol, thirdSymbol, fourthSymbol, fifthSymbol;
import SomeModule.{firstSymbol, secondSymbol, thirdSymbol, fourthSymbol, fifthSymbol};
use SomeModule only firstSymbol as one, secondSymbol as two, thirdSymbol as three;

record R {
  var x: int;
  forwarding x except   y,z;
  forwarding x only a;
}
