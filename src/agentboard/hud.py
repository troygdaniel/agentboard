"""Aggregate board data for the HUD view: agents, activity feed, totals, timeline."""
from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%M:%S"
STALE_MIN = 10
SPARK_BUCKETS, SPARK_MIN = 12, 5      # last hour in 5-minute buckets
TIMELINE_BUCKETS, TIMELINE_MIN = 24, 15  # last 6 hours in 15-minute buckets


def _t(s):
    try:
        return datetime.strptime(s, FMT)
    except (TypeError, ValueError):
        return None


def _bucket(times, now, n, minutes):
    out = [0] * n
    for t in times:
        age = (now - t).total_seconds() / 60
        if 0 <= age < n * minutes:
            out[n - 1 - int(age // minutes)] += 1
    return out


def build(tasks, now=None, feed_limit=60):
    now = now or datetime.now()
    events, by_agent, done_minutes = [], {}, []
    done_today = events_today = 0
    today = now.date()

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
            created = _t(t.get("created"))
            if created and marked >= created:
                done_minutes.append((marked - created).total_seconds() / 60)
        if t.get("agent"):
            by_agent.setdefault(t["agent"], []).append(t)

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
        state = ("waiting" if asking else "review" if reviewing else
                 "idle" if not doing else ("quiet" if quiet else "working"))
        times = [_t(e["at"]) for e in events if e["agent"] == name]
        began = next((e["at"] for e in cur.get("log", []) if e.get("status") == "doing" and _t(e.get("at"))),
                     cur.get("created"))
        agents.append({
            "name": name, "color": next((t.get("color") for t in ts if t.get("color")), None),
            "state": state,
            "question": cur.get("question", ""),
            "task": cur["title"], "task_id": cur["id"], "progress": cur.get("progress", 0),
            "status_text": cur.get("status_text", ""), "updated": cur.get("updated"), "started": began,
            "done": sum(1 for t in ts if t["status"] == "done"),
            "spark": _bucket([x for x in times if x], now, SPARK_BUCKETS, SPARK_MIN),
        })
    order = {"waiting": 0, "review": 1, "working": 2, "quiet": 3, "idle": 4}
    agents.sort(key=lambda a: (order[a["state"]], a["name"]))

    return {
        "now": now.strftime(FMT),
        "agents": agents,
        "events": events[:feed_limit],
        "totals": {
            "working": sum(1 for t in tasks if t["status"] == "doing"),
            "waiting": sum(1 for t in tasks if t["status"] == "doing" and t.get("needs_input")),
            "review": sum(1 for t in tasks if t["status"] == "doing" and t.get("review")),
            "quiet": sum(1 for a in agents if a["state"] == "quiet"),
            "done_today": done_today,
            "events_today": events_today,
            "avg_minutes": round(sum(done_minutes) / len(done_minutes), 1) if done_minutes else None,
            "queued": sum(1 for t in tasks if t["status"] == "todo"),
        },
        "timeline": _bucket([_t(e["at"]) for e in events if _t(e["at"])], now, TIMELINE_BUCKETS, TIMELINE_MIN),
    }
