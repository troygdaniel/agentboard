"""install-quickstart x main in redact.py: the branch swapped `re.compile(` for its `_compile(` shim on every shape line, main changed
the shapes themselves since. Take main's shapes and use the shim on them (AGENT-8's xr-install-redact-resolve-main). The shim itself is
defined outside the hunk and merges on its own. (CHANGELOG is the kit's own rule.)"""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import resolve   # noqa: E402

def mains_shapes_with_the_shim(ours, theirs):
    if "_compile(" in theirs and "re.compile(" in ours:
        return ours.replace("re.compile(", "_compile(")
    return ours + theirs

ok = resolve(sys.argv[1], "src/agentboard/redact.py", mains_shapes_with_the_shim)

# doctor.py: main (93c7053) moved the doctor's key scan to repoguard.py and deleted _fake(); the branch edited _fake() to defer to the
# masker. Main's side wins (the empty side of the hunk): repoguard is the one set of rules now.
from pathlib import Path   # noqa: E402
if "<<<<<<<" in (Path(sys.argv[1]) / "src/agentboard/doctor.py").read_text():
    ok = resolve(sys.argv[1], "src/agentboard/doctor.py", lambda ours, theirs: ours if "def _fake(" in theirs else ours + theirs) and ok

# The branch replaces `import tomllib` with its reader (`from . import tomlread`) in every module. Code main added since (store._roster,
# anything else that says tomllib.) merges without a conflict and then fails at run time with NameError: swap those uses to the reader,
# which has the same loads() and TOMLDecodeError. (This was the single cause of 60-odd failures in the night's combined tree.)
from pathlib import Path   # noqa: E402
for py in sorted((Path(sys.argv[1]) / "src" / "agentboard").glob("*.py")):
    t = py.read_text()
    if "tomllib." in t and "import tomllib" not in t and "from . import tomlread" in t:
        py.write_text(t.replace("tomllib.", "tomlread."))
        print(f"{py.name}: tomllib. -> tomlread. ({t.count('tomllib.')} use(s))")
sys.exit(0 if ok else 1)
