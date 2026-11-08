"""Where each session got to in the chat: `.agentboard/chat-cursors.json`, {name: the last seq its session printed}. This is the
one place it is read and written (the CLI, the idle drafter, the receipts and the Stop hook each used to do their own, by exact-case
name, with no lock). The key is the name lower-cased, so `agentboard me --name AGENT-4` and `chat inbox --name agent-4` are one
session; a write takes a file lock and only moves forward; the file is replaced atomically. An older file with mixed-case keys
reads as the highest seq per name."""
import json
from pathlib import Path

from . import backup, listeners

FILE = "chat-cursors.json"


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
