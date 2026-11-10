module M {
  proc f(x: int) {
    if x > 0 {
      for i in 1..x {
        writeln(i);
      }
    } else {
      select x {
        when 0 do writeln(0);
        otherwise {
          writeln(x);
        }
      }
    }
  }
  record R {
    var a: int;
    proc g() {
      return a;
    }
  }
}
