"""Aggregate board data for the HUD view: agents, activity feed, totals, timeline."""
from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%M:%S"
STALE_MIN = 10
ABANDONED_MIN = 120    # default: flag a Doing task as stale/abandoned after this many idle minutes.
                       # Much longer than STALE_MIN's "quiet" warning; overridden by [board].stale_minutes
                       # in config.toml (see cli.cmd_list's --stale and server.py's /api/config, /api/hud).
SPARK_BUCKETS, SPARK_MIN = 12, 5      # last hour in 5-minute buckets
TIMELINE_BUCKETS, TIMELINE_MIN = 30, 2   # last hour in 2-minute buckets (same window as the lanes)
WINDOW_MIN = TIMELINE_BUCKETS * TIMELINE_MIN


def _t(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


def _marked_at(t):
    """Timestamp of a task's most recent 'marked done' log entry, or None."""
    at = None
    for e in t.get("log", []):
        if e.get("text") in ("Marked done", "Moved to done"):
            ts = _t(e.get("at"))
            if ts:
                at = ts
    return at


def done_on(tasks, day=None):
    """Tasks marked done on `day` (default: today) — title, agent, result, mark time.

    Same 'marked done' detection build() uses for its done_today/agent done_today counts,
    generalized to any day so `agentboard report` can recap today or a past date.
    """
    day = day or datetime.now().date()
    out = [{"id": t["id"], "title": t["title"], "agent": t.get("agent"),
            "result": t.get("result") or t.get("status_text") or "", "at": m.strftime(FMT)}
           for t in tasks if t["status"] == "done" and (m := _marked_at(t)) and m.date() == day]
    out.sort(key=lambda d: d["at"])
    return out


def events_on(tasks, day=None):
    """Count of activity-log entries across all tasks on `day` (default: today) — same definition as
    build()'s events_today, generalized to any day."""
    day = day or datetime.now().date()
    return sum(1 for t in tasks for e in t.get("log", [])
               if (at := _t(e.get("at"))) and at.date() == day)


def minutes_idle(t, now=None):
    """Minutes since a Doing task's last update, or None if it isn't Doing / has no parseable timestamp."""
    if t.get("status") != "doing":
        return None
    last = _t(t.get("updated"))
    if last is None:
        return None
    return ((now or datetime.now()) - last).total_seconds() / 60


def _bucket(times, now, n, minutes):
    out = [0] * n
    for t in times:
        age = (now - t).total_seconds() / 60
        if 0 <= age < n * minutes:
            out[n - 1 - int(age // minutes)] += 1
    return out


def segments(t, now):
    """A task's history as (kind, start, end) runs, from its log.

    kind: queue (waiting in Todo), busy (agent working), waiting (needs the user), review (awaiting sign-off).
    The last run is open-ended and runs to `now`.
    """
    out, cur = [], None
    for e in t.get("log", []):
        at = _t(e.get("at"))
        if not at:
            continue
        text, st = e.get("text") or "", e.get("status")
        kind = (("waiting" if text.startswith("Needs input") else "review" if text.startswith("Ready for review") else "busy")
                if st == "doing" else "queue" if st == "todo" else None)
        if cur and kind != cur[0]:
            out.append((cur[0], cur[1], at))
            cur = None
        if kind and not cur:
            cur = (kind, at)
    if cur:
        out.append((cur[0], cur[1], now))
    return out


def build(tasks, now=None, feed_limit=60, abandoned_min=None):
    now = now or datetime.now()
    abandoned_min = ABANDONED_MIN if abandoned_min is None else abandoned_min
    events, by_agent, done_minutes = [], {}, []
    done_today = events_today = 0
    today = now.date()
    win_start = now - timedelta(minutes=WINDOW_MIN)
    lanes, agent_done_today = {}, {}
    queue_runs = []

    for t in tasks:
        marked = None
        for e in t.get("log", []):
            at = _t(e.get("at"))
            if not at:
                continue
            events.append({"at": e["at"], "task": t["id"], "title": t["title"], "agent": t.get("agent"),
                           "color": t.get("color"), "text": e.get("text", ""), "progress": e.get("progress", 0),
                           "status": e.get("status")})
            if at.date() == today:
                events_today += 1
            if e.get("text") in ("Marked done", "Moved to done"):
                marked = at
        if t["status"] == "done" and marked:
            if marked.date() == today:
                done_today += 1
                if t.get("agent"):
                    agent_done_today[t["agent"]] = agent_done_today.get(t["agent"], 0) + 1
            created = _t(t.get("created"))
            if created and marked >= created:
                done_minutes.append((marked - created).total_seconds() / 60)
        if t.get("agent"):
            by_agent.setdefault(t["agent"], []).append(t)
        for kind, a, b in segments(t, now):
            if b < win_start:
                continue
            a = max(a, win_start)
            if kind == "queue":
                queue_runs.append((a, b))
            elif t.get("agent"):
                lanes.setdefault(t["agent"], []).append(
                    {"k": kind, "a": a.strftime(FMT), "b": b.strftime(FMT), "t": t["title"]})

    events.sort(key=lambda e: e["at"], reverse=True)

    agents = []
    for name, ts in by_agent.items():
        ts.sort(key=lambda t: t.get("updated", ""), reverse=True)
        doing = [t for t in ts if t["status"] == "doing"]
        asking = [t for t in doing if t.get("needs_input")]
        reviewing = [t for t in doing if t.get("review")]
        cur = (asking or reviewing or doing or ts)[0]
        last = _t(cur.get("updated"))
        quiet = bool(doing) and (last is None or (now - last) > timedelta(minutes=STALE_MIN))
        abandoned = bool(doing) and (last is None or (now - last) > timedelta(minutes=abandoned_min))
        state = ("waiting" if asking else "review" if reviewing else
                 "idle" if not doing else ("abandoned" if abandoned else "quiet" if quiet else "working"))
        times = [_t(e["at"]) for e in events if e["agent"] == name]
        began = next((e["at"] for e in cur.get("log", []) if e.get("status") == "doing" and _t(e.get("at"))),
                     cur.get("created"))
        recent = [{"at": e["at"], "text": e.get("text", "")} for e in reversed(cur.get("log", []))][:3]   # newest first
        agents.append({
            "name": name, "color": next((t.get("color") for t in ts if t.get("color")), None),
            "state": state,
            "question": cur.get("question", ""),
            "task": cur["title"], "task_id": cur["id"], "progress": cur.get("progress", 0),
            "status_text": cur.get("status_text", ""), "updated": cur.get("updated"), "started": began, "recent": recent,
            "done": sum(1 for t in ts if t["status"] == "done"),
            "done_today": agent_done_today.get(name, 0),
            "spark": _bucket([x for x in times if x], now, SPARK_BUCKETS, SPARK_MIN),
        })
    order = {"abandoned": 0, "waiting": 1, "review": 2, "working": 3, "quiet": 4, "idle": 5}
    agents.sort(key=lambda a: (order[a["state"]], a["name"]))

    for name in lanes:
        lanes[name].sort(key=lambda r: r["a"])
    waiting_s = sum((_t(r["b"]) - _t(r["a"])).total_seconds() for rs in lanes.values() for r in rs if r["k"] in ("waiting", "review"))
    queue = [sum(1 for a, b in queue_runs if a <= tm <= b)   # sampled at each bucket's end; the last one is "now"
             for tm in (now - timedelta(minutes=WINDOW_MIN - (i + 1) * TIMELINE_MIN) for i in range(TIMELINE_BUCKETS))]

    return {
        "now": now.strftime(FMT),
        "window_min": WINDOW_MIN,
        "lanes": lanes,                 # per agent: coloured runs inside the window
        "queue": queue,                 # unclaimed Todo tasks per time bucket
        "waiting_s": round(waiting_s),  # agent-seconds spent waiting on / for the user

        "agents": agents,
        "events": events[:feed_limit],
        "totals": {
            "working": sum(1 for t in tasks if t["status"] == "doing"),
            "waiting": sum(1 for t in tasks if t["status"] == "doing" and t.get("needs_input")),
            "review": sum(1 for t in tasks if t["status"] == "doing" and t.get("review")),
            "quiet": sum(1 for a in agents if a["state"] == "quiet"),
            "abandoned": sum(1 for a in agents if a["state"] == "abandoned"),
            "done_today": done_today,
            "events_today": events_today,
            "avg_minutes": round(sum(done_minutes) / len(done_minutes), 1) if done_minutes else None,
            "queued": sum(1 for t in tasks if t["status"] == "todo"),
        },
        "timeline": _bucket([_t(e["at"]) for e in events if _t(e["at"])], now, TIMELINE_BUCKETS, TIMELINE_MIN),
    }
