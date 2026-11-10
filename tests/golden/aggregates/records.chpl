record Point:writeSerializable{
  var x, y: real;


  proc norm() do return sqrt(x ** 2 + y ** 2);
}
class C : Parent, I1 {
  var a: int;
  record Nested {
    class Deeper { var z: int; }
  }
}
union U { var i: int; var r: real; }
class Empty {}
record Empty2 {

}
extern record ER { }
extern "c_name" record ER2 { var f: int; }
class AVeryLongClassName: FirstInterfaceName, SecondInterfaceName, ThirdInterfaceName, FourthOne {
  var x: int;
}
interface I(T) { }
interface J {
  proc Self.f();
}
