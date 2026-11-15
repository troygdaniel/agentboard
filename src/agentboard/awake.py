"""The board's own sleep (card agent-status-slice-1, docs/status-visibility-design.md "The board-asleep rule").

An agent is "silent" when its card has not been touched for a while. When the Mac sleeps (or the server is stopped) every card goes untouched at
once, and the board used to call every agent silent or abandoned for it. This module records the stretches the board was not running, so the
quiet an agent is held to counts only the time the board could have heard it.

How: the server calls `tick()` about once a minute. It keeps the time of the last tick in `.agentboard/awake.json`; a tick that finds the last one
more than GAP_S ago writes one line `{"from": ..., "to": ...}` to `.agentboard/asleep.jsonl` for the stretch in between. Nothing else is stored: no
agent name, no text, local only, and it works with `[insights]` off (agentstates.py needs it on). A reader that asks right after a wake, before the next
tick has written the line, still gets the stretch: `windows()` adds the open one.

Never raises: a board that cannot write here simply has no windows, which is the behaviour from before this module."""
import json
from datetime import datetime, timedelta
from pathlib import Path

HEART = "awake.json"
FILE = "asleep.jsonl"
GAP_S = 180            # more than this since the last tick: the board was not running (a closed lid, a stopped server)
KEEP_DAYS = 14         # older stretches are dropped when the file is rewritten
MAX_BYTES = 100_000    # past this the old lines are dropped (14 days of even a restless Mac is far smaller)
_FMT = "%Y-%m-%dT%H:%M:%S"


def _stamp(dt):
    return dt.strftime(_FMT)


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _last_tick(board_dir):
    try:
        d = json.loads((Path(board_dir) / HEART).read_text())
        return _t(d.get("last")) if isinstance(d, dict) else None
    except (OSError, ValueError):
        return None


def _lines(board_dir):
    """Every recorded stretch as (from, to), oldest first; a line that is not one of ours is skipped."""
    out = []
    try:
        text = (Path(board_dir) / FILE).read_text()
    except OSError:
        return out
    for raw in text.splitlines():
        try:
            d = json.loads(raw)
        except ValueError:
            continue
        a, b = (_t(d.get("from")), _t(d.get("to"))) if isinstance(d, dict) else (None, None)
        if a and b and b > a:
            out.append((a, b))
    return sorted(out)


def tick(board_dir, now=None):
    """One tick. Returns the seconds of the stretch this tick ended (0 when the board was running the whole time). Never raises."""
    now = now or datetime.now()
    try:
        board = Path(board_dir)
        last = _last_tick(board)
        gap = 0
        if last is not None and (now - last).total_seconds() > GAP_S:
            gap = int((now - last).total_seconds())
            path = board / FILE
            try:
                if path.stat().st_size > MAX_BYTES:   # keep the recent ones only
                    cut = now - timedelta(days=KEEP_DAYS)
                    keep = [(a, b) for a, b in _lines(board) if b >= cut]
                    path.write_text("".join(json.dumps({"from": _stamp(a), "to": _stamp(b)}) + "\n" for a, b in keep))
            except OSError:
                pass
            with open(path, "a") as f:
                f.write(json.dumps({"from": _stamp(last), "to": _stamp(now)}) + "\n")
        (board / HEART).write_text(json.dumps({"last": _stamp(now)}))
        return gap
    except OSError:
        return 0


def windows(board_dir, now=None, days=1):
    """The stretches the board was not running that touch the last `days` days, as (from, to) datetimes, oldest first. A stretch that is still
    open (the last tick is more than GAP_S ago and nobody has written it down yet) is included, ending now."""
    now = now or datetime.now()
    since = now - timedelta(days=days)
    out = [(a, b) for a, b in _lines(board_dir) if b > since]
    last = _last_tick(board_dir)
    if last is not None and (now - last).total_seconds() > GAP_S and now > last:
        out.append((last, now))
    return out


def overlap_minutes(a, b, wins):
    """Minutes of [a, b] that fall inside the windows."""
    total = 0.0
    for wa, wb in wins or ():
        lo, hi = max(a, wa), min(b, wb)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total / 60


def awake_minutes(a, b, wins):
    """Minutes from a to b the board was running: the span less the windows. Never negative."""
    if b <= a:
        return 0.0
    return max(0.0, (b - a).total_seconds() / 60 - overlap_minutes(a, b, wins))


def latest(wins, now, within_hours=6):
    """The latest window that is still open or ended in the last `within_hours`, as {"from", "to", "minutes", "open"} (open: the board is asleep or just woke and has not written it down yet), else None."""
    best = None
    for a, b in wins or ():
        if (now - b).total_seconds() <= within_hours * 3600 and (best is None or b > best[1]):
            best = (a, b)
    if best is None:
        return None
    a, b = best
    return {"from": _stamp(a), "to": _stamp(b), "minutes": round((b - a).total_seconds() / 60), "open": b >= now}
