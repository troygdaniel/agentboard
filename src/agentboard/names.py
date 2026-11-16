"""Agent names that changed, and the palette slot a name gets (card agentboard-rename-agent, docs/agent-configurations-design.md).

`agentboard rename OLD NEW` (rename.py) rewrites the board, but a terminal that was started as OLD still has AGENTBOARD_NAME=OLD until its
owner retypes it. Without help its next `update` would be refused as "not your card" and its wait would register as a new agent. So the board
keeps an alias, `.agentboard/aliases.json`:

    {"scout": {"from": "Scout", "to": "Ives", "at": "2026-11-14T16:30:00", "used": "2026-11-14T16:42:10"}}

and the command line asks `resolve()` once, before any command runs (cli._canon_names), so `--name Scout`, `--to Scout` and AGENTBOARD_NAME=Scout all
mean Ives. An alias is dropped when its old name has not been used for TTL_S (a day) or when the rename is undone; it holds names and times only.
A chain (Scout to Ives to Wren) is followed, and `add()` flattens it so the old links point at the newest name.

This module also holds `agent_slot()`, the palette slot a name gets, which mirrors agentColor() in static/index.html (a pinned colour for a
renamed agent is the slot its old name had). Nothing here starts a program or reads a card."""
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import statefile

FILE = "aliases.json"
TTL_S = 24 * 3600     # an alias is dropped once its old name has gone this long without being used
TOUCH_S = 600         # `used` is rewritten at most this often, so a busy session does not write a file on every command
MAX_HOPS = 8          # a chain longer than this (or a loop) stops; the name resolved so far is returned

AGENT_SLOTS = {"GENERAL": 5, "ORCH": 6}


def agent_slot(name):
    """The 1-based palette slot an agent name gets: AGENT-1..4 take 1..4 (AGENT-5 wraps to 1), GENERAL 5, ORCH 6, any other name a stable hash."""
    if name in AGENT_SLOTS:
        return AGENT_SLOTS[name]
    m = re.fullmatch(r"AGENT-(\d+)", name)
    if m:
        return (max(int(m.group(1)), 1) - 1) % 4 + 1
    h = 7
    for ch in name:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return 1 + h % 6


MAX_NAME = 80         # a name longer than this is refused where it comes in (rename keeps new names to 40)
_BIDI = set("\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")   # embeddings, overrides and isolates: they reorder a line on a page


def check(name, what="the name"):
    """The name, unchanged, if it is one line of plain text; a BoardError naming `what` if it holds a control character, a line or paragraph
    separator or a bidi override, or is over MAX_NAME. A name goes into chat lines, card owners and lists as it is typed, so a newline in one draws a
    whole second line (`#999 [..] ORCH -> all: ...`) in `chat tail` and `chat inbox`, which agents read as input, and an ESC byte moves the cursor.
    Anything that is not text is left for the caller's own check."""
    if not isinstance(name, str):
        return name
    bad = next((c for c in name if unicodedata.category(c) in ("Cc", "Zl", "Zp") or c in _BIDI), None)
    if bad is not None:
        from .store import BoardError   # store imports this module's neighbours; a late import keeps the cycle out
        raise BoardError(f"{what} has a control character (U+{ord(bad):04X}): a name is one line of plain text")
    if len(name) > MAX_NAME:
        from .store import BoardError
        raise BoardError(f"{what} is over {MAX_NAME} characters")
    return name


def key(name):
    return str(name or "").strip().lower()


def path(board_dir):
    return Path(board_dir) / FILE


def _stamp(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _entry(e):
    """A well-formed alias entry as (from, to, at, used), else None: a hand-edited or damaged file is skipped, never trusted."""
    if not isinstance(e, dict) or not isinstance(e.get("to"), str) or not e["to"].strip():
        return None
    at = _t(e.get("at"))
    if at is None:
        return None
    return str(e.get("from") or ""), e["to"], at, _t(e.get("used")) or at


def _alive(e, now):
    got = _entry(e)
    return bool(got) and (now - max(got[2], got[3])).total_seconds() <= TTL_S


def read(board_dir, now=None):
    """{lower-cased old name: entry} for the aliases still alive."""
    now = now or datetime.now()
    d = statefile.load(path(board_dir), {})
    if not isinstance(d, dict):
        return {}
    return {k: e for k, e in d.items() if _alive(e, now)}


def resolve(board_dir, name, now=None):
    """The name `name` stands for now: itself, or the newest name at the end of its alias chain. Notes that the old name was used (at most every
    TOUCH_S), which is what keeps an alias alive for a day after its last use. Never raises: a board without the file answers at once."""
    if not name or not path(board_dir).exists():
        return name
    now = now or datetime.now()
    d = read(board_dir, now)
    cur, seen = name, set()
    for _ in range(MAX_HOPS):
        k = key(cur)
        e = d.get(k)
        if e is None or k in seen:
            break
        seen.add(k)
        cur = e["to"]
    if seen:
        _touch(board_dir, seen, now)
    return cur


def _touch(board_dir, keys, now):
    def note(d):
        if not isinstance(d, dict):
            return {}
        for k in keys:
            e = d.get(k)
            got = _entry(e)
            if got and (now - got[3]).total_seconds() >= TOUCH_S:
                e["used"] = _stamp(now)
        return d
    try:
        statefile.update(path(board_dir), note)
    except OSError:
        pass   # a read-only board still resolves; the alias just is not kept alive by this use


def add(board_dir, old, new, now=None):
    """Record that `old` is now `new`. Aliases that pointed at `old` follow it to `new`, and an alias for `new` itself is dropped (a rename back
    makes that name live again). Expired entries go with the write."""
    now = now or datetime.now()

    def put(d):
        d = {k: e for k, e in (d.items() if isinstance(d, dict) else ()) if _alive(e, now)}
        for e in d.values():
            if key(e["to"]) == key(old):
                e["to"] = new
        d.pop(key(new), None)
        d[key(old)] = {"from": old, "to": new, "at": _stamp(now), "used": _stamp(now)}
        return d
    return statefile.update(path(board_dir), put)


def drop(board_dir, old):
    """Remove the alias for `old` (an undone rename); aliases that pointed at it are left alone. True if there was one."""
    gone = []

    def rm(d):
        if isinstance(d, dict) and key(old) in d:
            gone.append(d.pop(key(old)))
        return d
    if path(board_dir).exists():
        statefile.update(path(board_dir), rm)
    return bool(gone)


def targets(board_dir, now=None):
    """Every name an alias currently points at or stands for, lower-cased: names a new rename may not take."""
    out = set()
    for k, e in read(board_dir, now).items():
        out.add(k)
        out.add(key(e["to"]))
    return out
