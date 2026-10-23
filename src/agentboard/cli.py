"""agentboard command line."""
import argparse
import os
import shlex
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

from . import __version__
from . import hud as hudlib
from . import prompt as promptlib
from .server import serve
from .store import DIR_NAME, BoardError, Store, find_dir, subtask_counts

SAMPLE_CONFIG = '''\
# agentboard config. Providers add context to task prompts.
# Attach them to a task with:  agentboard add "Title" --ctx name[:arg]

# [providers.docs]            # sections of a markdown file; arg = section names
# type = "markdown"
# path = "CLAUDE.md"          # relative to the project root, or absolute
# max_chars = 4000
#
# [providers.notes]           # last N entries of a file
# type = "file-tail"
# path = "~/notes.md"
# entry_pattern = '^# \\['     # lines that start an entry (omit for last N lines)
# entries = 3
#
# [providers.mail]            # any HTTP search endpoint; {query} <- arg or task title
# type = "http"
# url = "http://localhost:5001/api/search?q={query}&limit=5"
# json_path = "results"
# fields = ["from", "subject", "date", "body"]
# private = true              # skipped by `agentboard prompt --public`
# redact = ["\\\\b\\\\d{3}-\\\\d{3}-\\\\d{4}\\\\b"]
#
# [providers.git]             # any shell command; {arg} and {title} are substituted
# type = "command"
# run = "git log --oneline -10"

# [ui]
# dispatch = false            # hide Copy prompt and the prompt preview (shown by default)

# [board]
# stale_minutes = 120         # flag a Doing task as stale/abandoned after this many idle minutes
#                              # (default 120; much longer than the board's 10-min "quiet" warning).
#                              # Surfaced by `agentboard list --stale`, a red card marker, and the HUD.

# [notify]                    # native macOS notification when a card needs input or is ready for review
# enabled = true               # off by default; osascript only, no new dependency
# sound = "Glass"               # optional: a macOS notification sound name (omit for silent)

# [prompt]
# template_file = "prompt.md"  # replaces the built-in template
'''


def _store():
    return Store(find_dir())


def cmd_init(a):
    d = Path.cwd() / DIR_NAME
    d.mkdir(exist_ok=True)
    cfg = d / "config.toml"
    if not cfg.exists():
        cfg.write_text(SAMPLE_CONFIG)
    (d / "tasks.json").touch()
    if not (d / "tasks.json").read_text().strip():
        (d / "tasks.json").write_text('{"tasks": []}')
    print(f"initialized {d}\nnext: agentboard add \"My first task\" --status todo && agentboard serve")


def cmd_add(a):
    t = _store().add(a.title, a.description or "", a.status, a.ctx, a.id, a.project, blocked_by=a.blocked_by,
                     parent_id=a.parent)
    print(f"added {t['id']} ({t['status']})")


def cmd_list(a):
    s = _store()
    threshold = hudlib.stale_minutes(promptlib.load_config(s.dir))
    tasks = s.load()
    counts = subtask_counts(tasks)
    ids = {t["id"] for t in tasks}
    for t in _tree_order(tasks):
        if t.get("archived") and not a.all:
            continue
        if a.status and t["status"] != a.status:
            continue
        idle = hudlib.minutes_idle(t)
        stale = idle is not None and idle >= threshold
        if a.stale and not stale:
            continue
        who = f"  [{t['agent']}]" if t.get("agent") else ""
        flag = f"  ⚠ STALE ({int(idle)}m idle)" if stale else ""
        sub = t.get("parent_id") in ids
        n, d = counts.get(t["id"], (0, 0))
        kids = f"  [{d}/{n} subtasks]" if n else ""
        name = f"  ↳ {t['id']}" if sub else t["id"]   # subtasks hang under their parent
        print(f"{name:30} {t['status']:8} {'Σ' if n else ' '}{t.get('progress', 0):3}%{who}{kids}{flag}  {t['title']}")


def _tree_order(tasks):
    """Board order, but each subtask listed right under its parent."""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        if t.get("parent_id") in ids:
            continue
        yield t
        yield from (k for k in tasks if k.get("parent_id") == t["id"])


TAIL_FEED_CAP = 500   # generous enough that a burst of activity between polls can't overrun a single snapshot


def _tail_fmt(e):
    at = e["at"].split("T", 1)[1] if "T" in e["at"] else e["at"]
    agent = e.get("agent") or "-"
    return f"{at}  {agent:<12.12}  {e.get('label') or e['task']:<30.30}  {e['text']}"


