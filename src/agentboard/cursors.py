"""Where each session got to in the chat: `.agentboard/chat-cursors.json`, {name: the last seq its session printed}. This is the
one place it is read and written (the CLI, the idle drafter, the receipts and the Stop hook each used to do their own, by exact-case
name, with no lock). The key is the name lower-cased, so `agentboard me --name AGENT-4` and `chat inbox --name agent-4` are one
session; a write takes a file lock and only moves forward; the file is replaced atomically. An older file with mixed-case keys
reads as the highest seq per name.

Two steps (chat-f3). Printing a line is DELIVERED: `deliver()` records the highest seq printed to a name and when, in
`chat-delivered.json`. The name's cursor (SEEN) moves only when that session next does anything on the board as that name:
`confirm()`, called by every command that takes --name. A delivered line that is not confirmed within RESHOW_S is shown again by
the next `chat inbox` (the reader that printed it was gone, or never read its output)."""
import json
from datetime import datetime
from pathlib import Path

from . import backup, listeners

FILE = "chat-cursors.json"
DELIVERED = "chat-delivered.json"
RESHOW_S = 300   # a delivered line not confirmed in this long comes again (the analysis's 5 minutes)


def key(name):
    return str(name or "").strip().lower()


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
    return out


def deliver(board_dir, name, seq, now=None):
    """A line (up to `seq`) was printed to `name`: record it, with the time, unless a higher seq is already recorded."""
    seq = int(seq)
    with listeners.locked(board_dir, "cursors"):
        d = read_delivered(board_dir)
        k = key(name)
        if seq >= d.get(k, {}).get("seq", 0):
            d[k] = {"seq": seq, "at": _stamp(now)}
        try:
            backup.write_atomic(Path(board_dir) / DELIVERED, json.dumps(d), keep_previous=False)
        except OSError:
            pass
    return d.get(k)


def pending(board_dir, name, now=None):
    """What was printed to `name` and not yet confirmed: None, or {'seq', 'at', 'age_s'}."""
    rec = read_delivered(board_dir).get(key(name))
    seen = get(board_dir, name) or 0
    if not rec or rec["seq"] <= seen:
        return None
    return {"seq": rec["seq"], "at": rec["at"], "age_s": _age_s(rec["at"], now)}


def confirm(board_dir, name, now=None, within=None):
    """`name`'s session did something on the board: what was delivered to it counts as seen. With `within` (seconds), only a
    delivery younger than that is confirmed; an older one is left pending, so the next `chat inbox` shows it again. Returns the
    seq confirmed, or None."""
    p = pending(board_dir, name, now)
    if not p or (within is not None and p["age_s"] > within):
        return None
    advance(board_dir, name, p["seq"])
    return p["seq"]


def receipts(board_dir):
    """For the chat panel: seen (the cursors) and delivered (seq and time per name), keys lower-cased."""
    return {"read": read(board_dir), "delivered": read_delivered(board_dir)}
