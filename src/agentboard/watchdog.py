"""The agent protocol's watchdog: the ways a board gets stuck between agents, found in one pass, each with the one fix that puts it
right (overnight-rel-agent-protocol). Nothing here changes the board by itself: findings() only reads; heal() does one named fix,
on the owner's click or `agentboard watchdog --fix`, and writes one history line saying so.

What it finds (kind):
  stuck          a Doing card idle past the stale threshold whose holder has no wait running (nothing wakes it)
  claimed-idle   claimed, never worked: the last history line is still "Claimed by", and it is past the threshold
  vanished       an agent holding Doing cards with no wait running, no card update and no chat line past the threshold
  twins          two cards for one piece of work (`<id>` and `<id>-2`, the same agent, the same title)
  split-card     a Doing parent held by one agent with an open subtask held by another
  orphan         a subtask whose parent is not on the board (deleted, or cleared)
  subtask-ahead  a subtask in Doing while its parent is not
  two-sessions   two live sessions answer to one name (both wake on one line, both may answer)
  no-session     an agent holding Doing cards that never said who it is (`agentboard me`): the hooks cannot reach its session

The fixes (heal action): release (a card back to Todo, holder cleared), release-all (every Doing card of a vanished agent),
merge (the twin into its keeper), hand (the subtasks to the parent's holder), adopt (an orphan becomes a card of its own),
follow (a subtask takes its parent's column). two-sessions and no-session have no board-side fix: the line says what to run."""
from datetime import datetime

from . import hooks, hud, listeners, prompt
from .store import BoardError, _apply_status, _kids, _log, _now, _recompute, merge_twin, twins

ACTIONS = ("release", "release-all", "merge", "hand", "adopt", "follow")
FMT = "%Y-%m-%dT%H:%M:%S"


def _t(s):
    try:
        return datetime.strptime(str(s), FMT)
    except (TypeError, ValueError):
        return None


def _idle_min(t, now):
    last = _t(t.get("updated"))
    return None if last is None else (now - last).total_seconds() / 60


def threshold(store):
    return hud.stale_minutes(prompt.load_config(store.dir))


