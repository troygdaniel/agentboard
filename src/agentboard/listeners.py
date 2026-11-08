"""Who is listening. A Claude Code session that has gone quiet reads nothing on its own: a line the owner types on the board
reaches its inbox and sits there. What wakes it is a command it left running in the background that exits when the line
arrives: `agentboard chat inbox --name X --wait` or `agentboard answer CARD --wait`. While one of those runs it is written here,
`.agentboard/chat-listeners.json`, a list of entries (pid, since, what) per name, so the board can say "AGENT-4 is listening" or
warn that nothing will wake it, and the Stop hook can tell a session that is about to go quiet with no wait running to start one.
Two sessions that answer to one name are two entries (chat-f4): the board shows "2 sessions", a line to the name reaches both, and
when one ends the other still counts as listening; a session removes only its own pid. An older file with one entry per name reads
as a one-entry list.

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
    """{name: [entry, ...]} with only live pids, one key per name whatever the case (the first spelling seen is kept)."""
    out, keys = {}, {}
    for n, recs in d.items():
        recs = recs if isinstance(recs, list) else [recs]   # an older file: one dict per name
        k = keys.setdefault(str(n).lower(), str(n))
        for r in recs:
            if isinstance(r, dict) and alive(r.get("pid")) and not any(x.get("pid") == r.get("pid") for x in out.get(k, [])):
                out.setdefault(k, []).append(r)
    return out


def _key(d, name):
    return next((k for k in d if k.lower() == str(name).lower()), str(name))


def register(board_dir, name, what, pid=None):
    """Record that `name`'s session is waiting (`what`: 'inbox' or 'answer <card>'). Returns the pid written. A second live
    session under the same name is a second entry, not a replacement: see sessions()."""
    pid = pid or os.getpid()
    with locked(board_dir):
        d = _live(_read(board_dir))
        k = _key(d, name)
        d[k] = [r for r in d.get(k, []) if r.get("pid") != pid] + [{"pid": pid, "since": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "what": str(what)[:80]}]
        _write(board_dir, d)
    return pid


def unregister(board_dir, name, pid=None):
    """Take this pid's entry out from under `name`, and only that one: two waits by the same name do not clear each other."""
    pid = pid or os.getpid()
    with locked(board_dir):
        d = _live(_read(board_dir))
        k = _key(d, name)
        if any(r.get("pid") == pid for r in d.get(k, [])):
            d[k] = [r for r in d[k] if r.get("pid") != pid]
            if not d[k]:
                del d[k]
            _write(board_dir, d)


def sessions(board_dir, name):
    """How many live sessions are waiting under `name` (any case)."""
    d = _live(_read(board_dir))
    return len(d.get(_key(d, name), []))


@contextlib.contextmanager
def listening_as(board_dir, name, what):
    pid = register(board_dir, name, what)
    try:
        yield
    finally:
        unregister(board_dir, name, pid)


def listening(board_dir):
    """{name: {'since', 'what', 'sessions'}} for every name with a wait running now: the earliest wait's since and what, and how many
    live sessions answer to the name (2 or more is the "N sessions" chip on the board)."""
    out = {}
    for n, recs in _live(_read(board_dir)).items():
        first = min(recs, key=lambda r: str(r.get("since", "")))
        out[n] = {"since": first.get("since", ""), "what": first.get("what", ""), "sessions": len(recs)}
    return out


def is_listening(board_dir, name):
    return any(n.lower() == str(name or "").lower() for n in listening(board_dir))


def read_cursors(board_dir):
    """{name, lower-cased: last seq read}: what `chat inbox` and `answer --wait` wrote when they printed a line (cursors.py)."""
    from . import cursors
    return cursors.read(board_dir)


def receipts(board_dir):
    """What the chat panel needs to say sent / delivered / seen / answered and whether anyone will wake: the cursors (seen), what was
    printed to each name and when (delivered), and the listeners."""
    from . import cursors
    return {**cursors.receipts(board_dir), "listening": listening(board_dir)}