def _tail_fresh(events, last_at, seen):
    """events: newest-first, as from hud.build(). Returns (new events oldest-first, advanced last_at, advanced seen).

    Same-second collisions (two log entries sharing a timestamp) are disambiguated with a (task, at, text) set
    rather than just the watermark, since the log's timestamp resolution is whole seconds.
    """
    fresh = [e for e in events
             if e["at"] > last_at or (e["at"] == last_at and (e["task"], e["at"], e["text"]) not in seen)]
    if events:
        last_at = events[0]["at"]
        seen = {(e["task"], e["at"], e["text"]) for e in events if e["at"] == last_at}
    return list(reversed(fresh)), last_at, seen


def cmd_tail(a):
    """Watch board activity live in the terminal — the same event feed the HUD shows, polled from tasks.json."""
    s = _store()

    def snapshot():
        return hudlib.build(s.load(), feed_limit=TAIL_FEED_CAP)["events"]  # newest-first

    events = snapshot()
    # seed the watermark from the true newest event regardless of how much history --lines asks to print,
    # so a smaller --lines can never cause the first poll to replay what it skipped
    last_at = events[0]["at"] if events else time.strftime("%Y-%m-%dT%H:%M:%S")
    seen = {(e["task"], e["at"], e["text"]) for e in events if e["at"] == last_at}
    for e in reversed(events[:max(0, a.lines)]):
        print(_tail_fmt(e), flush=True)   # flush: stdout is block-buffered when piped/redirected, not a tty
    try:
        while True:
            time.sleep(a.interval)
            fresh, last_at, seen = _tail_fresh(snapshot(), last_at, seen)
            for e in fresh:
                print(_tail_fmt(e), flush=True)
    except KeyboardInterrupt:
        pass


def cmd_report(a):
    """Markdown recap of what was completed on a day (default: today), grouped by agent.

    Read-only; built on the same 'marked done' / activity-log aggregation the HUD uses
    (hud.done_on / hud.events_on), not a separate tracking mechanism. Paste it into a
    standup or a daily log.
    """
    if a.date:
        try:
            day = date.fromisoformat(a.date)
        except ValueError:
            raise BoardError(f"invalid --date '{a.date}'; use YYYY-MM-DD")
    else:
        day = date.today()
    tasks = _store().load()
    done = hudlib.done_on(tasks, day)
    events = hudlib.events_on(tasks, day)
    finished = [d for d in done if not d["partial"]]
    s = lambda n: "" if n == 1 else "s"

    print(f"# Daily recap — {day.isoformat()}")
    print()
    if not done:
        print(f"No tasks completed on {day.isoformat()}.")
    else:
        by_agent = {}
        for d in done:
            by_agent.setdefault(d["agent"] or "Unassigned", []).append(d)
        print(f"**{len(finished)} task{s(len(finished))} done** across {len(by_agent)} agent{s(len(by_agent))}"
              if finished else f"**No task finished**, {len(done)} in progress")
        print()
        for agent in sorted(by_agent):
            print(f"## {agent}")
            for d in by_agent[agent]:
                line = f"- **{d['title']}**"
                if d["partial"]:
                    line += f" _(in progress, {d['n_done']}/{d['n']} subtasks done)_"
                elif d["result"]:
                    line += f" — {d['result']}"
                print(line)
                for k in d["subs"]:   # subtasks grouped under their parent
                    print(f"  - {k['title']}" + (f" — {k['result']}" if k["result"] else ""))
            print()
    print(f"_{events} event{s(events)} logged on {day.isoformat()}._")


def cmd_project_add(a):
    p = _store().add_project(a.name, a.color, a.description or "", a.id)
    print(f"added project {p['id']}")


def cmd_project_list(a):
    for p in _store().load_projects():
        print(f"{p['id']:30} {p['name']}")


def cmd_project_edit(a):
    p = _store().update_project(a.id, a.name, a.color, a.description)
    print(f"updated project {p['id']}")


def cmd_project_rm(a):
    _store().delete_project(a.id)
    print(f"removed project {a.id}")


def cmd_project_assign(a):
    t = _store().set_project(a.task_id, a.project_id)
    print(f"{t['id']}: tied to project {a.project_id}")


def cmd_project_unassign(a):
    t = _store().set_project(a.task_id, None)
    print(f"{t['id']}: untied from its project")


def _chat_line(m):
    who = f"{m['sender']} (you)" if m["kind"] == "user" else m["sender"]
    return f"[{m['at']}] {who}: {m['text']}"


