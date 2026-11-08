"""visual-polish-3 x main in index.html: one line, the agent thread's head. main (chat-f4) added the `N sessions` chip after the name;
the branch changed the same line's markup. Take the branch's line and put the chip back after the name."""
import sys
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _lib import resolve   # noqa: E402

def head_line(ours, theirs):
    if "${sessionsChip(name)}" in ours and "${sessionsChip(name)}" not in theirs:
        return theirs.replace('<span class="th-name">${esc(name)}</span>', '<span class="th-name">${esc(name)}${sessionsChip(name)}</span>', 1)
    return ours   # a hunk we did not expect: keep main's side and let the kit's marker check decide

ok = resolve(sys.argv[1], "src/agentboard/static/index.html", head_line)
sys.exit(0 if ok else 1)
