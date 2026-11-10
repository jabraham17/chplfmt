module M {
  record R {
    var x: int;
    proc ref setX(v: int) {
      x = v;
    }
  }

  class C: Base {
    var y = 1;
  }

  enum Color { red, green, blue }

  proc f(a: int, b: int): int where a > 0 {
    if a > b {
      return a;
    } else if a == b {
      return 0;
    } else {
      return b;
    }
  }

  proc g() throws {
    for i in 1..10 {
      writeln(i);
    }
    forall (i, j) in zip(1..3, 4..6) with (+ reduce s) {
      s += i * j;
    }
    while x < 10 {
      x += 1;
    }
    do {
      x -= 1;
    } while x > 0;
    try {
      foo();
    } catch e: IllegalArgumentError {
      writeln(e);
    } catch {
      halt();
    }
    select x {
      when 1 {
        writeln("one");
      }
      otherwise {
        writeln("other");
      }
    }
    on here {
      begin {
        bar();
      }
    }
    {
      var z = 3;
    }
  }
}