def cmd_chat_send(a):
    name = a.name or os.environ.get("AGENTBOARD_NAME") or ("Troy" if a.user else None)
    if not name:
        raise BoardError("give --name (or set AGENTBOARD_NAME) so the board can show who's talking")
    m = _store().chat_send(name, a.text, kind="user" if a.user else "agent")
    print(_chat_line(m))


def cmd_chat_tail(a):
    """Print recent chat; --follow polls and streams new messages (Ctrl+C stops)."""
    s = _store()
    msgs = s.chat_list(limit=a.limit)
    for m in msgs:
        print(_chat_line(m))
    if not a.follow:
        return
    last = msgs[-1]["seq"] if msgs else 0
    try:
        while True:
            time.sleep(a.interval)
            for m in s.chat_list(after=last):
                print(_chat_line(m))
                last = m["seq"]
    except KeyboardInterrupt:
        pass


WAIT_FLAGS = ("review", "needs_input")  # pseudo-targets: a flag on the task, not a column


def _wait_result(t, target):
    """A result line once `wait --status target` should stop on t, else None.

    'review' and 'needs_input' always end the wait early even when they aren't the target:
    a task stuck on 'review' may never reach 'done' until a human clicks Mark done, and
    'needs_input' means progress is stalled on the user, not on more polling.
    """
    if target == "review" and t.get("review"):
        return f"ready for review — {t.get('result', '')}"
    if target == "needs_input" and t.get("needs_input"):
        return f"needs input — {t.get('question', '')}"
    if target not in WAIT_FLAGS and t["status"] == target:
        return f"reached {target}"
    if target in WAIT_FLAGS and t["status"] == "done":   # signed off without a pause on the way: nothing left to wait for
        return f"done (target was {target})"
    if target not in WAIT_FLAGS and t.get("review"):
        return f"ready for review (target was {target}) — {t.get('result', '')}"
    if target != "needs_input" and t.get("needs_input"):
        return f"needs input (target was {target}) — {t.get('question', '')}"
    return None


def cmd_wait(a):
    """Block (polling tasks.json) until a task reaches --status, or flags review/needs input."""
    s = _store()
    start = time.time()
    try:
        while True:
            t = Store.get(s.load(), a.id)
            msg = _wait_result(t, a.status)
            if msg:
                print(f"{a.id}: {msg}")
                return
            if a.timeout and time.time() - start >= a.timeout:
                sys.exit(f"agentboard: wait timed out after {a.timeout}s ({a.id} still {t['status']})")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        pass


def _agent_name(a):
    name = a.name or os.environ.get("AGENTBOARD_NAME")
    if not name:
        raise BoardError("give --name (or set AGENTBOARD_NAME) so the board can show who is working")
    return name


# Kept out of the status-color families (--warn/--hwarn amber ~25-50°, --ok/--hok green ~145-165°,
# --err/--hbad red near 0/360°): an agent's color shows up on its cards' avatar ring and progress bar
# fill at all times, not just during ask/review/abandoned, so a palette hue in one of those bands
# would make a normal in-progress card from that agent misread as needing attention at a glance.
SPAWN_PALETTE = ["#22d3ee", "#6366f1", "#f472b6", "#3b82f6", "#d946ef", "#8b5cf6"]


def _as_escape(s):
    """Escape a string for embedding inside a double-quoted AppleScript literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _notify_cfg(board_dir):
    cfg = promptlib.load_config(board_dir).get("notify", {})
    return bool(cfg.get("enabled")), cfg.get("sound")


def _notify(board_dir, title, subtitle, body):
    """Native macOS notification via osascript — same no-dependency mechanism as `spawn`.

    Opt-in and off by default (see [notify] in config.toml); a notification failing or the
    platform not supporting it should never break an agent's ask/review, so this never raises.
    """
    if sys.platform != "darwin":
        return
    enabled, sound = _notify_cfg(board_dir)
    if not enabled:
        return
    script = f'display notification "{_as_escape(body)}" with title "{_as_escape(title)}" subtitle "{_as_escape(subtitle)}"'
    if sound:
        script += f' sound name "{_as_escape(sound)}"'
    try:
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    except OSError:
        pass


def _hex_rgb(color):
    """'#rrggbb' -> (r, g, b) scaled to AppleScript's 0-65535 range, or None if not hex."""
    c = color.lstrip("#")
    if len(c) != 6:
        return None
    try:
        r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    return (r * 257, g * 257, b * 257)


