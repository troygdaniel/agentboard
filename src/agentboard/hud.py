"""Aggregate board data for the HUD view: agents, activity feed, totals, timeline, actions."""
import re
from datetime import datetime, timedelta

FMT = "%Y-%m-%dT%H:%M:%S"
STALE_MIN = 10
ABANDONED_MIN = 120    # default: flag a Doing task as stale/abandoned after this many idle minutes.
                       # Much longer than STALE_MIN's "quiet" warning; overridden by [board].stale_minutes
                       # in config.toml (see cli.cmd_list's --stale and server.py's /api/config, /api/hud).
SPARK_BUCKETS, SPARK_MIN = 12, 5      # last hour in 5-minute buckets
TIMELINE_BUCKETS, TIMELINE_MIN = 30, 2   # last hour in 2-minute buckets (same window as the lanes)
WINDOW_MIN = TIMELINE_BUCKETS * TIMELINE_MIN


def stale_minutes(conf):
    """The [board] stale_minutes setting, or the default when it is missing or not a positive number."""
    v = (conf or {}).get("board", {}).get("stale_minutes", ABANDONED_MIN)
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else ABANDONED_MIN


def retired(conf):
    """[hud] retired = ["AGENT-5"]: agent names the HUD leaves out (their cards and history stay).
    Anything that is not a list of strings is ignored."""
    v = (conf or {}).get("hud", {}).get("retired", [])
    return {x.strip() for x in v if isinstance(x, str) and x.strip()} if isinstance(v, list) else set()


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

    Subtasks are grouped under their parent in "subs". A parent finished that day lists all its
    finished subtasks; one still in progress shows up (partial=True) only if some of its subtasks
    finished that day. "n"/"n_done" are its subtask totals.
    """
    day = day or datetime.now().date()
    by_id = {t["id"]: t for t in tasks}
    kids = {}
    for t in tasks:
        if t.get("parent_id") in by_id:
            kids.setdefault(t["parent_id"], []).append(t)

    def brief(k):
        return {"id": k["id"], "title": k["title"], "result": k.get("result") or k.get("status_text") or ""}

    out = []
    for t in tasks:
        if t.get("parent_id") in by_id:
            continue
        ks = kids.get(t["id"], [])
        m = _marked_at(t) if t["status"] == "done" else None
        full = bool(m and m.date() == day)
        ended = [(_marked_at(k), k) for k in ks if k["status"] == "done"]
        today = [(mk, k) for mk, k in ended if mk and mk.date() == day]
        if not full and not today:
            continue
        shown = ended if full else today
        at = m if full else max(mk for mk, _ in today)
        out.append({"id": t["id"], "title": t["title"], "agent": t.get("agent"),
                    "result": t.get("result") or t.get("status_text") or "", "at": at.strftime(FMT),
                    "partial": not full, "n": len(ks), "n_done": len(ended),
                    "subs": [brief(k) for _, k in sorted(shown, key=lambda x: x[0] or datetime.min)]})
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


# ---- what needs a human: the ACTION strip -----------------------------------------------------
_ACTION_RE = re.compile(r"^\s*ACTION\b\s*:?\s*(?P<rest>.*)$", re.I)
_WHO_RE = re.compile(r"^(?P<who>Troy|ORCH|[A-Z][A-Z0-9-]*|none)\s*:\s*(?P<what>.+)$", re.I)


def parse_action(text):
    """Pull 'who: what' out of the three-line report shape agents write (ACTION / STATUS / WHY,
    on separate lines or joined with '|'). Returns {"who", "what", "status", "why"}; who is
    'Troy', 'ORCH', an agent name, 'none', or '' when the text is not in that shape."""
    out = {"who": "", "what": "", "status": "", "why": ""}
    if not text:
        return out
    # lines, ' | ', or the words STATUS / WHY run on inside one line ("ACTION Troy: x. STATUS y")
    parts = [x.strip() for x in re.split(r"\n|\s\|\s|\s(?=(?:STATUS|WHY)\b\s*:?\s)", str(text)) if x.strip()]
    for part in parts:
        m = _ACTION_RE.match(part)
        if m:
            rest = m.group("rest").strip()
            w = _WHO_RE.match(rest)
            if w:
                out["who"], out["what"] = w.group("who"), w.group("what").strip()
            elif rest.lower().startswith("none"):
                out["who"], out["what"] = "none", rest[4:].strip(" .:-")
            else:
                out["what"] = rest
            continue
        for key in ("status", "why"):
            m2 = re.match(rf"^\s*{key}\b\s*:?\s*(.*)$", part, re.I)
            if m2 and not out[key]:
                out[key] = m2.group(1).strip()
    if out["who"].lower() == "troy":
        out["who"] = "Troy"
    elif out["who"].lower() == "orch":
        out["who"] = "ORCH"
    elif out["who"].lower() == "none":
        out["who"] = "none"
    return out


def _since(t, prefix):
    """When the task last entered the state whose log line starts with `prefix`, else its update time."""
    at = None
    for e in t.get("log", []):
        if (e.get("text") or "").startswith(prefix):
            ts = _t(e.get("at"))
            if ts:
                at = ts
    return at or _t(t.get("updated"))


def actions(tasks, now=None, abandoned_min=None):
    """Every card that needs a person, one row each, most urgent first: asks (someone is blocked
    on an answer), then reviews (work waiting for sign-off), then abandoned cards (an agent went
    quiet). who/what come from the ACTION line when the agent wrote one, else a sensible default
    (asks and reviews are for Troy unless the text names someone else)."""
    now = now or datetime.now()
    abandoned_min = ABANDONED_MIN if abandoned_min is None else abandoned_min
    by_id = {t["id"]: t for t in tasks}
    out = []
    for t in tasks:
        if t.get("status") != "doing" or t.get("parent_id") in by_id or t.get("archived"):
            continue
        agent = t.get("agent") or "board"
        if t.get("needs_input"):
            kind, text, since = "ask", t.get("question") or t.get("status_text") or "", _since(t, "Needs input")
        elif t.get("review"):
            kind, text, since = "review", t.get("result") or t.get("status_text") or "", _since(t, "Ready for review")
        else:
            idle = minutes_idle(t, now)
            if idle is None or idle < abandoned_min:
                continue
            kind, text, since = "stale", t.get("status_text") or "", _t(t.get("updated"))
        parsed = parse_action(text)
        who = parsed["who"] or ("ORCH" if kind == "stale" else "Troy")
        if who == "none" and kind != "stale":
            who = "Troy"   # an ask or a review always needs a person, whatever the text says
        if kind == "stale":
            what = parsed["what"] or f"check on {agent}: no update for {dur(idle)}"
        else:
            what = parsed["what"] or text or ("answer the question" if kind == "ask" else "sign off")
        age = max(0, int((now - since).total_seconds() // 60)) if since else None
        out.append({
            "id": t["id"], "title": t["title"], "agent": agent, "color": t.get("color"),
            "project_id": t.get("project_id"), "kind": kind, "who": who, "what": what,
            "status": parsed["status"], "why": parsed["why"], "text": text,
            "since": since.strftime(FMT) if since else None, "age_min": age,
        })
    rank = {"ask": 0, "review": 1, "stale": 2}
    out.sort(key=lambda a: (0 if a["who"] == "Troy" else 1, rank[a["kind"]], -(a["age_min"] or 0)))
    return out


def dur(minutes):
    m = int(minutes or 0)
    return f"{m}m" if m < 60 else f"{m // 60}h{m % 60:02d}"


def build(tasks, now=None, feed_limit=60, abandoned_min=None, retired=()):
    """retired: agent names to leave out of agents/lanes/actions (see retired()); their cards still
    count in the totals, feed and timeline, so history is untouched."""
    now = now or datetime.now()
    abandoned_min = ABANDONED_MIN if abandoned_min is None else abandoned_min
    retired = set(retired or ())
    events, by_agent, done_minutes = [], {}, []
    done_today = events_today = 0
    today = now.date()
    win_start = now - timedelta(minutes=WINDOW_MIN)
    lanes, agent_done_today = {}, {}
    queue_runs = []
    by_id = {t["id"]: t for t in tasks}
    parents = {t["parent_id"] for t in tasks if t.get("parent_id") in by_id}
    # Subtasks are detail of their parent: the agent rows, the totals and the queue count the parent
    # only (a 4-subtask card is one piece of work), while the activity feed and the lanes show each
    # subtask's own events, labelled "parent › subtask" so they read in context.
    top = [t for t in tasks if t.get("parent_id") not in by_id]

    def label(t):
        p = by_id.get(t.get("parent_id"))
        return f"{p['title']} › {t['title']}" if p else t["title"]

    for t in tasks:
        is_sub = t.get("parent_id") in by_id
        marked = None
        for e in t.get("log", []):
            at = _t(e.get("at"))
            if not at:
                continue
            events.append({"at": e["at"], "task": t["id"], "title": label(t), "agent": t.get("agent"),
                           "color": t.get("color"), "text": e.get("text", ""), "progress": e.get("progress", 0),
                           "status": e.get("status"),
                           "label": f"{t['parent_id']} › {t['id']}" if is_sub else t["id"]})
            if at.date() == today:
                events_today += 1
            if e.get("text") in ("Marked done", "Moved to done"):
                marked = at
        if t["status"] == "done" and marked and not is_sub:
            if marked.date() == today:
                done_today += 1
                if t.get("agent"):
                    agent_done_today[t["agent"]] = agent_done_today.get(t["agent"], 0) + 1
            created = _t(t.get("created"))
            if created and marked >= created:
                done_minutes.append((marked - created).total_seconds() / 60)
        if t.get("agent") and not is_sub and t["agent"] not in retired:
            by_agent.setdefault(t["agent"], []).append(t)
        for kind, a, b in segments(t, now):
            if b < win_start:
                continue
            a = max(a, win_start)
            if kind == "queue":
                if not is_sub:
                    queue_runs.append((a, b))
            elif kind == "busy" and t["id"] in parents:
                continue   # its subtasks' own runs say what the agent was doing; don't paint over them
            elif t.get("agent") and t["agent"] not in retired:
                lanes.setdefault(t["agent"], []).append(
                    {"k": kind, "a": a.strftime(FMT), "b": b.strftime(FMT), "t": label(t)})

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
        feed = [(e, "") for e in cur.get("log", [])] + [
            (e, k["title"] + ": ") for k in tasks if k.get("parent_id") == cur["id"] for e in k.get("log", [])]
        feed.sort(key=lambda x: x[0].get("at", ""))
        recent = [{"at": e["at"], "text": pre + e.get("text", "")} for e, pre in reversed(feed)][:3]   # newest first
        agents.append({
            "name": name, "color": next((t.get("color") for t in ts if t.get("color")), None),
            "state": state,
            "question": cur.get("question", ""),
            "task": cur["title"], "task_id": cur["id"], "progress": cur.get("progress", 0),
            "status_text": cur.get("status_text", ""), "updated": cur.get("updated"), "started": began, "recent": recent,
            "done": sum(1 for t in ts if t["status"] == "done"),
            "done_today": agent_done_today.get(name, 0),
            "open": len(doing),                                    # cards this agent holds in Doing
            "open_titles": [t["title"] for t in doing[:4]],
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
        "actions": actions([t for t in top if t.get("agent") not in retired], now, abandoned_min),
        "events": events[:feed_limit],
        "totals": {
            "working": sum(1 for t in top if t["status"] == "doing"),
            "waiting": sum(1 for t in top if t["status"] == "doing" and t.get("needs_input")),
            "review": sum(1 for t in top if t["status"] == "doing" and t.get("review")),
            "quiet": sum(1 for a in agents if a["state"] == "quiet"),
            "abandoned": sum(1 for a in agents if a["state"] == "abandoned"),
            "done_today": done_today,
            "events_today": events_today,
            "avg_minutes": round(sum(done_minutes) / len(done_minutes), 1) if done_minutes else None,
            "queued": sum(1 for t in top if t["status"] == "todo"),
        },
        "timeline": _bucket([_t(e["at"]) for e in events if _t(e["at"])], now, TIMELINE_BUCKETS, TIMELINE_MIN),
    }
