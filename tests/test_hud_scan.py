"""hud.build visits what changed lately, not every log line of every card (finding the-hud-rebuild-scans-every-card: 50 ms at 5,000 cards, 30,000
log stamps parsed and 30,000 event dicts built on every rebuild, to show 60 feed lines and one hour of charts).

`reference_build` below is hud.build as it was before the change, copied as it stood; the new build must return exactly what it returns, on boards of every
shape the fuzz can make (quiet boards, busy ones, subtasks, retired agents, stamps that do not parse, logs out of order, ties). The counting tests do not
time anything, so a busy Mac cannot flake them."""
import random
import unittest
from datetime import datetime, timedelta
from unittest import mock

from agentboard import hud
from agentboard.hud import (ABANDONED_MIN, FMT, STALE_MIN, SPARK_BUCKETS, SPARK_MIN, TIMELINE_BUCKETS, TIMELINE_MIN, WINDOW_MIN, _bucket, _t, actions, awake, chart, segments)
from agentboard.store import DEFAULT_OWNER

def reference_build(tasks, now=None, feed_limit=60, abandoned_min=None, retired=(), roster=(), owner=DEFAULT_OWNER, asleep=()):
    """retired: agent names to leave out of agents/lanes/actions (see retired()); their cards still
    count in the totals, feed and timeline, so history is untouched. roster: agent names that belong on
    the HUD even with no card yet (they show as idle, folded with the other idle agents). owner: the human's name, as the board's
    config sets it; the actions that wait on a person are theirs. asleep: the stretches the board was not running (awake.windows): they never
    count towards an agent's quiet, so a closed lid does not make every agent silent."""
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
                           "text": e.get("text", ""), "progress": e.get("progress", 0),
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
        idle_awake = awake.awake_minutes(last, now, asleep) if last is not None else None   # minutes since it was last heard that the board was running
        quiet = bool(doing) and (last is None or idle_awake > STALE_MIN)
        abandoned = bool(doing) and (last is None or idle_awake > abandoned_min)
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
            "name": name,
            "state": state, "chart": chart(cur, [k for k in tasks if k.get("parent_id") == cur["id"]], now),
            "question": cur.get("question", ""),
            "task": cur["title"], "task_id": cur["id"], "progress": cur.get("progress", 0),
            "status_text": cur.get("status_text", ""), "updated": cur.get("updated"), "started": began, "recent": recent,
            "done": sum(1 for t in ts if t["status"] == "done"),
            "done_today": agent_done_today.get(name, 0),
            "open": len(doing),                                    # cards this agent holds in Doing
            "quiet_min": None if idle_awake is None else round(idle_awake),   # minutes since it was last heard, the board asleep not counted (None: never)
            "open_titles": [t["title"] for t in doing[:4]],
            "spark": _bucket([x for x in times if x], now, SPARK_BUCKETS, SPARK_MIN),
        })
    for name in roster:   # a configured peer with no card yet is still an agent: idle, with nothing to say
        if name and name not in by_agent and name not in retired:
            agents.append({"name": name, "state": "idle", "chart": {"pct": [None] * TIMELINE_BUCKETS, "events": [0] * TIMELINE_BUCKETS},
                           "question": "", "task": "", "task_id": "", "progress": 0, "status_text": "", "updated": None, "started": None,
                           "recent": [], "done": 0, "done_today": 0, "open": 0, "open_titles": [], "spark": [0] * SPARK_BUCKETS})
    order = {"abandoned": 0, "waiting": 1, "review": 2, "working": 3, "quiet": 4, "idle": 5}
    agents.sort(key=lambda a: (order[a["state"]], a["name"]))
    idle = [a for a in agents if a["state"] == "idle"]

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
        # the idle agents folded into one line: who, how many, and the one fact that matters for each (what they last did, when)
        "idle": {"n": len(idle), "done_today": sum(a["done_today"] for a in idle),
                 "agents": [{"name": a["name"], "task": a["task"], "updated": a["updated"], "done_today": a["done_today"]} for a in idle]},
        "actions": actions([t for t in top if t.get("agent") not in retired], now, abandoned_min, owner),
        "owner": owner,
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


NOW = datetime(2026, 11, 15, 22, 30, 0)
AGENTS = ["Atlas", "Orion", "Vega", "Lyra"]


def stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).strftime(FMT)


