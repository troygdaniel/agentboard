"""Private by default (sec-data-file-modes).

The board holds card text, chat, review bodies, phone numbers in config.toml and session ids. Only tasks.json, its .bak and the backups
were mode 0600; reports, config.toml, sessions.json, the chat files, run logs and the folders were 0644/0755, and a Mac home folder is
not private either (drwxr-xr-x), so another account on the machine could read them.

* The command line and the server run with umask 077, so every file and folder the board makes from then on is yours alone.
* `tighten_dir` fixes what is already there (the server does it at start, and `agentboard init` for a new board).
* Programs the board starts for you (`claude -p` runs, context-provider commands, the idle chatter's round) get your own umask back, so
  the files they write in your project are made as they always were. Files meant for other tools or people follow your umask too: the
  project's .gitignore and .claude/settings.json, and a summary page you ask for with --html.
* AGENTBOARD_UMASK=022 (any octal) turns it off for a board folder you share on purpose."""
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

ENV = "AGENTBOARD_UMASK"
ORIG_ENV = "AGENTBOARD_ORIG_UMASK"     # the umask the first agentboard process started with, handed down to what it starts
DEFAULT = 0o077


def _override():
    v = os.environ.get(ENV, "").strip()
    try:
        return int(v, 8) if v else None
    except ValueError:
        return None


def tighten_process():
    """umask 077 (or $AGENTBOARD_UMASK) for this process, its threads and anything it starts; remember the one we started with."""
    prev = os.umask(DEFAULT if _override() is None else _override())
    os.environ.setdefault(ORIG_ENV, f"{prev:03o}")   # setdefault: a nested agentboard keeps the very first one
    return prev


def original_umask():
    """Your own umask: the one the first agentboard process started with, or the current one when nothing was tightened."""
    try:
        return int(os.environ[ORIG_ENV], 8)
    except (KeyError, ValueError):
        cur = os.umask(0)
        os.umask(cur)
        return cur


def child():
    """subprocess keyword arguments that give a started program your own umask back (POSIX only)."""
    return {"umask": original_umask()} if os.name == "posix" else {}


@contextmanager
def as_user():
    """For a file meant for other tools or people (the project's .gitignore, .claude/settings.json, a page you ask for): your umask."""
    prev = os.umask(original_umask())
    try:
        yield
    finally:
        os.umask(prev)


def tighten_dir(board_dir):
    """Folders 0700, files no wider than 0700 and never group or other, everything under the board folder; symlinks are left alone.
    Returns how many entries changed. Does nothing under $AGENTBOARD_UMASK (a shared folder on purpose)."""
    if _override() is not None:
        return 0
    root, changed = Path(board_dir), 0

    def fix(p, want):
        nonlocal changed
        try:
            if p.is_symlink():
                return
            cur = stat.S_IMODE(p.lstat().st_mode)
            new = want if p.is_dir() else cur & 0o700
            if cur != new:
                os.chmod(p, new)
                changed += 1
        except OSError:
            pass
    if not root.is_dir():
        return 0
    fix(root, 0o700)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for n in dirnames:
            fix(Path(dirpath) / n, 0o700)
        for n in filenames:
            fix(Path(dirpath) / n, 0o600)
    return changed