def cmd_spawn(a):
    if sys.platform != "darwin":
        raise BoardError("spawn only supports macOS Terminal.app right now")
    names = [n.strip() for n in a.names.split(",") if n.strip()]
    if not names:
        raise BoardError('give at least one name, e.g. agentboard spawn atlas,scribe,bolt')
    colors = [c.strip() for c in a.colors.split(",")] if a.colors else []
    cwd = os.getcwd()
    for i, name in enumerate(names):
        color = colors[i] if i < len(colors) else SPAWN_PALETTE[i % len(SPAWN_PALETTE)]
        cmdline = f"cd {shlex.quote(cwd)} && {a.cmd}"
        lines = ['tell application "Terminal"', "activate",
                 f'set newTab to do script "{_as_escape(cmdline)}"']
        rgb = _hex_rgb(color)
        if rgb:
            lines.append(f"set background color of newTab to {{{rgb[0]}, {rgb[1]}, {rgb[2]}}}")
            lines.append("set normal text color of newTab to {65535, 65535, 65535}")
        lines.append(f'set custom title of newTab to "{_as_escape(name)}"')
        if not a.no_rename:
            lines.append(f"delay {a.delay}")
            lines.append(f'do script "/rename {_as_escape(name)}" in newTab')
            lines.append("delay 0.4")
            lines.append(f'do script "/color {_as_escape(color)}" in newTab')
        lines.append("end tell")
        subprocess.run(["osascript", "-e", "\n".join(lines)], check=True)
    print(f"spawned {len(names)} session(s): {', '.join(names)}")


def cmd_start(a):
    t = _store().start(a.title, _agent_name(a), a.color or os.environ.get("AGENTBOARD_COLOR"),
                       a.description or "", a.id, a.project, blocked_by=a.blocked_by, force=a.force,
                       parent_id=a.parent)
    print(t["id"])  # agents use this id for update/done


INSTRUCTIONS = """\
## Agent board

This project tracks agent work on a shared board (`agentboard`). When you begin a distinct piece of work:

    ID=$(agentboard start "<short title>" --name "<your session name>" [--color <color>])
    agentboard update "$ID" <0-100> "<one-line status>"     # your REAL % done, updated every time it changes
    agentboard review "$ID" "<one-line result>"                # work complete -> the USER signs off and marks it done
    agentboard ask "$ID" "<one-line question>"                 # ONLY if blocked on the user; keep working after they answer

The percentage is what the list and HUD show at a glance, without anyone opening the card — keep
it current. Call `update` again whenever your estimate changes, not just at fixed checkpoints, and
walk it back if you discover more work than you thought; don't leave it sitting at a stale number.

Add `--body "<markdown>"` (or `--body-file <path>` for multi-line content) to `review`/`ask`
for a proper recap, diff, or report — it renders as formatted markdown in the detail panel,
which opens automatically when your card needs input or is ready for review.

NEVER mark your own task done. Finish with `review` and stop. Run
`agentboard done "$ID"` only if the user explicitly tells you to.

If you are handed a task id instead, run `agentboard claim <id> --name "<your session name>"`.
Use your own session name (and color, if you have one) so people can tell agents apart.
Create one task per deliverable, not per command. Keep titles short and status lines to one line.

Before claiming or starting a card, if anything about it is ambiguous, ask your orchestrator/coordinating
session a one-line question (e.g. via SendMessage) and wait for its answer first. It has visibility into
the whole board and can often answer without bothering the user; it escalates to them if it can't. This
is a one-time check before you start, not an ongoing back-and-forth once work is underway.

## Projects

Group related tasks under a project so they show up together on the board:

    agentboard project add "<name>" [--color <color>] [--description "..."]   # prints its id
    agentboard project list
    agentboard project assign <task_id> <project_id>     # tie any existing card to a project
    agentboard project unassign <task_id>                 # untie it
    agentboard add "<title>" --project <project_id>       # or tie it at creation time
    agentboard start "<title>" --name "<you>" --project <project_id>

## Subtasks

A big card can be split into subtasks (one level deep). A subtask is a normal task with a parent:

    agentboard add "<title>" --parent <parent_id>              # Troy/ORCH at planning time; follows the parent's column
    agentboard start "<title>" --name "<you>" --parent <id>    # an agent adding one mid-flight

When you claim a parent that has no subtasks yet, break it down first (same command). `claim <parent>`
takes every subtask with it. Then work the subtasks, not the parent (updating a subtask before its parent is in Doing is refused):

    agentboard update <sub_id> <0-100> "<one-line status>"     # a subtask at 100% closes itself: no review step
    agentboard review <parent_id> "<one-line result>"          # the deliverable is ready; open subtasks close with it

The parent's % is computed (the mean of its subtasks, shown with a Σ), so `update <parent>` only sets its
status line. Never call `review` or `done` on a subtask. Finished subtasks stay in their parent's card, shown as
completed, while the parent stays in Doing. `rm <parent>` and `done <parent>` take the remaining subtasks with them.

## Talking to other agents

Coordinating with another agent — who's on what, asking for a hand, splitting or handing off
work — goes in the shared chat, not only a private message, so the user can see it and jump in:

    agentboard chat send "<message>" --name "<your session name>"
    agentboard chat tail                                   # catch up, including the user jumping in
    agentboard chat tail --follow                           # keep watching live (Ctrl+C stops)

Write it like a quick Slack message to a teammate, not a status report: short, plain, skimmable in
a second — what you're doing or what you need, then stop.

    Good:          "grabbing the HUD legend task, shout if you're already on it"
    Good:          "done with the scroll-jump fix, up for review"
    Over-formal:   "I have completed the scroll-jump bug fix. The render() function's focus-restore
                    logic now uses preventScroll:true. The card is ready for your review."

Got a lot to say (a commit audit, a multi-part handoff)? Say it briefly and point at the card/task
id for the detail — don't paste the whole report inline.

Check it when you're blocked on coordinating with another agent, same as you'd check for a reply
to a private message. Use a private message instead only for something that genuinely shouldn't
be visible on the board.

## Dependencies

Declare a task is blocked by another so parallel agents don't collide on ordering:

    agentboard add "<title>" --blocked-by <task_id>            # repeat --blocked-by for more than one
    agentboard start "<title>" --name "<you>" --blocked-by <task_id>
    agentboard claim <id> --name "<you>"                        # refuses while a blocker isn't done (--force to override)

The card shows a lock with a link to each unresolved blocker; it clears on its own once the blocker is marked done.

## Sync

Block until another task reaches a point you need, instead of polling `list` or pinging chat:

    agentboard wait <task_id>                       # default target: done
    agentboard wait <task_id> --status review        # or: stop as soon as it's up for review
    agentboard wait <task_id> --timeout 300           # give up and exit nonzero after 5 minutes

`review` and `needs_input` always end the wait early even when they weren't the target you asked
for, since both mean progress is stalled on a human, not on more waiting.
"""


