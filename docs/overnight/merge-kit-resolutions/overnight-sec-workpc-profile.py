"""sec-workpc-profile x the UX stack (both change cli.py's parser setup and the init subcommand, and server.py's import line).
cli.py hunk 1: main's parser lines, with the branch's `profilelib.apply()` call before them. Hunk 2: main's init block, then the
branch's new flags and subcommands (its own `sp = add("init", ...)` line dropped: main's init line stays). server.py: both imports."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import resolve   # noqa: E402

def cli(ours, theirs):
    if "profilelib.apply()" in theirs and "_Parser(" in ours:
        call = "".join(l + "\n" for l in theirs.splitlines() if "profilelib.apply()" in l)
        return call + ours
    if 'add("init"' in ours and 'add("init"' in theirs:
        rest = "".join(l + "\n" for l in theirs.splitlines() if 'add("init"' not in l)
        return ours + rest
    return ours + theirs

def server(ours, theirs):
    return ours + "".join(l + "\n" for l in theirs.splitlines() if "profile as profilelib" in l)

def doctor_imports(ours, theirs):   # main's import line (repoguard and all) plus the branch's `profile as profilelib` line
    from _lib import union_import
    base = "".join(l + "\n" for l in theirs.splitlines() if l.startswith("from . import ") and " as profilelib" not in l)
    extra = "".join(l + "\n" for l in theirs.splitlines() if " as profilelib" in l)
    return (union_import(ours, base) if base else ours) + extra

ok = resolve(sys.argv[1], "src/agentboard/cli.py", cli)
ok = resolve(sys.argv[1], "src/agentboard/server.py", server) and ok
from pathlib import Path   # noqa: E402
if "<<<<<<<" in (Path(sys.argv[1]) / "src/agentboard/doctor.py").read_text():
    ok = resolve(sys.argv[1], "src/agentboard/doctor.py", doctor_imports) and ok
sys.exit(0 if ok else 1)
