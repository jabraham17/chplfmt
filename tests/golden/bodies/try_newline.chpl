proc f() {
  try { f(); } catch e: IllegalArgumentError { handle(e); } catch { halt(); }
  serial c { f(); }
  serial c do f();
  serial c { f(); g(); }
  select x { when 1 do f(); when 2 { g(); h(); } }
}