def cmd_instructions(a):
    print(INSTRUCTIONS.replace("agentboard ", f"{promptlib.agentboard_cmd(find_dir())} ") if a.absolute else INSTRUCTIONS)


def cmd_demo(a):
    """Fill the board with sample work so the UI has something to show. Idempotent."""
    s = _store()

    def seed(fn, *args, **kw):
        try:
            fn(*args, **kw)
        except BoardError:
            pass  # already seeded on an earlier run

    seed(s.add,"Write release notes", "v2.4 changelog from merged PRs.", "todo", task_id="demo-release-notes")
    seed(s.add, "Audit npm dependencies", "Flag anything unmaintained or with open CVEs.", "backlog", task_id="demo-audit")
    seed(s.start, "Refactor billing module", "atlas", "#3b82f6", task_id="demo-billing")
    for pct, text in ((20, "Mapped call sites (41 files)"), (45, "Extracted BillingService, tests green"),
                      (70, "Updating call sites in invoices/")):
        seed(s.update, "demo-billing", pct, text)
    seed(s.start, "Draft API docs", "scribe", "#6366f1", task_id="demo-docs")
    seed(s.update, "demo-docs", 30, "Reading route handlers")
    seed(s.start, "Set up CI", "bolt", "#8b5cf6", task_id="demo-ci")
    seed(s.update, "demo-ci", text="GitHub Actions: lint, test, deploy in 3 jobs", status="done")
    print("added sample tasks (ids start with demo-); remove with: agentboard rm --demo")
    if a.live:
        _demo_live(s, a.minutes)


