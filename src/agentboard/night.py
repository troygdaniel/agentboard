"""The night queue (card retro-night-queue, retro rec 13; docs/night-queue-design.md).

A board-wide Night switch, off by default, and an ordered queue of card ids. While the switch is on, an agent with a free hand takes the next
ready card itself (`agentboard night next --name NAME`) instead of waiting for a message from ORCH. The owner decides when the switch is on
(and it ends by itself, at `until`, so a forgotten switch cannot run into the day); ORCH or the owner decides what is queued and in what order;
a worker agent can only take. The limits (no push, no spend, no live restarts, no personal cards) are stated in every take and in the chat line;
the board cannot enforce them, it can only make sure a card gets on the queue on purpose.

State: one small file, `.agentboard/night.json`, {"on": bool, "until": "YYYY-MM-DDTHH:MM:SS", "queue": [card ids]}. Nothing else on the board
changes: a board that never turns it on has no such file, and no command, line or screen differs from before. A taker holds the file's lock while
it claims, so two agents never take the same card; the claim itself is the ordinary `claim`.
"""
import re
from datetime import datetime, timedelta
from pathlib import Path

from . import statefile
from .store import BoardError, _to_owner, _unresolved_blockers

FILE = "night.json"
DEFAULT_UNTIL = "08:00"
LIMITS = "Night rules: no push, no spend, no live restarts, no personal cards. Hand in with review; ORCH merges."
_FMT = "%Y-%m-%dT%H:%M:%S"
_CAP = 200   # a queue longer than this is a mistake, not a plan


def path(board_dir):
    return Path(board_dir) / FILE


def _t(s):
    try:
        return datetime.fromisoformat(str(s)[:19])
    except ValueError:
        return None


def _clean(d):
    """The file's content as one well-formed dict, whatever was in it."""
    d = d if isinstance(d, dict) else {}
    q = d.get("queue")
    seen, out = set(), []
    for x in q if isinstance(q, list) else []:
        if isinstance(x, str) and x and x not in seen:
            seen.add(x)
            out.append(x)
    return {"on": d.get("on") is True, "until": d.get("until") if isinstance(d.get("until"), str) else None, "queue": out[:_CAP]}


def _read(board_dir):
    return _clean(statefile.load(path(board_dir), {}))


def parse_until(text, now=None):
    """`HH:MM` (or `H:MM`) -> the next time that is on the clock, strictly after now. Anything else is refused with the fix."""
    now = now or datetime.now()
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(text or DEFAULT_UNTIL))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise BoardError(f"--until takes a time of day like 07:30, not {str(text)[:20]!r}")
    at = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def active(board_dir, now=None):
    """(is night mode on right now, when it ends). An `until` that has passed means off."""
    st = _read(board_dir)
    until = _t(st["until"])
    return bool(st["on"] and until and (now or datetime.now()) < until), until


def _may_run(by, owner):
    """The switch and the queue are the owner's and ORCH's: a terminal with no session name (the owner), ORCH, or the owner by name."""
    b = str(by or "").strip()
    if b and b.upper() != "ORCH" and not _to_owner(b, owner):
        raise BoardError(f"only ORCH or the owner turns night mode on or off and lines up the queue: {b} takes the next card with "
                         f"`agentboard night next --name {b}`")


def _waiting(tasks, tid):
    """The card behind a queued id, or None when it no longer waits (gone, done, claimed, cleared, or not a Todo card any more)."""
    t = next((x for x in tasks if x["id"] == tid), None)
    if not t or t.get("archived") or t.get("parent_id") or t["status"] != "todo" or t.get("agent"):
        return None
    return t


def status(store, now=None):
    """What the board, the CLI and the page show: whether it is on, until when, and the queue in order (cards that no longer wait are left out)."""
    now = now or datetime.now()
    st = _read(store.dir)
    until = _t(st["until"])
    on = bool(st["on"] and until and now < until)
    tasks = store.load()
    rows = []
    for tid in st["queue"]:
        t = _waiting(tasks, tid)
        if t:
            blocked = _unresolved_blockers(tasks, t.get("blocked_by"))
            rows.append({"id": tid, "title": t["title"], "blocked_by": blocked, "ready": not blocked})
    return {"on": on, "until": until.strftime(_FMT) if until else None,
            "ended": bool(st["on"] and until and not on),   # it was on and ran out: the page says "ended 08:00", not "off"
            "queue": rows}


def _hhmm(s):
    return (s or "")[11:16]


