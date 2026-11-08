"""rel-data-integrity x rel-agent-protocol in cli.py: the branch adds `--fix` to `verify` right where main's watchdog subcommand block
begins. The `--fix` line belongs to the verify parser above the hunk, so it goes first, then the watchdog block."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import resolve   # noqa: E402

def verify_then_watchdog(ours, theirs):
    if 'add("watchdog"' in ours and "--fix" in theirs:
        return theirs + ours
    return ours + theirs

ok = resolve(sys.argv[1], "src/agentboard/cli.py", verify_then_watchdog)
sys.exit(0 if ok else 1)