def findings(store, now=None, stale_min=None):
    """Every way this board is stuck right now, most urgent first. Read-only."""
    now = now or datetime.now()
    stale_min = threshold(store) if stale_min is None else stale_min
    tasks = store.load()
    by_id = {t["id"]: t for t in tasks}
    live = {t["id"]: t for t in tasks if not t.get("archived")}
    listening = listeners.listening(store.dir)
    lk = {n.lower() for n in listening}
    said = {str(n).lower() for n in (r.get("name") for r in hooks.read_sessions(store.dir).values() if isinstance(r, dict)) if n}
    chat_last = {}
    for m in store.chat_list(limit=500):
        if m.get("kind") == "agent" and m.get("sender") and not m.get("via"):
            chat_last[m["sender"].lower()] = m.get("at")
    out = []

    def add(kind, t, what, fix=None, agent=None, since=None):
        out.append({"kind": kind, "id": t["id"] if t else None, "title": t["title"] if t else None, "agent": agent or (t.get("agent") if t else None),
                    "what": what, "fix": fix, "since": since})

    # twins and split cards: shape problems, whatever the clock says
    for k, tw in twins(tasks):
        if tw.get("archived"):
            continue
        add("twins", tw, f"{tw['id']} is a second card for {k['id']} (same agent, same title): two histories for one piece of work",
            {"action": "merge", "id": tw["id"], "label": f"Merge into {k['id']}"})
    for t in live.values():
        if t.get("status") != "doing" or t.get("parent_id") in by_id:
            continue
        others = sorted({k.get("agent") for k in _kids(tasks, t["id"]) if k["status"] != "done" and k.get("agent") and k.get("agent") != t.get("agent")})
        if t.get("agent") and others:
            add("split-card", t, f"{t['agent']} holds the card but {', '.join(others)} hold{'s' if len(others) == 1 else ''} open subtasks of it: two agents on one card",
                {"action": "hand", "id": t["id"], "label": f"Hand the subtasks to {t['agent']}"})
    for t in live.values():
        pid = t.get("parent_id")
        if not pid:
            continue
        parent = by_id.get(pid)
        if parent is None or parent.get("archived"):
            add("orphan", t, f"its parent {pid} is not on the board: the subtask can neither be updated nor closed with a card",
                {"action": "adopt", "id": t["id"], "label": "Make it a card of its own"})
        elif t["status"] == "doing" and parent["status"] != "doing":
            add("subtask-ahead", t, f"in Doing while its parent {pid} is in {parent['status'].title()}: the parent's % and the HUD do not see the work",
                {"action": "follow", "id": t["id"], "label": f"Follow the parent to {parent['status'].title()}"})
    # the clock: stuck cards and vanished agents
    holders = {}
    for t in live.values():
        if t.get("status") != "doing" or t.get("parent_id") in by_id or not t.get("agent"):
            continue
        holders.setdefault(t["agent"], []).append(t)
    for agent, cards in sorted(holders.items()):
        a = agent.lower()
        idle_cards = [t for t in cards if (_idle_min(t, now) or 0) >= stale_min and not t.get("needs_input") and not t.get("review")]
        chat_idle = ((now - _t(chat_last[a])).total_seconds() / 60) if _t(chat_last.get(a)) else None
        quiet = a not in lk and (chat_idle is None or chat_idle >= stale_min)
        if quiet and idle_cards and len(idle_cards) == len([t for t in cards if not t.get("needs_input") and not t.get("review")]):
            add("vanished", None, f"{agent} holds {len(idle_cards)} Doing card{'s' if len(idle_cards) > 1 else ''}, has no wait running, and has not touched a card or the chat for {int(min(_idle_min(t, now) for t in idle_cards))} min",
                {"action": "release-all", "id": agent, "label": f"Release {agent}'s cards to Todo"}, agent=agent, since=min(t.get("updated", "") for t in idle_cards))
        for t in idle_cards:
            claimed = bool(t.get("log")) and str(t["log"][-1].get("text", "")).startswith("Claimed by")
            if a in lk and not claimed:
                continue   # a listening holder on a quiet card is working or waiting; the HUD's stale row covers it
            kind = "claimed-idle" if claimed else "stuck"
            what = (f"claimed by {agent} {int(_idle_min(t, now))} min ago and never worked" if claimed
                    else f"no update for {int(_idle_min(t, now))} min and {agent} has no wait running: nothing on the board wakes it")
            add(kind, t, what, {"action": "release", "id": t["id"], "label": "Release to Todo"}, since=t.get("updated"))
        if a not in said and a not in lk:
            add("no-session", None, f"{agent} never said who it is (agentboard me --name {agent}): the Stop hook and the mirror cannot reach its session",
                None, agent=agent)
    for name, rec in listening.items():
        if rec.get("sessions", 1) > 1:
            add("two-sessions", None, f"{rec['sessions']} sessions answer to {name}: a line reaches all of them and each may answer; rename one with /rename in that session",
                None, agent=name)
    rank = {"vanished": 0, "stuck": 1, "claimed-idle": 2, "split-card": 3, "twins": 4, "orphan": 5, "subtask-ahead": 6, "two-sessions": 7, "no-session": 8}
    out.sort(key=lambda f: (rank[f["kind"]], f.get("since") or "", f.get("id") or ""))
    return out