def _post(store, text):
    store.chat_send(store.owner, text, "user", to="all", via="board")


def turn_on(store, until=None, by=None, now=None):
    now = now or datetime.now()
    _may_run(by, store.owner)
    end = parse_until(until, now)
    was = active(store.dir, now)[0]

    def go(d):
        d = _clean(d)
        d["on"], d["until"] = True, end.strftime(_FMT)
        return d
    statefile.update(path(store.dir), go)
    st = status(store, now)
    if not was:
        n = len(st["queue"])
        _post(store, f"ORCH and agents: night mode is on until {_hhmm(st['until'])}: {n} card{'s' if n != 1 else ''} queued. "
                     f"Take the next one with: agentboard night next --name <you>. {LIMITS}")
    return st


def turn_off(store, by=None, now=None):
    now = now or datetime.now()
    _may_run(by, store.owner)
    was = active(store.dir, now)[0]

    def go(d):
        d = _clean(d)
        d["on"] = False
        return d
    statefile.update(path(store.dir), go)
    if was:
        _post(store, "ORCH and agents: night mode is off. Take only the cards ORCH assigns; finish and hand in the one you hold.")
    return status(store, now)


def _edit_queue(store, fn):
    def go(d):
        d = _clean(d)
        d["queue"] = fn(d["queue"])[:_CAP]
        return d
    return statefile.update(path(store.dir), go)


def queue_add(store, ids, first=False, by=None):
    """Put cards on the queue (at the end, or the front with first=True). Each must be a Todo card nobody holds. Returns the ids added."""
    _may_run(by, store.owner)
    tasks = store.load()
    added, seen = [], set()
    for tid in ids:
        if tid in seen:
            continue
        seen.add(tid)
        if not any(x["id"] == tid for x in tasks):
            raise BoardError(f"no such card on the board: {tid}")
        t = _waiting(tasks, tid)
        if not t:
            raise BoardError(f"{tid} cannot be queued: only a Todo card nobody holds (not a subtask) can")
        added.append(tid)

    def go(q):   # a card already queued keeps its place, unless --first moves it to the front
        return added + [x for x in q if x not in added] if first else q + [x for x in added if x not in q]
    _edit_queue(store, go)
    return added


def queue_remove(store, ids, by=None):
    _may_run(by, store.owner)
    _edit_queue(store, lambda q: [x for x in q if x not in set(ids)])


def queue_clear(store, by=None):
    _may_run(by, store.owner)
    _edit_queue(store, lambda q: [])


def holds_open_card(tasks, name):
    """The card `name` is still working on (Doing, not handed in, no question open), or None. A card in review does not count: its holder is free."""
    n = str(name or "").strip().lower()
    return next((t for t in tasks if str(t.get("agent") or "").lower() == n and t["status"] == "doing" and not t.get("parent_id")
                 and not t.get("review") and not t.get("needs_input")), None)


def take(store, name, now=None):
    """The first ready card on the queue becomes `name`'s, claimed as `agentboard claim` would. Returns {"card", "blocked", "left"}, or None when
    nothing is ready. Refuses (BoardError) when night mode is off or ended, or when `name` still holds an unfinished card."""
    now = now or datetime.now()
    with statefile.locked(path(store.dir)):
        st = _read(store.dir)
        until = _t(st["until"])
        if not (st["on"] and until and now < until):
            raise BoardError(f"night mode ended at {_hhmm(st['until'])}: take only the cards ORCH assigns" if st["on"] and until
                             else "night mode is off: take only the cards ORCH assigns")
        tasks = store.load()
        held = holds_open_card(tasks, name)
        if held:
            raise BoardError(f"you hold {held['id']}: hand it in with review first, then take the next one")
        blocked, taken, keep = [], None, []
        for tid in st["queue"]:
            t = _waiting(tasks, tid)
            if not t:
                continue   # taken, claimed, done or gone: it leaves the queue
            if taken:
                keep.append(tid)
                continue
            if _unresolved_blockers(tasks, t.get("blocked_by")):
                blocked.append(tid)
                keep.append(tid)
                continue
            try:
                taken = store.claim(tid, name)
            except BoardError:   # someone claimed it between the read and now: the next card is this agent's
                continue
            store.update(tid, None, "Taken from the night queue")
        st["queue"] = keep
        statefile.write(path(store.dir), st)
        return {"card": taken, "blocked": blocked, "left": len(keep)} if taken else None
