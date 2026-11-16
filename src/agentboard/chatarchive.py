"""Chat archive (card retro-chat-archive, docs/insights-design.md capture 9): the whole chat kept beyond the live file's CHAT_MAX lines, with counts per
day and sender.

Behind `[insights] enabled = true`. The store calls `append()` after every chat post, under its own lock, with the live chat list: every line newer than the
last archived one goes, as posted, to `.agentboard/chat-archive/chat-YYYY-MM-DD.jsonl` (the day of its `at` stamp: a new file each day, and nothing here is
ever rewritten or pruned), and `.agentboard/chat-archive/counts.json` gains one for that day and sender and keeps the last archived seq, so a line is never
archived twice. The first append copies what the live file still holds, so the archive starts with the lines that would otherwise be the first to fall off.

Local files only, written by the store and read by nothing on the board: not by an agent command, not by lookup, not by the server. `read()` and `counts()`
are for the owner's own scripts (a retro) and the tests. A later change to a live line (its casual rendering, a decision on a proposal, a nudge) stays on the
live line: the archive is the line as sent. No program is started and nothing leaves the board; this module imports no process or network module (selfcheck)."""
import json
import re
from pathlib import Path

from . import backup

DIR = "chat-archive"
COUNTS = "counts.json"


_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(msg):
    """The day a line belongs to, from its `at` ("%Y-%m-%dT%H:%M:%S"), as a file-name-safe YYYY-MM-DD. A hand-edited or copied board can hold anything in `at`
    (a path, a NUL, a number): that line goes to chat-unknown.jsonl instead of naming a file somewhere else or raising on the post."""
    day = str(msg.get("at") or "")[:10]
    return day if _DAY.match(day) else "unknown"


def _file(d, day):
    return d / f"chat-{day}.jsonl"


def _load_counts(d):
    try:
        c = json.loads((d / COUNTS).read_text())
    except (OSError, ValueError):
        c = None
    if not isinstance(c, dict):
        c = {}
    if not isinstance(c.get("last_seq"), int):
        c["last_seq"] = 0
    if not isinstance(c.get("days"), dict):
        c["days"] = {}
    return c


def append(board_dir, live):
    """Archive every line of `live` (the live chat list, oldest first) newer than the last archived seq; returns how many were written.
    The store calls this under its lock, after the live file is written. An OSError is the caller's to swallow: a failed archive never fails a post."""
    d = Path(board_dir) / DIR
    d.mkdir(parents=True, exist_ok=True)
    c = _load_counts(d)
    lines = [m for m in live if isinstance(m, dict) and isinstance(m.get("seq"), int)]
    if lines and lines[-1]["seq"] < c["last_seq"]:
        new = lines[-1:]   # the board was restored to an older snapshot and the numbers went back: start again from the line just posted
    else:
        new = [m for m in lines if m["seq"] > c["last_seq"]]
    if not new:
        return 0
    by_day = {}
    for m in new:
        day = _day(m)
        by_day.setdefault(day, []).append(m)
        who = str(m.get("sender") or "?")
        per = c["days"].setdefault(day, {})
        per[who] = int(per.get(who, 0)) + 1
    for day, msgs in by_day.items():
        with open(_file(d, day), "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(m, ensure_ascii=False, sort_keys=True) + "\n" for m in msgs))
    c["last_seq"] = max(m["seq"] for m in new)
    backup.write_atomic(d / COUNTS, json.dumps(c, indent=1, sort_keys=True) + "\n", keep_previous=False)   # temp file and rename, like every state file
    return len(new)


def read(board_dir, day=None):
    """Every archived line, oldest first (one day's with `day`, "YYYY-MM-DD"). For the owner's own scripts and the tests; nothing on the board calls it."""
    d = Path(board_dir) / DIR
    files = [_file(d, day)] if day else sorted(d.glob("chat-*.jsonl"))
    out = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if isinstance(m, dict):
                out.append(m)
    return out


def counts(board_dir):
    """{day: {sender: lines}} as kept in counts.json. For the owner's own scripts and the tests."""
    return _load_counts(Path(board_dir) / DIR)["days"]