def heal(store, action, target, by=None):
    """Do one fix. Returns the ids it touched. Every change is one history line that says the watchdog did it, for whom."""
    by = by or store.owner
    who = f"the watchdog, for {by}"
    if action not in ACTIONS:
        raise BoardError(f"fix must be one of {', '.join(ACTIONS)}")
    if action == "merge":
        pairs = [(k["id"], tw["id"]) for k, tw in twins(store.load()) if tw["id"] == target]
        if not pairs:
            raise BoardError(f"{target} is not a twin of another card")
        store.backups.take("before-watchdog-merge")
        with store.transaction() as tasks:
            by_id = {t["id"]: t for t in tasks}
            merge_twin(tasks, by_id[pairs[0][0]], by_id[pairs[0][1]])
            _log(by_id[pairs[0][0]], f"Merged {target} into this card (a twin)", by=who)
            tasks[:] = [t for t in tasks if t["id"] != target]
        return [pairs[0][0], target]
    with store.transaction() as tasks:
        by_id = {t["id"]: t for t in tasks}
        if action == "release-all":
            cards = [t for t in tasks if t.get("status") == "doing" and t.get("agent") == target and t.get("parent_id") not in by_id and not t.get("archived")]
            if not cards:
                raise BoardError(f"{target} holds no Doing card")
            for t in cards:
                _release(tasks, t, who)
            return [t["id"] for t in cards]
        t = store.get(tasks, target)
        if action == "release":
            if t.get("status") != "doing":
                raise BoardError(f"{target} is not in Doing")
            if t.get("parent_id") in by_id:
                raise BoardError("release the parent card")
            _release(tasks, t, who)
            return [t["id"]]
        if action == "hand":
            holder = t.get("agent")
            if not holder:
                raise BoardError(f"{target} has no holder to hand its subtasks to")
            moved = []
            for k in _kids(tasks, t["id"]):
                if k["status"] != "done" and k.get("agent") != holder:
                    _log(k, f"Handed from {k.get('agent') or 'nobody'} to {holder}, who holds the card", by=who)
                    k["agent"], k["updated"] = holder, _now()
                    moved.append(k["id"])
            if not moved:
                raise BoardError(f"every open subtask of {target} is already {holder}'s")
            return moved
        if action == "adopt":
            pid = t.get("parent_id")
            parent = by_id.get(pid)
            if pid and parent and not parent.get("archived"):
                raise BoardError(f"{target} still has its parent {pid}; nothing to adopt")
            t.pop("parent_id", None)
            _log(t, f"Made a card of its own: its parent {pid} was not on the board", by=who)
            t["updated"] = _now()
            return [t["id"]]
        if action == "follow":
            parent = by_id.get(t.get("parent_id"))
            if not parent:
                raise BoardError(f"{target} has no parent on the board")
            if t["status"] == parent["status"]:
                raise BoardError(f"{target} is already in {parent['status'].title()} with its parent")
            _apply_status(t, parent["status"])
            _log(t, f"Followed its parent to {parent['status'].title()}", by=who)
            t["updated"] = _now()
            _recompute(tasks, parent)
            return [t["id"]]
    raise BoardError("nothing to do")


def _release(tasks, t, who):
    """Back to Todo with its history: the holder is cleared, the question or review flag goes, open subtasks come along."""
    was = t.get("agent")
    for f in ("needs_input", "question", "ask_child", "review", "reply", "body_md"):
        t.pop(f, None)
    _apply_status(t, "todo")
    t.pop("agent", None)
    t["status_text"] = f"Released from {was} by the watchdog: no update and nothing listening"
    _log(t, f"Released to Todo: {was} had no wait running and had not updated the card", by=who)
    t["updated"] = _now()
    for k in _kids(tasks, t["id"]):
        if k["status"] != "done":
            _apply_status(k, "todo")
            k.pop("agent", None)
            k["updated"] = t["updated"]
    _recompute(tasks, t)


def summary(items):
    """One line for doctor and the HUD: counts by kind, or the all-clear."""
    if not items:
        return "no stuck claim, twin, orphan or vanished agent on the board"
    counts = {}
    for f in items:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    return ", ".join(f"{n} {k}" for k, n in counts.items())
