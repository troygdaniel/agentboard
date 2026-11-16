"""A sign of life: when a named session last did something on the board (card fix-orch-presence-while-busy).

The board used to call ORCH "running" only while a `chat inbox --wait` was open. A wait ends the moment a line arrives, and ORCH cannot start
the next one until its current tool call ends: a merge and an eight-minute test run left no wait open for minutes, and the board said
"ORCH is not running" with a Start ORCH button while ORCH was hard at work. So every board command a named session runs, every wait it opens
or closes, and both Claude Code hooks (SendMessage, Stop) write a stamp here, `.agentboard/chat-presence.json`:

    {"orch": "2026-11-15T19:20:11", "taskmaster-3": "2026-11-15T19:20:05"}

lower-cased name to the local time of the last one. The page treats ORCH as running while a wait is open or the stamp is younger than the
grace (`[orch] presence_grace_s`, 600 s by default, 30 to 86400). Names and times only; nothing here reads a card or starts a program. A name
is rewritten at most every TOUCH_S seconds, so a busy session does not write a file on every command, and a stamp older than KEEP_S is dropped.
The Watch tab's own listening dot is not changed: it still means "a wait is open now"."""
from datetime import datetime
from pathlib import Path

from . import statefile

FILE = "chat-presence.json"
TOUCH_S = 10                 # a name's stamp is rewritten at most this often
KEEP_S = 7 * 24 * 3600       # a stamp this old belongs to a session long gone
DEFAULT_GRACE_S = 600        # ORCH counts as running this long after its last sign of life (real work: a merge, a full test run)
MIN_GRACE_S, MAX_GRACE_S = 30, 86400


def path(board_dir):
    return Path(board_dir) / FILE


def _stamp(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")


def _age_s(stamp, now=None):
    from .store import parse_stamp
    at = parse_stamp(stamp)
    return float("inf") if at is None else ((now or datetime.now()) - at).total_seconds()


def read(board_dir):
    """{lower-cased name: stamp}; a missing or broken file reads as nothing."""
    d = statefile.load(path(board_dir), {})
    return {str(k).lower(): v for k, v in d.items() if isinstance(v, str)} if isinstance(d, dict) else {}


def touch(board_dir, name, now=None):
    """`name`'s session did something just now. Quiet on any trouble: a stamp never stops a command. Returns True when it wrote."""
    if not isinstance(name, str) or not name.strip():
        return False
    k = name.strip().lower()
    now = now or datetime.now()
    try:
        last = read(board_dir).get(k)
        if last and 0 <= _age_s(last, now) < TOUCH_S:
            return False   # the cheap check first: no lock, no write

        def put(d):
            d[k] = _stamp(now)
            for old in [n for n, v in d.items() if not isinstance(v, str) or _age_s(v, now) > KEEP_S]:
                del d[old]
        statefile.update(path(board_dir), put)
        return True
    except (OSError, ValueError):
        return False


def grace_s(conf):
    """[orch] presence_grace_s from a loaded config, or the default when it is missing, not a whole number or out of range."""
    sec = conf.get("orch") if isinstance(conf, dict) else None
    v = sec.get("presence_grace_s") if isinstance(sec, dict) else None
    return v if isinstance(v, int) and not isinstance(v, bool) and MIN_GRACE_S <= v <= MAX_GRACE_S else DEFAULT_GRACE_S
