"""rel-agent-protocol-3 x the UX stack in cli.py's cmd_update: the branch passes `by=` to store.update, the stack added a note about an
out-of-range percent after the same call. Take the branch's call and keep the stack's note lines."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import resolve   # noqa: E402

def update_call(ours, theirs):
    if "by=os.environ" in theirs:
        rest = "".join(l + "\n" for l in ours.splitlines() if "t = s.update(" not in l)
        return theirs + rest
    return ours + theirs

ok = resolve(sys.argv[1], "src/agentboard/cli.py", update_call)
sys.exit(0 if ok else 1)
