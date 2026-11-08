"""Shared helpers for the resolution scripts: each script gets the clone path as argv[1], edits the conflicted files in place and exits 0;
the kit then checks that no marker is left and commits. Keep every resolution small and literal, so the morning can read it."""
import re
import sys
from pathlib import Path

HUNK = re.compile(r"<<<<<<< [^\n]*\n(.*?)=======\n(.*?)>>>>>>> [^\n]*\n", re.S)


def resolve(clone, rel, fn):
    """Rewrite every conflict hunk of clone/rel with fn(ours, theirs) -> text. Prints what it did."""
    p = Path(clone) / rel
    s = p.read_text()
    s2, n = HUNK.subn(lambda m: fn(m.group(1), m.group(2)), s)
    p.write_text(s2)
    left = s2.count("<<<<<<< ") + s2.count(">>>>>>> ")
    print(f"{rel}: {n} hunk(s) resolved, {left} marker(s) left")
    return left == 0


def both(ours, theirs):
    """Keep both sides, ours first (two additions at the same spot)."""
    return ours + theirs


def union_import(ours, theirs):
    """Two `from .x import a, b` lines that differ: one line with the union of the names."""
    def names(line):
        m = re.match(r"\s*from (\S+) import (.*)", line.strip())
        return (m.group(1), [n.strip() for n in m.group(2).split(",")]) if m else (None, [])
    mod, a = names(ours)
    mod2, b = names(theirs)
    if mod and mod == mod2:
        return f"from {mod} import " + ", ".join(sorted(set(a) | set(b), key=str.lower)) + "\n"
    return ours + theirs