def fuzz_board(seed, n=60, quiet=False):
    r = random.Random(seed)
    tasks = []
    for i in range(n):
        st = r.choice(["done", "done", "done", "doing", "todo", "backlog"])
        age = r.choice([5, 20, 50, 90, 200, 900, 3000, 20000]) if not quiet else r.choice([3000, 20000, 40000])
        log = []
        t0 = age + r.randint(0, 600)
        for k in range(r.randint(0, 8)):
            m = t0 - k * r.randint(1, 120)
            e = {"at": stamp(max(m, 0)), "status": r.choice(["todo", "doing", "doing", "done", None]), "progress": r.randint(0, 100),
                 "text": r.choice(["Claimed by x", "Needs input: q", "Ready for review: r", "Marked done", "Moved to done", "note"])}
            if r.random() < 0.04:
                e["at"] = r.choice(["", "yesterday", "2026-11-15T7:05:09", "2026-02-30T10:00:00", "2026-11-15", "2026-11-15T22:29:59 extra"])
            log.append(e)
        if r.random() < 0.15:
            r.shuffle(log)
        t = {"id": f"t{i}", "title": f"Card {i}", "description": "", "status": st, "progress": r.randint(0, 100), "status_text": "", "ctx": [], "prompt": "",
             "created": stamp(t0 + 30), "updated": stamp(age), "log": log}
        if r.random() < 0.9:
            t["agent"] = r.choice(AGENTS)
        if i > 3 and r.random() < 0.3:
            t["parent_id"] = f"t{r.randint(0, i - 1)}"
        if r.random() < 0.1:
            t["needs_input"] = True
            t["question"] = "ACTION you: pick one. STATUS waiting. WHY blocked."
        if r.random() < 0.1:
            t["review"] = True
        tasks.append(t)
    return tasks


class SameAsBefore(unittest.TestCase):
    def check(self, tasks, **kw):
        self.assertEqual(hud.build(tasks, now=NOW, **kw), reference_build(tasks, now=NOW, **kw))

    def test_fuzz_busy_boards(self):
        for seed in range(60):
            with self.subTest(seed=seed):
                self.check(fuzz_board(seed), roster=["Nova"], retired={"Lyra"} if seed % 3 == 0 else (), asleep=[])

    def test_fuzz_quiet_boards_that_need_older_lines_for_the_feed(self):
        for seed in range(30):
            with self.subTest(seed=seed):
                self.check(fuzz_board(1000 + seed, n=40, quiet=True))

    def test_fuzz_with_a_small_feed(self):
        for seed in range(20):
            with self.subTest(seed=seed):
                self.check(fuzz_board(2000 + seed), feed_limit=5)
                self.check(fuzz_board(3000 + seed), feed_limit=500)

    def test_an_empty_board_and_one_card(self):
        self.check([])
        self.check(fuzz_board(7, n=1))

    def test_a_board_that_crosses_midnight(self):
        for hour, minute in ((0, 20), (0, 59), (23, 59), (12, 0)):
            tasks = fuzz_board(55)
            global NOW
            old, NOW = NOW, datetime(2026, 11, 16, hour, minute, 30)
            try:
                self.check(tasks)
            finally:
                NOW = old


def old_board(cards=1500, recent=80):
    """Many finished cards whose lines are days old, and a few busy ones: the shape of a board after a month."""
    tasks = []
    for i in range(cards):
        tasks.append({"id": f"d{i}", "title": f"Old {i}", "description": "", "status": "done", "progress": 100, "status_text": "", "ctx": [], "prompt": "",
                      "created": stamp(60000 + i), "updated": stamp(50000 + i), "agent": AGENTS[i % 4],
                      "log": [{"at": stamp(59000 + i + 10 * k), "status": "doing" if k < 5 else "done", "progress": 20 * k, "text": "Marked done" if k == 5 else "step"} for k in range(6)]})
    for i in range(recent):
        tasks.append({"id": f"r{i}", "title": f"New {i}", "description": "", "status": "doing", "progress": 10, "status_text": "", "ctx": [], "prompt": "",
                      "created": stamp(200), "updated": stamp(i % 50), "agent": AGENTS[i % 4],
                      "log": [{"at": stamp(i % 50 + k), "status": "doing", "progress": 10, "text": f"step {k}"} for k in range(3)]})
    return tasks


class DoesNotVisitOldLines(unittest.TestCase):
    def test_the_old_cards_are_not_parsed_line_by_line(self):
        tasks = old_board()
        calls = []
        real = hud._t

        def counting(s):
            calls.append(1)
            return real(s)
        with mock.patch.object(hud, "_t", counting):
            out = hud.build(tasks, now=NOW)
        self.assertEqual(out, reference_build(tasks, now=NOW))
        self.assertLess(len(calls), 5 * len(tasks), f"{len(calls)} stamp parses for {len(tasks)} cards: every log line of every old card is still visited")

    def test_the_old_cards_are_not_walked_for_their_runs(self):
        tasks = old_board()
        with mock.patch.object(hud, "segments", wraps=hud.segments) as seg:
            hud.build(tasks, now=NOW)
        self.assertLess(seg.call_count, 200, f"{seg.call_count} calls to segments for 1,580 cards, 1,500 of them finished days ago")


if __name__ == "__main__":
    unittest.main()
