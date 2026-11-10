// before module
module M /* before brace */ { // after brace
  // first member
  record R { // after R brace
    var x: int; // trailing x

    // between members
    var y: int;
    // after last member
  }
  class E1 { /* inline in empty */ }
  class E2 { // eol in empty
  }
  class E3 {
    // own-line in empty
  }
  class E4 {

    // own-line after blank

    /* second */
  }
  record G /* before brace */
  {
    var z: int;
  }
  class K: /* before parent */ P /* after parent */ { }
} // after module
