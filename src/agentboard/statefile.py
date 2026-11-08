"""The small JSON state files beside tasks.json (chat cursors, listeners, sessions, hour counts): one way to read, write and update them.

Every write is atomic (a temp file in the same folder, flushed, renamed over the old one), so a crash or a kill -9 leaves the old file
or the new one, never half of either. An update takes a lock (flock on <file>.lock, where the platform has it) around read-modify-write,
so two agents recording their cursor at the same moment lose nothing. A file that is not JSON is read as empty with one plain line
saying so (state, unlike the board, is rebuilt from use: the next write replaces it), and `agentboard verify` names such files, along
with temp files an interrupted write left behind; the board's next save removes those."""
import contextlib
import json
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:   # a platform without flock: the write is still atomic; two writers at the same instant may lose one update
    fcntl = None

from . import backup

STATE_FILES = ("chat-cursors.json", "chat-listeners.json", "sessions.json")   # the board's own state files (a plugin's are its own)
STALE_TMP_S = 600   # a temp file older than this belongs to no live write


def read(path, default=None):
    """(data, problem). A missing file is (default, ''). One that is unreadable or not JSON is (default, one line naming it)."""
    path = Path(path)
    empty = {} if default is None else default
    try:
        text = path.read_text()
    except FileNotFoundError:
        return empty, ""
    except OSError as e:
        return empty, f"{path.name} is unreadable ({e.__class__.__name__}); it is read as empty"
    try:
        return json.loads(text), ""
    except ValueError as e:
        return empty, f"{path.name} is not valid JSON ({e}); it is read as empty until the next write replaces it"


def load(path, default=None):
    """The file's data, or `default` ({} by default) when it is missing, unreadable or not JSON."""
    return read(path, default)[0]


def write(path, data, indent=None):
    """Atomic and flushed: a temp file in the same folder, renamed over the old one."""
    backup.write_atomic(Path(path), json.dumps(data, indent=indent), keep_previous=False)


@contextlib.contextmanager
def locked(path):
    """An exclusive lock on <file>.lock for a read-modify-write of that file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f"{path}.lock", os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0), 0o600)
    try:
        if fcntl:
            fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fcntl:
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def update(path, fn, default=None, indent=None):
    """Locked read-modify-write: `fn(data)` changes the data in place, or returns the new value; the result is written atomically and
    returned. Two processes updating the same file take turns, so neither overwrites the other's change."""
    with locked(path):
        data = load(path, {} if default is None else default)
        out = fn(data)
        if out is not None:
            data = out
        write(path, data, indent)
        return data


def stray_temps(folder, older_than_s=STALE_TMP_S, now=None):
    """Temp files an atomic write left behind when its process died between the write and the rename (.<name>-xxxx.tmp, .snap-xxxx.tmp),
    older than `older_than_s` seconds, so a write in flight right now is never touched."""
    now = time.time() if now is None else now
    out = []
    try:
        for p in Path(folder).iterdir():
            if p.name.startswith(".") and p.name.endswith(".tmp") and p.is_file():
                with contextlib.suppress(OSError):
                    if now - p.stat().st_mtime >= older_than_s:
                        out.append(p)
    except OSError:
        pass
    return sorted(out)


def sweep_temps(folder, older_than_s=STALE_TMP_S, now=None):
    """Remove the stray temp files in `folder`; returns the ones removed. Never raises."""
    gone = []
    for p in stray_temps(folder, older_than_s, now):
        with contextlib.suppress(OSError):
            p.unlink()
            gone.append(p)
    return gone


def repair(board_dir, now=None):
    """`agentboard verify --fix`: sweep the leftover temp files now (a minute old or more, so a write in flight is never touched) and set each
    state file that is not JSON aside as <name>.broken-<stamp>, so the next write starts fresh and nothing is lost for a look. Returns the
    lines saying what was done."""
    board_dir = Path(board_dir)
    done = []
    for p in sweep_temps(board_dir, 60, now) + sweep_temps(board_dir / "backups", 60, now):
        done.append(f"removed {p.name} (a temp file from an interrupted write)")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    for name in STATE_FILES:
        p = board_dir / name
        if p.exists() and read(p)[1]:
            aside = board_dir / f"{name}.broken-{stamp}"
            with contextlib.suppress(OSError):
                os.replace(p, aside)
                done.append(f"set {name} aside as {aside.name} (not valid JSON); it is rebuilt from use")
    return done


def problems(board_dir, now=None):
    """What `agentboard verify` reports about the state files: each one that is not JSON, and the leftover temp files, as plain lines."""
    board_dir = Path(board_dir)
    out = []
    for name in STATE_FILES:
        _data, why = read(board_dir / name)
        if why:
            out.append(why)
    stray = stray_temps(board_dir, now=now) + stray_temps(board_dir / "backups", now=now)
    if stray:
        names = ", ".join(p.name for p in stray[:3]) + (", ..." if len(stray) > 3 else "")
        out.append(f"{len(stray)} leftover temp file{'s' if len(stray) != 1 else ''} from an interrupted write ({names}); the next save removes them")
    return out
