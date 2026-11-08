"""Who is listening. A Claude Code session that has gone quiet reads nothing on its own: a line the owner types on the board
reaches its inbox and sits there. What wakes it is a command it left running in the background that exits when the line
arrives: `agentboard chat inbox --name X --wait` or `agentboard answer CARD --wait`. While one of those runs it is written here,
`.agentboard/chat-listeners.json`, keyed by name with the pid, so the board can say "AGENT-4 is listening" or warn that nothing
will wake it, and the Stop hook can tell a session that is about to go quiet with no wait running to start one.

A pid that is gone is not listening, whatever the file says (a killed wait leaves its entry behind); the file is pruned on the
next write and ignored on read.

Every change is a read-modify-write under one file lock (`.listeners.lock`), written atomically: twenty waits woken by one line
to "all" re-register at the same instant and all twenty survive, and a reader never sees half a file."""
import contextlib
import json
import os
from datetime import datetime
from pathlib import Path

from . import backup

try:
    import fcntl
except ImportError:   # not POSIX: no lock, the writes stay atomic
    fcntl = None

FILE = "chat-listeners.json"


def path(board_dir):
    return Path(board_dir) / FILE


def _read(board_dir):
    try:
        d = json.loads(path(board_dir).read_text())
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(board_dir, d):
    try:
        backup.write_atomic(path(board_dir), json.dumps(d, indent=1), keep_previous=False)
    except OSError:
        pass


@contextlib.contextmanager
def locked(board_dir, what="listeners"):
    """One writer at a time for one of the board's small files: an exclusive lock on `.agentboard/.<what>.lock` for the block.
    Reads outside it are fine (the writes are atomic); a read-modify-write belongs inside."""
    d = Path(board_dir)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f".{what}.lock", "a") as lf:
        if fcntl:
            fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lf, fcntl.LOCK_UN)


def alive(pid):
    """Is a process with this pid running? One we may not signal still counts as running."""
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, TypeError, ValueError, OverflowError):
        return False
    except PermissionError:
        return True
    return True


def _live(d):
    return {n: r for n, r in d.items() if isinstance(r, dict) and alive(r.get("pid"))}


def register(board_dir, name, what, pid=None):
    """Record that `name`'s session is waiting (`what`: 'inbox' or 'answer <card>'). Returns the pid written."""
    pid = pid or os.getpid()
    with locked(board_dir):
        d = _live(_read(board_dir))
        d[str(name)] = {"pid": pid, "since": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "what": str(what)[:80]}
        _write(board_dir, d)
    return pid


def unregister(board_dir, name, pid=None):
    """Take `name`'s entry out, but only the one this pid wrote: two waits by the same name do not clear each other."""
    pid = pid or os.getpid()
    with locked(board_dir):
        d = _read(board_dir)
        rec = d.get(str(name))
        if isinstance(rec, dict) and rec.get("pid") == pid:
            del d[str(name)]
            _write(board_dir, _live(d))


@contextlib.contextmanager
def listening_as(board_dir, name, what):
    pid = register(board_dir, name, what)
    try:
        yield
    finally:
        unregister(board_dir, name, pid)


def listening(board_dir):
    """{name: {'since', 'what'}} for every session whose wait is running now."""
    return {n: {"since": r.get("since", ""), "what": r.get("what", "")} for n, r in _live(_read(board_dir)).items()}


def is_listening(board_dir, name):
    return any(n.lower() == str(name or "").lower() for n in listening(board_dir))


def read_cursors(board_dir):
    """{name, lower-cased: last seq read}: what `chat inbox` and `answer --wait` wrote when they printed a line (cursors.py)."""
    from . import cursors
    return cursors.read(board_dir)


def receipts(board_dir):
    """What the chat panel needs to say delivered / read / answered and whether anyone will wake: the cursors and the listeners."""
    return {"read": read_cursors(board_dir), "listening": listening(board_dir)}
