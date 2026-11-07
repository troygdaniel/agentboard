"""What a running `agentboard serve` was started with, written down so `agentboard doctor` can compare it with its own environment.

A process's environment cannot be read from outside (macOS hides it), so doctor used to answer "is the lock on?" from its OWN shell and
could say PASS while the board's server, started from a LaunchAgent or another terminal, ran without it. The server now writes
`server-<pid>.json` in the board folder when it starts:

    {"pid": 4242, "port": 8765, "started": "2026-11-07T09:30:00", "lockdown": true, "plugins_open": false, "plugins_loaded": []}

Only yes/no answers and plugin names: no value of any environment variable, no path, no secret. Mode 0600 (the folder is private anyway),
written atomically, removed when the server exits normally; one file per pid, so two servers on one board do not overwrite each other.
Files of servers that are gone are forgotten the next time a server starts; doctor only trusts a file whose pid is a running
`agentboard serve`. A diagnostics file must never stop a board: every write here swallows its errors.
"""
import json
import os
import re
from datetime import datetime
from pathlib import Path

from . import lockdown, plugins

PREFIX = "server-"
MAX_BYTES = 4096
_NAME = re.compile(r"[a-z][a-z0-9_-]{0,30}")
_FILE = re.compile(rf"{PREFIX}(\d{{1,10}})\.json")


def path_for(board_dir, pid):
    return Path(board_dir) / f"{PREFIX}{int(pid)}.json"


def record(port, loaded):
    """What this process was started with, as the file will hold it."""
    return {"pid": os.getpid(), "port": int(port), "started": datetime.now().isoformat(timespec="seconds"),
            "lockdown": lockdown.locked(), "plugins_open": plugins.disabled_reason() is None,
            "plugins_loaded": sorted(str(n) for n in (loaded or []))}


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def forget_dead(board_dir):
    """Delete the state files of servers that are no longer running."""
    for p in Path(board_dir).glob(f"{PREFIX}*.json"):
        m = _FILE.fullmatch(p.name)
        if m and not pid_alive(int(m.group(1))):
            try:
                p.unlink()
            except OSError:
                pass


def write(board_dir, port, loaded):
    """Write this server's file. Never raises."""
    try:
        forget_dead(board_dir)
        final = path_for(board_dir, os.getpid())
        tmp = final.with_name(final.name + ".tmp")
        try:
            tmp.unlink()   # a leftover (or a planted link) is removed itself, never written through
        except FileNotFoundError:
            pass
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(record(port, loaded), indent=2))
        os.replace(tmp, final)
    except (OSError, ValueError):
        pass


def remove(board_dir):
    """Delete this server's file (registered to run when the server exits)."""
    try:
        path_for(board_dir, os.getpid()).unlink()
    except OSError:
        pass


def read(board_dir, pid):
    """The recorded state of the server with this pid as a checked dict, or None: no file, not JSON, too big, the wrong shape, or a pid
    that does not match its own file name. The file is data a person could have edited, so every field is checked."""
    p = path_for(board_dir, pid)
    try:
        if p.is_symlink() or p.stat().st_size > MAX_BYTES:
            return None
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(d, dict) or d.get("pid") != pid or not isinstance(d.get("lockdown"), bool) or not isinstance(d.get("plugins_open"), bool):
        return None
    loaded = d.get("plugins_loaded")
    port = d.get("port")
    return {"pid": pid, "lockdown": d["lockdown"], "plugins_open": d["plugins_open"],
            "plugins_loaded": [n for n in loaded if isinstance(n, str) and _NAME.fullmatch(n)][:20] if isinstance(loaded, list) else [],
            "port": port if isinstance(port, int) and not isinstance(port, bool) else None,
            "started": d["started"][:25] if isinstance(d.get("started"), str) else ""}
