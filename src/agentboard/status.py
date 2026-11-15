"""Agent status on one page (card agent-status-slice-1, docs/status-visibility-design.md): the answer to "is anyone waiting on me, what is stuck, who waits on
whom", worked out on the server from what the board already holds, so the page only draws it and nobody has to ask.

`build()` takes what `hud.build` made (its `agents`, already sleep-aware: awake.py), the cards and the names with a wait running, and returns, for `/api/hud`:

    counts   five groups, each {n, oldest_min}: you (an agent asks, or a finished card waits for your sign-off), stuck (silent, presumed gone, blocked),
             others (a finished card waits for ORCH), working, idle
    agents   one row per agent: name, state, task, task_id, line, progress, quiet_min, waits_on, group
    asleep   the latest stretch the board was not running (from, to, minutes, open), or None: shown, and never counted as silence

The eight state words: working, silent, gone (presumed gone, the HUD's "abandoned"), blocked, waiting (on you), review, idle (a wait is running: listening for work)
and away. "In queue" (waiting for a shared resource) is slice 2; it needs a wait note from the project's test runner.

A card in review waits on ORCH until ORCH has recorded its sign-off (signoff.py) and on the owner after it. Counts, names and cards' own words only; nothing is stored."""
from . import awake

STATES = ("working", "silent", "gone", "blocked", "waiting", "review", "idle", "away")
GROUPS = ("you", "stuck", "others", "working", "idle")
_ORDER = {"you": 0, "stuck": 1, "others": 2, "working": 3, "idle": 4}
_FROM_HUD = {"working": "working", "quiet": "silent", "abandoned": "gone", "waiting": "waiting", "review": "review"}


def _blocker(card, by_id):
    """The id of the first unfinished card this one waits on, or None."""
    for b in (card or {}).get("blocked_by") or []:
        other = by_id.get(b)
        if other is not None and other.get("status") != "done":
            return b
    return None


def _row(a, by_id, listening):
    card = by_id.get(a.get("task_id") or "")
    hud_state = a.get("state") or "idle"
    state = _FROM_HUD.get(hud_state)
    waits = ""
    if state is None:   # the HUD says idle: nothing in Doing. Listening for work, or away
        state = "idle" if (a.get("name") or "").lower() in listening else "away"
    elif state in ("working", "silent"):
        blocker = _blocker(card, by_id)
        if blocker:
            state, waits = "blocked", blocker
    if state == "waiting":
        waits = "you"
    elif state == "review":
        waits = "you" if (card or {}).get("signoff") else "orch"
    group = ("you" if state == "waiting" or (state == "review" and waits == "you") else
             "others" if state == "review" else
             "stuck" if state in ("silent", "gone", "blocked") else
             "working" if state == "working" else "idle")
    return {"name": a.get("name"), "state": state, "group": group, "task": a.get("task") or "", "task_id": a.get("task_id") or "",
            "line": (a.get("question") if state == "waiting" and a.get("question") else a.get("status_text")) or "",
            "progress": a.get("progress") or 0, "quiet_min": a.get("quiet_min"), "waits_on": waits}


def build(hud_agents, tasks, now, listening=(), asleep=()):
    """The status block for /api/hud. hud_agents: hud.build()['agents']; tasks: every card; listening: names with a wait running;
    asleep: awake.windows(). `now` is the clock the HUD was built at."""
    by_id = {t.get("id"): t for t in tasks if isinstance(t, dict)}
    live = {str(n).lower() for n in listening or ()}
    rows = [_row(a, by_id, live) for a in hud_agents]
    rows.sort(key=lambda r: (_ORDER[r["group"]], r["state"] != "waiting", str(r["name"]).lower()))
    counts = {}
    for g in GROUPS:
        mine = [r for r in rows if r["group"] == g]
        ages = [r["quiet_min"] for r in mine if r["quiet_min"] is not None]
        counts[g] = {"n": len(mine), "oldest_min": max(ages) if ages else None}
    return {"counts": counts, "agents": rows, "asleep": awake.latest(asleep, now)}
