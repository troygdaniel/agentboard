"""The UX stack tip x main: cli.py's store import line (main added names, the stack added `demo as demolib` above it) and doctor.py's run()
(main calls check_stop_hook, the stack calls check_agents): keep both, main's first."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import both, resolve, union_import   # noqa: E402

def cli_imports(ours, theirs):
    extra = "".join(l + "\n" for l in theirs.splitlines() if not l.startswith("from .store import"))
    mine = "".join(l + "\n" for l in theirs.splitlines() if l.startswith("from .store import"))
    return extra + union_import(ours, mine)

ok = resolve(sys.argv[1], "src/agentboard/cli.py", cli_imports)
ok = resolve(sys.argv[1], "src/agentboard/doctor.py", both) and ok
sys.exit(0 if ok else 1)