def _demo_live(s, minutes):
    """Simulate agents working so the board and HUD have live activity."""
    import random
    import time
    agents = [("nova", "#22d3ee"), ("atlas", "#3b82f6"), ("scribe", "#6366f1"), ("echo", "#f472b6")]
    titles = ["Tune cache eviction", "Backfill audit log", "Split payments worker", "Harden webhook retries",
              "Trim bundle size", "Index search facets", "Rotate API keys", "Profile slow queries"]
    steps = ["Reading code", "Mapping call sites", "Writing tests", "Refactoring", "Running test suite",
             "Fixing edge cases", "Updating docs", "Benchmarking"]
    end = time.time() + minutes * 60
    n = max([int(t["id"].rsplit("-", 1)[-1]) for t in s.load()
             if t["id"].startswith("demo-live-") and t["id"].rsplit("-", 1)[-1].isdigit()] or [0])
    print(f"live demo for {minutes:g} min — open the board, press h for the HUD, sound on. Ctrl+C stops.")
    try:
        while time.time() < end:
            doing = [t for t in s.load() if t["status"] == "doing" and t["id"].startswith("demo-")]
            if len(doing) < 2:
                name, color = random.choice(agents)
                n += 1
                s.start(random.choice(titles), name, color, task_id=f"demo-live-{n}")
            elif doing:
                t = random.choice(doing)
                if t.get("needs_input"):
                    if random.random() < .25:
                        s.update(t["id"], t.get("progress", 0), "User answered — resuming")
                    time.sleep(random.uniform(3, 7))
                    continue
                if t.get("review"):
                    if random.random() < .3:   # the "user" signs off
                        s.update(t["id"], 100, t.get("result") or "Approved", status="done")
                    time.sleep(random.uniform(3, 7))
                    continue
                if random.random() < .07 and not any(x.get("needs_input") for x in doing):
                    q = random.choice(["Deploy to staging or prod?", "OK to drop the legacy column?",
                                        "Retry limit: 3 or 5?", "Use the new API key or rotate?"])
                    s.ask(t["id"], q)
                    _notify(s.dir, f"{t.get('agent') or 'An agent'} needs your input", t["title"], q)
                    time.sleep(random.uniform(3, 7))
                    continue
                p = min(100, t.get("progress", 0) + random.randint(3, 9))
                if p >= 100:
                    result = random.choice(["Shipped", "Merged", "All tests green"])
                    s.review(t["id"], result)
                    _notify(s.dir, f"{t.get('agent') or 'An agent'} ready for review", t["title"], result)
                else:
                    s.update(t["id"], p, random.choice(steps))
            time.sleep(random.uniform(3, 7))
    except KeyboardInterrupt:
        pass


def cmd_clear(a):
    print(f"archived {len(_store().clear_done())} done task(s)")


def cmd_rm(a):
    s = _store()
    ids = [t["id"] for t in s.load() if t["id"].startswith("demo-")] if a.demo else [a.id]
    n = 0
    for i in ids:
        gone = {t["id"] for t in s.load()}
        if i not in gone:   # already taken out with its parent
            continue
        s.delete(i)
        n += len(gone - {t["id"] for t in s.load()})   # a parent takes its subtasks with it
    print(f"removed {n} task(s)")


def cmd_claim(a):
    name = _agent_name(a)
    t = _store().claim(a.id, name, a.color or os.environ.get("AGENTBOARD_COLOR"), a.force)
    print(f"claimed {t['id']} as {name}")


def cmd_update(a):
    s = _store()
    kids = [k for k in s.load() if k.get("parent_id") == a.id]
    t = s.update(a.id, a.progress, a.text)
    if kids:
        print(f"{t['id']}: Σ {t['progress']}% (a parent's % is computed from its subtasks; update those instead)")
    elif t["status"] == "done" and t.get("parent_id"):
        print(f"{t['id']}: 100% — subtask done")
    else:
        print(f"{t['id']}: {t['progress']}%")


def _read_body(a):
    """--body-file wins if given (handles multi-line content without shell quoting pain)."""
    if a.body_file:
        try:
            return Path(a.body_file).expanduser().read_text()
        except OSError as e:
            raise BoardError(f"could not read --body-file: {e}") from e
    return a.body


def cmd_ask(a):
    s = _store()
    t = s.ask(a.id, a.question, _read_body(a))
    _notify(s.dir, f"{t.get('agent') or 'An agent'} needs your input", t["title"], a.question)
    print(f"{t['id']}: waiting on user — {a.question}")


def cmd_review(a):
    s = _store()
    t = s.review(a.id, a.text, _read_body(a))
    if t.get("parent_id"):
        print(f"{t['id']}: subtask finished (100%) — subtasks have no review step; review the parent, {t['parent_id']}, when the deliverable is ready")
        return
    _notify(s.dir, f"{t.get('agent') or 'An agent'} ready for review", t["title"], a.text)
    print(f"{t['id']}: ready for review — waiting on the user to mark it done")


def cmd_done(a):
    # a.text, not `a.text or ""`: an explicit "" would blank out a review's result/status_text
    # (store.update treats "not None" as "replace it"); omitting it should leave them alone.
    _store().update(a.id, text=a.text, status="done")
    print(f"{a.id}: done")


def cmd_prompt(a):
    s = _store()
    all_tasks = s.load()
    text, warnings = promptlib.build_prompt(Store.get(all_tasks, a.id), s.dir, public=a.public, tasks=all_tasks)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(text)


