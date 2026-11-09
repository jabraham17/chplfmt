import itertools
import random

from chplfmt.api import TextEdit, compute_edits


def _apply(old: str, edits: list[TextEdit]) -> str:
    lines = old.splitlines(keepends=True)
    for e in reversed(edits):
        lines[e.start_line : e.end_line] = [e.new_text]
    return "".join(lines)


def test_identical_text_has_no_edits():
    assert compute_edits("a\nb\n", "a\nb\n") == []


def test_single_changed_line():
    old = "".join(f"{i}\n" for i in range(100)) + "}\n\n" * 50
    new = old.replace("42\n", "x\n")
    assert compute_edits(old, new) == [TextEdit(42, 43, "x\n")]


def test_edits_reproduce_new_text():
    rng = random.Random(7)
    for _ in range(300):
        old = [rng.choice("abcdefgh}") + "\n" for _ in range(rng.randrange(30))]
        new = list(old)
        for _ in range(rng.randrange(6)):
            k = rng.randrange(len(new) + 1)
            if new and rng.random() < 0.5:
                del new[k : k + rng.randrange(1, 4)]
            else:
                new[k:k] = [rng.choice("abxyz}") + "\n"] * rng.randrange(1, 3)
        a, b = "".join(old), "".join(new)
        edits = compute_edits(a, b)
        assert _apply(a, edits) == b
        assert all(e.start_line <= e.end_line for e in edits)
        assert all(x.end_line < y.start_line for x, y in itertools.pairwise(edits))
