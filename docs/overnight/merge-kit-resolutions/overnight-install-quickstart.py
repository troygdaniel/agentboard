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
sys.exit(0 if ok else 1)
