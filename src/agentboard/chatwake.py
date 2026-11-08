"""The chat wake file: `.agentboard/chat-wake.json` moves whenever a line is posted (a counter, the time and who the line was for; never
its words). A wait (`chat inbox --wait`) watches that one small file and reads the board only when it moved, so a session wakes within a
second of a line without re-reading the board every second; and a runtime that cannot hold a wait, such as ORCH running on a schedule,
learns in one stat whether anything was posted since it last looked (chat-f7). Never raises into a send."""
import contextlib
import json
import time
from datetime import datetime
from pathlib import Path

from . import backup

WAKE_FILE = "chat-wake.json"
NET_S = 10.0   # a wait re-reads the board this often even when the file has not moved (a line written by an older agentboard, a restored backup)


def path(board_dir):
    return Path(board_dir) / WAKE_FILE


def count(board_dir):
    """How many lines have been posted since the file was first written (0 before)."""
    try:
        d = json.loads(path(board_dir).read_text())
    except (OSError, ValueError):
        return 0
    n = d.get("n") if isinstance(d, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def bump(board_dir, to=None, now=None):
    """A line was posted: move the file. `to` is the name it was for (or 'all'), so a reader with one stat knows whether to bother."""
    with contextlib.suppress(OSError, ValueError, TypeError):
        d = {"n": count(board_dir) + 1, "at": (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S"), "to": str(to or "all")[:40]}
        backup.write_atomic(path(board_dir), json.dumps(d), keep_previous=False)


def sleep_until_change(board_dir, interval=1.0, max_s=NET_S, sleep=time.sleep, clock=time.monotonic):
    """Sleep in `interval` steps until the wake file moves or `max_s` has passed (then the caller re-reads the board anyway, as a net).
    Returns whether the file moved."""
    n0, start = count(board_dir), clock()
    while clock() - start < max_s:
        sleep(max(0.0, min(interval, max_s - (clock() - start))))
        if count(board_dir) != n0:
            return True
    return False
