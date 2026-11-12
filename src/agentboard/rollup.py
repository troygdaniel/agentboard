"""The roll-up: the whole board in one page for ORCH (and the owner), so work can be redistributed without opening every card.

`agentboard rollup` reads the same data the HUD does and says, in this order: what waits on the owner, what each agent holds, what is
stuck, what is next in Todo (with what an earlier agent learned on it), what finished lately and what it learned, and the moves that
follow (release a stuck card back to Todo, hand Todo cards to idle agents). Read-only: it changes nothing."""
import re
from datetime import datetime, timedelta

from . import hud

_LEARNED = re.compile(r"^\s*(?:#{1,6}\s*|\*\*)(?:what (?:i|we) )?(?:learned|lessons?(?: learned)?|gotchas|for next time)\b.*$", re.I)
_HEAD = re.compile(r"^\s*(?:#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$)")


def learned_text(body_md):
    """The `## Learned` section of a review body, as plain lines (empty when the body has none)."""
    out, on = [], False
    for ln in str(body_md or "").splitlines():
        if _LEARNED.match(ln):
            on = True
            continue
        if on and _HEAD.match(ln):
            break
        if on and ln.strip():
            out.append(ln.strip().lstrip("-* ").strip())
    return out


def _one(text, n=110):
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build(store, now=None, since_hours=24):
    """The roll-up as data: totals, who waits on the owner, agents, stuck cards, the Todo queue, finished cards and the moves that follow."""
    from . import prompt
    now = now or datetime.now()
    tasks = store.load_all()
    conf = prompt.load_config(store.dir)
    data = hud.build(tasks, now=now, abandoned_min=hud.stale_minutes(conf), retired=hud.retired(conf), roster=hud.roster(conf), owner=store.owner)
    live = [t for t in tasks if not t.get("archived") and not t.get("parent_id")]
    by_id = {t["id"]: t for t in tasks}

    def card(t):
        L = t.get("learned") if isinstance(t.get("learned"), dict) else None
        kids = [k for k in tasks if k.get("parent_id") == t["id"]]
        return {"id": t["id"], "title": t["title"], "agent": t.get("agent"), "progress": t.get("progress", 0), "status_text": t.get("status_text", ""),
                "subs": [sum(1 for k in kids if k["status"] == "done"), len(kids)] if kids else None,
                "idle_min": hud.minutes_idle(t, now) if t["status"] == "doing" else None,
                "resumes": {"by": L.get("by"), "progress": L.get("progress", 0), "status": L.get("status", ""), "asking": L.get("asking", "")} if L else None,
                "blocked_by": [b for b in (t.get("blocked_by") or []) if b in by_id and by_id[b]["status"] != "done"]}

    me = {"you", str(store.owner).lower()}
    waiting = [a for a in data["actions"] if a["kind"] in ("ask", "review") and str(a.get("who", "")).lower() in me]
    stuck = [a for a in data["agents"] if a["state"] in ("quiet", "abandoned")]
    held = {}
    for t in live:
        if t["status"] == "doing" and t.get("agent"):
            held.setdefault(t["agent"], []).append(card(t))
    todo = [card(t) for t in live if t["status"] == "todo"]
    since = now - timedelta(hours=since_hours)
    finished = []
    for t in sorted((x for x in live if x["status"] == "done"), key=lambda x: x.get("updated", ""), reverse=True):
        at = hud._t(t.get("updated"))
        if not at or at < since:
            continue
        L = learned_text(t.get("body_md"))
        carried = t.get("learned") if isinstance(t.get("learned"), dict) else {}
        finished.append({"id": t["id"], "title": t["title"], "agent": t.get("agent"), "result": t.get("result", ""),
                         "learned": L[:3] or ([carried["status"]] if carried.get("status") else [])})
    return {"now": now.strftime("%Y-%m-%d %H:%M"), "owner": store.owner, "totals": data["totals"], "waiting": waiting,
            "agents": [dict(a, held=held.get(a["name"], [])) for a in data["agents"]], "stuck": stuck, "todo": todo, "finished": finished,
            "idle": [a["name"] for a in data["agents"] if a["state"] == "idle"], "since_hours": since_hours}


def render(d):
    """The roll-up as the page ORCH reads: short lines, the owner's waiting items first, the moves last."""
    t, who = d["totals"], d["owner"]
    out = [f"# Roll-up · {d['now']}", "",
           f"{t['working']} in Doing · {t['waiting']} asking · {t['review']} in review · {t['queued']} in Todo · {t['done_today']} done today"
           + (f" · {t['quiet'] + t['abandoned']} quiet" if t["quiet"] + t["abandoned"] else "")]
    out += ["", f"## Waiting on {who if who != 'you' else 'the owner'}"]
    out += [f"- {a['id']} ({a.get('agent') or 'no agent'}): {_one(a.get('what') or a.get('title'))}" for a in d["waiting"]] or ["- nothing"]
    out += ["", "## Agents"]
    for a in d["agents"]:
        if a["state"] == "idle":
            continue
        out.append(f"- {a['name']} · {a['state']}")
        for c in a["held"]:
            subs = f" · {c['subs'][0]}/{c['subs'][1]} subtasks" if c["subs"] else ""
            idle = f" · quiet {hud.dur(c['idle_min'])}" if c["idle_min"] and c["idle_min"] >= hud.STALE_MIN else ""
            out.append(f"    {c['id']} {c['progress']}%{subs}{idle}: {_one(c['title'], 70)}" + (f" — {_one(c['status_text'], 70)}" if c["status_text"] else ""))
    if d["idle"]:
        out.append(f"- idle, free to take a card: {', '.join(d['idle'])}")
    if d["stuck"]:
        out += ["", "## Stuck"]
        out += [f"- {a['name']} has been {a['state']} on {a['task_id']} ({a['progress']}%): `agentboard release {a['task_id']}` sends it back to Todo with what it learned" for a in d["stuck"]]
    out += ["", "## Todo, next up first"]
    for c in d["todo"][:12]:
        tag = ""
        if c["resumes"]:
            r = c["resumes"]
            tag = f" ↩ resumes at {r['progress']}%" + (f" ({r['by']})" if r["by"] else "") + (f": {_one(r['status'], 60)}" if r["status"] else "")
        out.append(f"- {c['id']}: {_one(c['title'], 80)}{tag}" + (f" · blocked by {', '.join(c['blocked_by'])}" if c["blocked_by"] else ""))
    if not d["todo"]:
        out.append("- nothing queued")
    elif len(d["todo"]) > 12:
        out.append(f"- … and {len(d['todo']) - 12} more")
    out += ["", f"## Finished in the last {d['since_hours']}h"]
    for f in d["finished"][:10]:
        out.append(f"- {f['id']} ({f.get('agent') or 'no agent'}): {_one(f['result'] or f['title'])}")
        out += [f"    learned: {_one(x, 100)}" for x in f["learned"]]
    if not d["finished"]:
        out.append("- nothing")
    out += ["", "## Moves"]
    if d["idle"] and d["todo"]:
        out.append(f"- {len(d['idle'])} idle agent(s) and {len(d['todo'])} Todo card(s): tell an idle agent to `claim` the top Todo card (it picks up what an earlier agent learned)")
    if d["stuck"]:
        out.append("- release a stuck card first (`agentboard release <id>`, or `agentboard release --agent NAME` for all of one agent's), then hand it on")
    out.append("- `agentboard release <id>` sends a Doing card back to Todo, to the top, keeping its progress, history and what its agent learned")
    return "\n".join(out)
