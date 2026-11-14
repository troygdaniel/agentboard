"""Where each session got to in the chat: `.agentboard/chat-cursors.json`, {name: the last seq its session printed}. This is the
one place it is read and written (the CLI, the idle drafter, the receipts and the Stop hook each used to do their own, by exact-case
name, with no lock). The key is the name lower-cased, so `agentboard me --name AGENT-4` and `chat inbox --name agent-4` are one
session; a write takes a file lock and only moves forward; the file is replaced atomically. An older file with mixed-case keys
reads as the highest seq per name.

Two steps (chat-f3). Printing a line is DELIVERED: `deliver()` records the highest seq printed to a name, when, and to which SESSION
(`session_id()`), in `chat-delivered.json`. The name's cursor (SEEN) moves when that session next does anything on the board: a command
that carries the name (`confirm()`), or ANY board command run by the same session (`confirm_session()`), or its next `chat inbox`. A
session is the first ancestor process of the command that is not a shell: the agent runtime, or a terminal tab's login. Time alone is
not the witness (a session that merged a branch and ran a suite for ten minutes, with commands that carry no name, had its handled line
printed again): a delivery that no session of ours has confirmed within RESHOW_S is shown again by the next `chat inbox` only when
that is a DIFFERENT session, or one we cannot identify (the reader that printed it was gone, or never read its output)."""
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

from . import backup, listeners

FILE = "chat-cursors.json"
DELIVERED = "chat-delivered.json"
RESHOW_S = 300   # a delivered line not confirmed in this long comes again (the analysis's 5 minutes)


def key(name):
    return str(name or "").strip().lower()


_NOT_A_SESSION = {"sh", "bash", "zsh", "dash", "fish", "ksh", "tcsh", "csh", "env", "sudo", "nohup", "timeout", "time", "stdbuf", "xargs"}   # a shell or a wrapper runs the command; the session is above it
_SESSION = ["unset"]


def _ps(pid):
    """(parent pid, command name) of a process, or None."""
    try:
        out = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(int(pid))], capture_output=True, text=True, timeout=3).stdout.strip()
        ppid, _, comm = out.partition(" ")
        return int(ppid), comm.strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def session_id():
    """Which session is running this command: the pid of the first ancestor process that is not a shell or a wrapper (the agent runtime
    that spawned the shell, or a terminal tab's login), or None when it cannot be told. Worked out once per process."""
    if _SESSION[0] != "unset":
        return _SESSION[0]
    found, pid = None, os.getppid()
    for _ in range(12):
        row = _ps(pid) if pid and pid > 1 else None
        if not row:
            break
        ppid, comm = row
        if Path(comm).name.lstrip("-").lower() not in _NOT_A_SESSION:
            found = pid
            break
        pid = ppid
    _SESSION[0] = found
    return found


def path(board_dir):
    return Path(board_dir) / FILE


def read(board_dir):
    """{lower-cased name: seq}; only whole numbers count, and two spellings of one name read as the higher seq."""
    try:
        d = json.loads(path(board_dir).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, int) and not isinstance(v, bool):
            kk = key(k)
            out[kk] = max(v, out.get(kk, 0))
    return out


def get(board_dir, name):
    """The last seq `name`'s session printed, or None when it never read."""
    return read(board_dir).get(key(name))


def advance(board_dir, name, seq):
    """Move `name`'s cursor to `seq` unless it is already past it; returns the cursor after. Locked, so readers waking on the same
    line never overwrite each other's update."""
    seq = int(seq)
    with listeners.locked(board_dir, "cursors"):
        d = read(board_dir)
        k = key(name)
        cur = max(seq, d.get(k, 0))
        d[k] = cur
        try:
            backup.write_atomic(path(board_dir), json.dumps(d), keep_previous=False)
        except OSError:
            pass
    return cur


def _stamp(dt=None):
    return (dt or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")


def _age_s(stamp, now=None):
    from .store import parse_stamp
    at = parse_stamp(stamp)
    return float("inf") if at is None else ((now or datetime.now()) - at).total_seconds()


def read_delivered(board_dir):
    """{lower-cased name: {'seq', 'at'}}: the highest seq printed to each name and when it was printed."""
    try:
        d = json.loads((Path(board_dir) / DELIVERED).read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, dict) and isinstance(v.get("seq"), int) and not isinstance(v.get("seq"), bool):
                kk = key(k)
                if v["seq"] >= out.get(kk, {}).get("seq", 0):
                    out[kk] = {"seq": v["seq"], "at": str(v.get("at", ""))}
                    if isinstance(v.get("by"), int) and not isinstance(v.get("by"), bool):
                        out[kk]["by"] = v["by"]
    return out


def deliver(board_dir, name, seq, now=None, by=None):
    """A line (up to `seq`) was printed to `name`: record it, with the time and the session it went to (`by`, a session_id), unless a higher
    seq is already recorded."""
    seq = int(seq)
    with listeners.locked(board_dir, "cursors"):
        d = read_delivered(board_dir)
        k = key(name)
        if seq >= d.get(k, {}).get("seq", 0):
            d[k] = {"seq": seq, "at": _stamp(now)}
            if by is not None:
                d[k]["by"] = int(by)
        try:
            backup.write_atomic(Path(board_dir) / DELIVERED, json.dumps(d), keep_previous=False)
        except OSError:
            pass
    return d.get(k)


def pending(board_dir, name, now=None):
    """What was printed to `name` and not yet confirmed: None, or {'seq', 'at', 'age_s', 'by'} (by: the session it went to, when known)."""
    rec = read_delivered(board_dir).get(key(name))
    seen = get(board_dir, name) or 0
    if not rec or rec["seq"] <= seen:
        return None
    out = {"seq": rec["seq"], "at": rec["at"], "age_s": _age_s(rec["at"], now)}
    if "by" in rec:
        out["by"] = rec["by"]
    return out


def confirm(board_dir, name, now=None, within=None, by=None):
    """`name`'s session did something on the board: what was delivered to it counts as seen. With `within` (seconds), only a
    delivery younger than that is confirmed; an older one is left pending, so the next `chat inbox` shows it again. `by` is the session
    doing it: when the delivery went to that very session it is confirmed whatever its age (that session is here, so it read what it was
    shown). Returns the seq confirmed, or None."""
    p = pending(board_dir, name, now)
    if not p:
        return None
    if not (by is not None and p.get("by") == by) and within is not None and p["age_s"] > within:
        return None
    advance(board_dir, name, p["seq"])
    return p["seq"]


def confirm_session(board_dir, by=None):
    """A session ran a board command, whatever name it carried (or none): every delivery that went to it counts as seen. Cheap when nothing is
    pending (one small file read, no process lookup). Returns the names confirmed."""
    waiting = [(k, rec) for k, rec in read_delivered(board_dir).items() if "by" in rec and rec["seq"] > (get(board_dir, k) or 0)]
    if not waiting:
        return []
    by = session_id() if by is None else by
    if by is None:
        return []
    done = []
    for k, rec in waiting:
        if rec["by"] == by:
            advance(board_dir, k, rec["seq"])
            done.append(k)
    return done


def receipts(board_dir):
    """For the chat panel: seen (the cursors) and delivered (seq and time per name), keys lower-cased."""
    return {"read": read(board_dir), "delivered": read_delivered(board_dir)}