def cmd_rebuild(a):
    s = _store()
    ids = [t["id"] for t in s.load()] if a.all else [a.id]
    with s.transaction() as tasks:
        for tid in ids:
            t = Store.get(tasks, tid)
            t["prompt"], warnings = promptlib.build_prompt(t, s.dir, tasks=tasks)
            for w in warnings:
                print(f"{tid}: warning: {w}", file=sys.stderr)
    print(f"rebuilt {len(ids)} prompt(s)")


def cmd_serve(a):
    serve(_store(), a.port, not a.no_open)


def main(argv=None):
    p = argparse.ArgumentParser(prog="agentboard", description="Kanban board for parallel CLI agents")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help)
        sp.set_defaults(fn=fn)
        return sp

    add("init", cmd_init, "create .agentboard/ in the current directory")
    sp = add("add", cmd_add, "add a task")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--status", choices=["backlog", "todo", "doing", "done"],
                    help="column to add to (default: backlog; a subtask follows its parent)")
    sp.add_argument("--ctx", action="append", default=[], metavar="PROVIDER[:ARG]")
    sp.add_argument("--id")
    sp.add_argument("--project", help="project id to tie this task to (a subtask inherits its parent's)")
    sp.add_argument("--parent", metavar="ID", help="make this a subtask of that task (one level deep)")
    sp.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID",
                     help="task id this depends on; repeat for multiple")
    sp = add("list", cmd_list, "list tasks")
    sp.add_argument("--status")
    sp.add_argument("--all", action="store_true", help="include archived tasks")
    sp.add_argument("--stale", action="store_true",
                     help="only show Doing tasks idle past the stale threshold (default "
                          f"{hudlib.ABANDONED_MIN} min; see [board].stale_minutes in config.toml)")
    sp = add("tail", cmd_tail, "watch board activity live in the terminal (same feed as the HUD); Ctrl+C stops")
    sp.add_argument("-n", "--lines", type=int, default=10, help="recent events to print before following (default 10; 0 for none)")
    sp.add_argument("--interval", type=float, default=1.0, help="poll interval in seconds (default 1)")
    sp = add("report", cmd_report, "markdown recap of what was completed today (or --date), by agent — for a standup or daily log")
    sp.add_argument("--date", help="YYYY-MM-DD (default: today)")
    add("clear", cmd_clear, "archive all Done tasks (kept for history and the HUD)")
    sp = add("spawn", cmd_spawn, "open a new Terminal window per name, cd here, launch an agent in each (macOS)")
    sp.add_argument("names", help="comma-separated session names, e.g. atlas,scribe,bolt")
    sp.add_argument("--colors", help="comma-separated hex colors, one per name (default: built-in palette)")
    sp.add_argument("--cmd", default="claude", help="command to run in each window (default: claude)")
    sp.add_argument("--delay", type=float, default=3.0,
                     help="seconds to wait for the agent to start before sending /rename and /color (default: 3)")
    sp.add_argument("--no-rename", action="store_true", help="skip sending /rename and /color after launch")
    sp = add("start", cmd_start, "agent: announce new work (creates a task in doing, prints its id)")
    sp.add_argument("title")
    sp.add_argument("-d", "--description")
    sp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    sp.add_argument("--color", help="(or $AGENTBOARD_COLOR)")
    sp.add_argument("--id")
    sp.add_argument("--project", help="project id to tie this task to")
    sp.add_argument("--parent", metavar="ID", help="start it as a subtask of that task (one level deep)")
    sp.add_argument("--blocked-by", action="append", dest="blocked_by", metavar="ID",
                     help="task id this depends on; repeat for multiple")
    sp.add_argument("--force", action="store_true", help="start even if a blocker is not done")
    sp = add("instructions", cmd_instructions, "print a snippet to paste into CLAUDE.md / AGENTS.md")
    sp.add_argument("--absolute", action="store_true", help="embed absolute command + board path (works from any directory)")
    sp = add("demo", cmd_demo, "add sample tasks to see the board")
    sp.add_argument("--live", action="store_true", help="then simulate agents working (great with the HUD)")
    sp.add_argument("--minutes", type=float, default=5)
    sp = add("rm", cmd_rm, "remove a task")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--demo", action="store_true", help="remove all demo tasks")
    sp = add("claim", cmd_claim, "agent: take a task (moves it to doing)")
    sp.add_argument("id")
    sp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    sp.add_argument("--color")
    sp.add_argument("--force", action="store_true")
    sp = add("update", cmd_update, "agent: report progress")
    sp.add_argument("id")
    sp.add_argument("progress", type=int)
    sp.add_argument("text", nargs="?")
    sp = add("ask", cmd_ask, "agent: flag that you are blocked on the user")
    sp.add_argument("id")
    sp.add_argument("question")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--body", help="markdown body (recap/diff/report) shown in the detail panel")
    g.add_argument("--body-file", help="read --body from a file instead (handles multi-line content)")
    sp = add("review", cmd_review, "agent: work complete — hand to the user for sign-off")
    sp.add_argument("id")
    sp.add_argument("text", help="one-line result")
    g = sp.add_mutually_exclusive_group()
    g.add_argument("--body", help="markdown body (recap/diff/report) shown in the detail panel")
    g.add_argument("--body-file", help="read --body from a file instead (handles multi-line content)")
    sp = add("done", cmd_done, "USER-APPROVED completion (agents: use review instead)")
    sp.add_argument("id")
    sp.add_argument("text", nargs="?")
    sp = add("wait", cmd_wait, "block (polling) until a task reaches a status — sync on another agent's work")
    sp.add_argument("id")
    sp.add_argument("--status", default="done", choices=["backlog", "todo", "doing", "done", "review", "needs_input"],
                     help="target to wait for (default: done); 'review'/'needs_input' also always end the wait early "
                          "when they aren't the target, since those are blocked-on-a-human moments too")
    sp.add_argument("--interval", type=float, default=2.0, help="poll interval in seconds (default 2)")
    sp.add_argument("--timeout", type=float, help="give up and exit nonzero after this many seconds (default: wait forever)")
    sp = add("prompt", cmd_prompt, "print a task's assembled prompt")
    sp.add_argument("id")
    sp.add_argument("--public", action="store_true", help="skip private providers")
    sp = add("rebuild", cmd_rebuild, "re-run providers and store prompt(s)")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--all", action="store_true")
    sp = add("serve", cmd_serve, "run the board at http://localhost:8765")
    sp.add_argument("--port", type=int, default=8765)
    sp.add_argument("--no-open", action="store_true")

    sp = sub.add_parser("project", help="manage projects (groups of tasks)")
    psub = sp.add_subparsers(dest="project_cmd", required=True)

    def padd(name, fn, help):
        psp = psub.add_parser(name, help=help)
        psp.set_defaults(fn=fn)
        return psp

    psp = padd("add", cmd_project_add, "create a project")
    psp.add_argument("name")
    psp.add_argument("-d", "--description")
    psp.add_argument("--color")
    psp.add_argument("--id")
    padd("list", cmd_project_list, "list projects")
    psp = padd("edit", cmd_project_edit, "rename/recolor/describe a project")
    psp.add_argument("id")
    psp.add_argument("--name")
    psp.add_argument("--color")
    psp.add_argument("--description")
    psp = padd("rm", cmd_project_rm, "delete a project (untying any tasks from it)")
    psp.add_argument("id")
    psp = padd("assign", cmd_project_assign, "tie an existing task to a project")
    psp.add_argument("task_id")
    psp.add_argument("project_id")
    psp = padd("unassign", cmd_project_unassign, "untie a task from its project")
    psp.add_argument("task_id")

    sp = sub.add_parser("chat", help="shared channel for agents (and you) to self-organize, visible on the board")
    csub = sp.add_subparsers(dest="chat_cmd", required=True)

    def cadd(name, fn, help):
        csp = csub.add_parser(name, help=help)
        csp.set_defaults(fn=fn)
        return csp

    csp = cadd("send", cmd_chat_send, "post a message (who's on what, asking for a hand, handing off work)")
    csp.add_argument("text")
    csp.add_argument("--name", help="your session name (or $AGENTBOARD_NAME)")
    csp.add_argument("--user", action="store_true", help="post as the human (Troy), not an agent")
    csp = cadd("tail", cmd_chat_tail, "read recent messages, optionally following live")
    csp.add_argument("--limit", type=int, default=30)
    csp.add_argument("--follow", action="store_true", help="keep polling and print new messages (Ctrl+C stops)")
    csp.add_argument("--interval", type=float, default=2.0, help="seconds between polls with --follow")

    a = p.parse_args(argv)
    if a.cmd == "rebuild" and not (a.all or a.id):
        p.error("give a task id or --all")
    if a.cmd == "rm" and not (a.demo or a.id):
        p.error("give a task id or --demo")
    try:
        a.fn(a)
    except BoardError as e:
        sys.exit(f"agentboard: {e}")


if __name__ == "__main__":
    main()
